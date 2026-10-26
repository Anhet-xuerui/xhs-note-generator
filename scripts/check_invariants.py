#!/usr/bin/env python3
"""机械校验小红书多角色项目的五条冻结不变式。

唯一真相源是设计文档 docs/superpowers/specs/2026-10-23-xhs-multiagent-design.md
（§6 信息隔离、§7 判定卡与轮次上限、§12 评测口径、§17 已定取舍）。
本脚本不解释「为什么」，只回答「现在有没有被破坏」。

用法：
    python scripts/check_invariants.py --root .
    python scripts/check_invariants.py --root . --app backend/app

退出码：0 = 全部通过（或尚无实现） / 1 = 有违规
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

# --- 冻结值：改这里等于改契约，必须同时改设计文档 -------------------------

VERDICT_FIELDS = {
    "click",
    "click_reason",
    "drop_at_sentence",
    "read_through",
    "save",
    "comment_intent",
    "objections",
}

OBJECTION_FIELDS = {"sentence_index", "quote", "problem_type", "suggestion"}

# 读者节点不许出现的信息：出现即违反 §6 的三条隔离
READER_HIDDEN = {
    "real_material",
    "angle",
    "angle_history",
    "verdicts",
    "feedback_history",
    "previous_objections",
    "taboo",
}

MAX_ROUNDS_VALUE = 3
MAX_ROUNDS_NAMES = {"MAX_ROUNDS", "MAX_ROUND", "ROUND_LIMIT", "ROUNDS_LIMIT"}

FORBIDDEN_IMPORTS = {"playwright", "selenium", "scrapy", "pyppeteer", "snscrape"}
FORBIDDEN_URLS = re.compile(r"xiaohongshu\.(com|cn)|xhslink\.com|xiaohongshu\.net", re.I)

PASS_CONDITION_NAMES = {"passed", "is_passed", "is_pass", "check_passed"}


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[bool, str, str]] = []

    def ok(self, code: str, msg: str) -> None:
        self.rows.append((True, code, msg))

    def fail(self, code: str, msg: str) -> None:
        self.rows.append((False, code, msg))

    def skip(self, code: str, msg: str) -> None:
        self.rows.append((True, code, f"跳过：{msg}"))

    @property
    def failed(self) -> bool:
        return any(not ok for ok, _, _ in self.rows)


def app_modules(app: Path) -> list[Path]:
    return sorted(p for p in app.rglob("*.py") if "__pycache__" not in p.parts)


def parse_all(paths: list[Path], report: "Report") -> dict[Path, ast.Module]:
    """解析失败必须报 FAIL：静默跳过等于给违规开后门。"""
    trees: dict[Path, ast.Module] = {}
    for p in paths:
        try:
            trees[p] = ast.parse(p.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            report.fail("C0", f"{p.name} 无法解析，检查无法进行：{exc}")
    return trees


def classes_named(trees: dict[Path, ast.Module], name: str):
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == name:
                yield path, node


def class_fields(cls: ast.ClassDef) -> set[str]:
    fields: set[str] = set()
    for node in cls.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            fields.add(node.target.id)
        elif isinstance(node, ast.Assign):
            fields |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return fields


def check_schema(report: Report, trees, cls_name: str, expected: set[str], code: str) -> None:
    found = list(classes_named(trees, cls_name))
    if not found:
        report.skip(code, f"未找到 {cls_name} 定义")
        return
    for path, cls in found:
        actual = class_fields(cls)
        extra = actual - expected
        missing = expected - actual
        if extra or missing:
            detail = []
            if extra:
                detail.append(f"多出 {sorted(extra)}")
            if missing:
                detail.append(f"缺少 {sorted(missing)}")
            report.fail(code, f"{path.name}:{cls.lineno} {cls_name} 字段与冻结契约不符——" + "，".join(detail))
        else:
            report.ok(code, f"{path.name}:{cls.lineno} {cls_name} 字段与冻结契约一致")


def identifiers(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            names.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            names.add(sub.attr)
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            names.add(sub.value)
        elif isinstance(sub, ast.keyword) and sub.arg:
            names.add(sub.arg)
    return names


def check_reader_isolation(report: Report, trees) -> None:
    builders = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and "reader" in node.name and "context" in node.name:
                builders.append((path, node))
    if not builders:
        report.skip("C3", "未找到 reader 上下文构造函数")
        return
    for path, fn in builders:
        leaked = READER_HIDDEN & identifiers(fn)
        if leaked:
            report.fail(
                "C3",
                f"{path.name}:{fn.lineno} {fn.name}() 向读者泄露了 {sorted(leaked)}（§6 三条隔离）",
            )
        else:
            report.ok("C3", f"{path.name}:{fn.lineno} {fn.name}() 未泄露读者不该看的信息")


def check_round_cap(report: Report, trees) -> None:
    seen = False
    for path, tree in trees.items():
        for node in tree.body:
            target = None
            value = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target, value = node.target.id, node.value
            if target not in MAX_ROUNDS_NAMES:
                continue
            seen = True
            if not (isinstance(value, ast.Constant) and isinstance(value.value, int)):
                report.fail("C4", f"{path.name}:{node.lineno} {target} 不是字面量整数——轮次上限不允许可配置（§7/§17）")
            elif value.value != MAX_ROUNDS_VALUE:
                report.fail("C4", f"{path.name}:{node.lineno} {target} = {value.value}，冻结值是 {MAX_ROUNDS_VALUE}（§7/§17）")
            else:
                report.ok("C4", f"{path.name}:{node.lineno} {target} = {MAX_ROUNDS_VALUE}，硬编码正确")
    if not seen:
        report.skip("C4", "未找到轮次上限常量")


def check_no_scraping(report: Report, paths: list[Path], trees) -> None:
    bad_imports, bad_urls = [], []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in FORBIDDEN_IMPORTS:
                        bad_imports.append(f"{path.name}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in FORBIDDEN_IMPORTS:
                    bad_imports.append(f"{path.name}:{node.lineno} from {node.module}")
    for path in paths:
        for i, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
            if FORBIDDEN_URLS.search(line):
                bad_urls.append(f"{path.name}:{i}")
    if bad_imports or bad_urls:
        detail = "; ".join(bad_imports + bad_urls)
        report.fail("C5", f"发现采集/发布平台数据的痕迹（§3 N1/N2）：{detail}")
    else:
        report.ok("C5", "未发现爬虫/自动发布痕迹")


def check_single_pass_condition(report: Report, trees) -> None:
    defs = [
        (path, node)
        for path, tree in trees.items()
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in PASS_CONDITION_NAMES
    ]
    if not defs:
        report.skip("C6", "未找到通过条件函数")
    elif len(defs) > 1:
        where = ", ".join(f"{p.name}:{n.lineno}" for p, n in defs)
        report.fail("C6", f"通过条件有多处定义（{where}）——口径必须单一，否则 A/B 与线上判定会漂移（§12）")
    else:
        path, node = defs[0]
        report.ok("C6", f"{path.name}:{node.lineno} {node.name}() 是唯一的通过条件定义")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 xhs 多角色项目的冻结不变式")
    parser.add_argument("--root", default=".", help="仓库根目录，默认当前目录")
    parser.add_argument("--app", default=None, help="应用包目录，默认自动探测 backend/app 或 app")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")  # GBK 控制台不至于因中文崩溃
    except (AttributeError, OSError):
        pass

    root = Path(args.root).resolve()
    app = Path(args.app) if args.app else next(
        (root / c for c in ("backend/app", "app", "src/app") if (root / c).is_dir()),
        None,
    )
    print(f"xhs-invariants  root={root}")
    if app is None or not app.is_dir():
        print("未发现应用包（backend/app 或 app），跳过全部检查——首次落地前属正常。")
        return 0

    paths = app_modules(app)
    if not paths:
        print(f"{app} 下没有 .py，跳过。")
        return 0

    report = Report()
    trees = parse_all(paths, report)
    print(f"扫描 {len(trees)}/{len(paths)} 个模块：{app.relative_to(root) if app.is_relative_to(root) else app}\n")

    check_schema(report, trees, "Verdict", VERDICT_FIELDS, "C1")
    check_schema(report, trees, "Objection", OBJECTION_FIELDS, "C2")
    check_reader_isolation(report, trees)
    check_round_cap(report, trees)
    check_no_scraping(report, paths, trees)
    check_single_pass_condition(report, trees)

    for ok, code, msg in report.rows:
        print(f"[{'ok' if ok else 'FAIL'}] {code}  {msg}")

    failures = [r for r in report.rows if not r[0]]
    print(f"\n{len(report.rows)} 项检查：{len(report.rows) - len(failures)} 通过 / {len(failures)} 违规")
    if failures:
        print("口径以设计文档 §6/§7/§12/§17 为准；要改冻结值，先改文档再改本脚本。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
