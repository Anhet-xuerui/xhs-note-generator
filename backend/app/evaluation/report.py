"""评测报告：markdown 给人读，单文件 HTML 给面试官点开（§14）。"""

from __future__ import annotations

import html as htmllib
from dataclasses import dataclass, field
from typing import Any

from app.evaluation.runners import E1Result, E2Result, E3Row
from app.schemas import Usage


@dataclass(frozen=True)
class EvalBundle:
    topics: list[str]
    corpus_n: int
    prompt_sha: str
    writer_model: str
    reader_model: str
    reader_host: str
    e1: E1Result
    e2: E2Result
    e3: dict[str, E3Row] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"


def _num(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _kappa_ok(value: float | None) -> bool:
    """§12 的判据是 click 与 save 两个字段的 κ 都要 ≥ 0.6，只查一个会把结论说反。"""
    return value is not None and value >= 0.6


def _verdict_line(name: str, ok: bool) -> str:
    return f"- **{name}**：{'达成' if ok else '未达成'}"


def markdown(bundle: EvalBundle) -> str:
    e1, e2, e3 = bundle.e1, bundle.e2, bundle.e3
    lines = [
        "# 评测报告：多角色讨论到底值不值",
        "",
        f"- 主题数 N = {len(bundle.topics)}，三档稿共 {bundle.corpus_n * 3} 篇",
        f"- 读者 prompt 指纹：`{bundle.prompt_sha}`（改过 prompt 就不再是同一组数据）",
        f"- 写作模型：`{bundle.writer_model}`；读者模型：`{bundle.reader_model}`（`{bundle.reader_host}`）",
        "",
        "## E1 判别力（construct validity）",
        "",
        "同一批三档稿交给读者打分，看它能不能把 good / mid / bad 排对。",
        "",
        "| 指标 | 值 | 判据 |",
        "|---|---|---|",
        f"| 排序正确率 | {_pct(e1.ordering_accuracy)} | ≥ 80% 有判别力 |",
        f"| Kendall τ | {_num(e1.kendall_tau)} | 越接近 1 越好 |",
    ]
    for variant, accuracy in sorted(e1.by_weights.items()):
        lines.append(f"| 权重 ×{variant} 下的正确率 | {_pct(accuracy)} | 敏感性检查 |")
    lines += [
        "",
        _verdict_line("判别力 ≥ 80%", e1.ordering_accuracy >= 0.8),
        _verdict_line("权重 ±30% 结论稳定", not e1.sensitive),
        "",
        "## E2 双厂商一致性（reliability）",
        "",
        "| 指标 | 值 | 判据 |",
        "|---|---|---|",
        f"| click 的 Cohen κ | {_num(e2.kappa_click)} | ≥ 0.6 可接受 |",
        f"| save 的 Cohen κ | {_num(e2.kappa_save)} | ≥ 0.6 可接受 |",
        f"| score 的 Spearman ρ | {_num(e2.spearman_rho)} | 越接近 1 越好 |",
        "",
        _verdict_line(
            "两家厂商判定一致（click 与 save 的 κ 都 ≥ 0.6）",
            _kappa_ok(e2.kappa_click) and _kappa_ok(e2.kappa_save),
        ),
        "",
        "## E3 消融（A 裸模型 / B 七角色 / C 同厂商读者）",
        "",
        "| 组 | 配置 | 通过率 | 平均分 | tokens | 成本(元) | 时延(s) | 平均 AI 味 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    labels = {"A": "裸模型单次成稿", "B": "完整链路", "C": "完整链路 + 读者同厂商"}
    for mode in ("A", "B", "C"):
        row = e3.get(mode)
        if row is None:
            continue
        lines.append(
            f"| {mode} | {labels[mode]} | {_pct(row.pass_rate)} | {_num(row.mean_score)} | "
            f"{row.tokens} | {row.cost_cny} | {row.elapsed_s} | {_num(row.smell_before, 1)} |"
        )
    lines += [
        "",
        "> 评分口径：三组成稿都由**同一个读者实例**事后打分；A 组的评分调用成本单列在它的 tokens/成本里。",
        "",
        "## 局限",
        "",
        "- 没有真实互动数据：判定器的有效性只有内部验证（判别力 + 一致性），不能证明它等同于真实用户。",
        "- `bad` 档是反向 prompt 构造的，它定义的是「我们能想到的 AI 味」，不是全部。",
        "- 标签级、选题级的效果没有验证；本轮也没有人工盲评（E4）。",
        "- 规模缩小后统计量噪声变大，报告里的 N 就是实际样本数，不要外推。",
    ]
    if bundle.notes:
        lines += ["", "## 备注", ""] + [f"- {note}" for note in bundle.notes]
    lines.append("")
    return "\n".join(lines)


STYLE = """
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;max-width:900px;margin:40px auto;padding:0 20px;line-height:1.7;color:#1f2328}
h1{font-size:26px}h2{font-size:18px;margin-top:32px;padding-bottom:6px;border-bottom:1px solid #e5e7eb}
table{border-collapse:collapse;width:100%;font-size:14px;margin:10px 0}
th,td{border:1px solid #e5e7eb;padding:6px 10px;text-align:left}th{background:#f9fafb}
.ok{color:#047857;font-weight:600}.bad{color:#b91c1c;font-weight:600}.note{color:#6b7280;font-size:13px}
"""


def _esc(value: Any) -> str:
    return htmllib.escape("" if value is None else str(value))


def _html_table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def html(bundle: EvalBundle) -> str:
    e1, e2, e3 = bundle.e1, bundle.e2, bundle.e3
    e1_rows = [
        ["排序正确率", _pct(e1.ordering_accuracy), "≥ 80% 有判别力"],
        ["Kendall τ", _num(e1.kendall_tau), "越接近 1 越好"],
    ] + [
        [f"权重 ×{variant}", _pct(accuracy), "敏感性检查"]
        for variant, accuracy in sorted(e1.by_weights.items())
    ]
    e2_rows = [
        ["click 的 Cohen κ", _num(e2.kappa_click), "≥ 0.6 可接受"],
        ["save 的 Cohen κ", _num(e2.kappa_save), "≥ 0.6 可接受"],
        ["score 的 Spearman ρ", _num(e2.spearman_rho), "越接近 1 越好"],
    ]
    labels = {"A": "裸模型单次成稿", "B": "完整链路", "C": "完整链路 + 读者同厂商"}
    e3_rows = [
        [mode, labels[mode], _pct(row.pass_rate), _num(row.mean_score), str(row.tokens), str(row.cost_cny), str(row.elapsed_s)]
        for mode, row in ((m, e3.get(m)) for m in ("A", "B", "C"))
        if row is not None
    ]

    def verdict(name: str, ok: bool) -> str:
        css = "ok" if ok else "bad"
        mark = "✓" if ok else "✗"
        return f"<div class={css!r}>{mark} {_esc(name)}</div>"

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>评测报告</title><style>{STYLE}</style></head>
<body>
<h1>评测报告：多角色讨论到底值不值</h1>
<div class="note">主题数 N = {len(bundle.topics)}，三档稿共 {bundle.corpus_n * 3} 篇 ·
读者 prompt 指纹 <code>{_esc(bundle.prompt_sha)}</code><br>
写作模型 <code>{_esc(bundle.writer_model)}</code> · 读者模型 <code>{_esc(bundle.reader_model)}</code></div>

<h2>E1 判别力</h2>
{_html_table(["指标", "值", "判据"], e1_rows)}
{verdict("判别力 ≥ 80%", e1.ordering_accuracy >= 0.8)}
{verdict("权重 ±30% 结论稳定", not e1.sensitive)}

<h2>E2 双厂商一致性</h2>
{_html_table(["指标", "值", "判据"], e2_rows)}
{verdict("两家厂商判定一致（click 与 save 的 κ 都 ≥ 0.6）", _kappa_ok(e2.kappa_click) and _kappa_ok(e2.kappa_save))}

<h2>E3 消融</h2>
{_html_table(["组", "配置", "通过率", "平均分", "tokens", "成本(元)", "时延(s)"], e3_rows)}
<div class="note">三组成稿都由同一个读者实例事后打分；A 组的评分调用成本单列在它的 tokens/成本里。</div>

<h2>局限</h2>
<ul>
<li>没有真实互动数据，判定器只有内部验证，不能等同于真实用户。</li>
<li><code>bad</code> 档由反向 prompt 构造，只覆盖我们想到的 AI 味。</li>
<li>标签级、选题级效果未验证；本轮无人工盲评。</li>
<li>样本量见上；缩小规模后统计噪声变大，不要外推。</li>
</ul>
</body></html>
"""


def synthetic_bundle() -> EvalBundle:
    """`--dry-run` 用：不调 API，验证模板与链路。"""
    return EvalBundle(
        topics=["（dry-run）租房第一年", "（dry-run）通勤两小时"],
        corpus_n=2,
        prompt_sha="dryrun000000",
        writer_model="dry-run-writer",
        reader_model="dry-run-reader",
        reader_host="dry-run",
        e1=E1Result(
            n=2,
            ordering_accuracy=0.5,
            kendall_tau=0.33,
            by_weights={1.0: 0.5, 1.3: 0.5, 0.7: 0.5},
            sensitive=False,
            prompt_sha="dryrun000000",
            usage=Usage(),
        ),
        e2=E2Result(
            n=6,
            kappa_click=0.4,
            kappa_save=None,
            spearman_rho=0.6,
            prompt_sha="dryrun000000",
            usage=Usage(),
        ),
        e3={
            "A": E3Row("A", 2, 0.0, 1.2, 1200, 0.01, 5.0, 40.0),
            "B": E3Row("B", 2, 0.5, 3.4, 8000, 0.06, 70.0, 12.0),
            "C": E3Row("C", 2, 0.5, 3.4, 8000, 0.06, 68.0, 12.0),
        },
        notes=["这是 dry-run 的合成数据，不代表任何真实结论。"],
    )
