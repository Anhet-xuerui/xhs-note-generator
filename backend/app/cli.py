"""命令行入口：关掉页面也能跑（§3 A2）。

    python -m app.cli run --persona scripts/personas/p01.json --topic "租房第一年"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import replace
from pathlib import Path

from pydantic import ValidationError

from app.agents.planner import PlannerContractError
from app.config import ProviderNotConfigured, Settings, UnknownModelPrice
from app.evaluation.aggregate import summarize
from app.evaluation.corpus import build_corpus
from app.evaluation.report import EvalBundle, synthetic_bundle
from app.evaluation.report import html as eval_html
from app.evaluation.report import markdown as eval_markdown
from app.evaluation.runners import run_e1, run_e1_pairwise, run_e2, run_e3
from app.graph.decisions import evaluate
from app.graph.loop import finish_draft, run_loop
from app.llm.client import Deps, LLMClient, NodeCallFailed
from app.report.html import render_report
from app.report.trace import append_event, build_trace, read_events
from app.schemas import PersonaInput, RunInput, Usage
from app.state import RunState


def build_deps() -> Deps:
    """唯一构造 Settings + LLMClient 的地方（测试通过 monkeypatch 替换它）。"""
    settings = Settings.load()
    return Deps(llm=LLMClient(settings), settings=settings)


def new_state(persona: PersonaInput, topic: str) -> RunState:
    return {
        "run_id": uuid.uuid4().hex[:12],
        "input": RunInput(persona=persona, topic=topic),
        "profile": None,
        "angle": None,
        "angle_history": [],
        "round": 0,
        "draft": None,
        "draft_history": [],
        "verdicts": [],
        "feedback_history": [],
        "writer_responses": [],
        "best_round": None,
        "status": "running",
    }


def result_payload(state: RunState) -> dict:
    draft = state.get("draft")
    usage = state.get("usage") or Usage()
    verdicts = state.get("verdicts") or []
    best = state.get("best_round")
    # 未达标项必须描述**交付的那一轮**，不是最后一轮（评审 I3）。
    judged = verdicts[best - 1] if best and 0 <= best - 1 < len(verdicts) else (verdicts[-1] if verdicts else None)
    failed_checks = evaluate(judged).failed_checks if judged else []
    humanized = state.get("humanized")
    smell = state.get("smell")
    gate = state.get("gate")
    return {
        "title": draft.title if draft else None,
        "cover_text": draft.cover_text if draft else None,
        "body": draft.body if draft else None,
        "tags": list(draft.tags) if draft else [],
        "status": state.get("status"),
        "meta": {
            "run_id": state.get("run_id"),
            "rounds_used": len(verdicts),
            "best_round": state.get("best_round"),
            "failed_checks": failed_checks,
            "degraded_rounds": list(state.get("degraded_rounds") or []),
            "smell": (
                {"before": humanized.smell_before, "after": humanized.smell_after, "fidelity": humanized.fidelity}
                if humanized
                else ({"before": smell.score, "after": smell.score, "fidelity": "skipped"} if smell else None)
            ),
            "changes": len(humanized.changes) if humanized else 0,
            "gate_findings": [finding.model_dump() for finding in gate.findings] if gate else [],
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cost_cny": round(usage.cost_cny, 4),
                "calls": usage.calls,
                "elapsed_s": round(usage.elapsed_s, 2),
            },
        },
    }


async def _run_pipeline(state: RunState, deps: Deps) -> RunState:
    """一条完整的 run：讨论循环 + 定稿尾部（封面 / 人味校订 / 守门人）。"""
    return await finish_draft(await run_loop(state, deps), deps)


TOPICS_PATH = Path(__file__).resolve().parents[2] / "eval" / "data" / "topics.json"
PERSONAS_DIR = Path(__file__).resolve().parents[1] / "scripts" / "personas"


def _load_topics() -> list[str]:
    if TOPICS_PATH.exists():
        return json.loads(TOPICS_PATH.read_text(encoding="utf-8"))
    return ["租房第一年我终于搞清楚的事"]


def _load_personas() -> list[PersonaInput]:
    files = sorted(PERSONAS_DIR.glob("*.json"))
    return [PersonaInput.model_validate_json(path.read_text(encoding="utf-8")) for path in files]


def _swapped_reader(settings: Settings) -> Deps:
    """把读者的 provider 换成主笔那家：E2 的第二判定器、E3 的 C 组都靠它。"""
    swapped = settings.model_copy(
        update={
            "reader_base_url": settings.writer_base_url,
            "reader_model": settings.writer_model,
            "reader_api_key": settings.writer_api_key,
        }
    )
    return Deps(llm=LLMClient(swapped), settings=swapped)


async def _one_round(args, settings, deps, swapped, topics, personas) -> EvalBundle:
    corpus = await build_corpus(topics, deps, personas=personas)
    e1 = await run_e1(corpus, deps)
    e1_pair = await run_e1_pairwise(corpus, deps)
    e2 = await run_e2(corpus, deps, swapped)
    e3 = {
        "A": await run_e3(topics[: args.pairs], deps, deps, mode="A", personas=personas),
        "B": await run_e3(topics[: args.pairs], deps, deps, mode="B", personas=personas),
        "C": await run_e3(topics[: args.pairs], swapped, deps, mode="C", personas=personas),
    }
    host = (settings.reader_base_url or "").split("//")[-1].split("/")[0]
    return EvalBundle(
        topics=topics,
        corpus_n=len(corpus.items),
        prompt_sha=e1.prompt_sha,
        writer_model=settings.writer_model,
        reader_model=settings.reader_model or "",
        reader_host=host,
        e1=e1,
        e1_pair=e1_pair,
        e2=e2,
        e3=e3,
    )


def _metrics(bundle: EvalBundle) -> dict[str, float]:
    rows: dict[str, float | None] = {
        "E1 绝对打分正确率": bundle.e1.ordering_accuracy,
        "E1 Kendall τ": bundle.e1.kendall_tau,
        "E2 click κ": bundle.e2.kappa_click,
        "E2 save κ": bundle.e2.kappa_save,
        "E2 score ρ": bundle.e2.spearman_rho,
        "E3 A 通过率": bundle.e3["A"].pass_rate if "A" in bundle.e3 else None,
        "E3 B 通过率": bundle.e3["B"].pass_rate if "B" in bundle.e3 else None,
        "E3 C 通过率": bundle.e3["C"].pass_rate if "C" in bundle.e3 else None,
        "E3 B tokens": float(bundle.e3["B"].tokens) if "B" in bundle.e3 else None,
        "E3 B 成本(元)": bundle.e3["B"].cost_cny if "B" in bundle.e3 else None,
    }
    if bundle.e1_pair is not None:
        rows["E1 两两比较正确率"] = bundle.e1_pair.accuracy
        rows["E1 两两比较 tie 率"] = bundle.e1_pair.tie_rate
    return {key: value for key, value in rows.items() if value is not None}


def _ci_rows(metrics_all: list[dict[str, float]]) -> list[tuple[str, str]]:
    keys = [key for key in metrics_all[0] if all(key in item for item in metrics_all)]
    rows: list[tuple[str, str]] = []
    for key in keys:
        summary = summarize([item[key] for item in metrics_all])
        value = summary.pct() if key.endswith("率") or "κ" in key or "ρ" in key or "τ" in key else summary.label(2)
        rows.append((key, value))
    return rows


async def _evaluate(args) -> EvalBundle:
    """全部实验跑在**同一个事件循环**里：LLMClient 的 httpx 连接是绑定 loop 的。"""
    settings = Settings.load()
    deps = Deps(llm=LLMClient(settings), settings=settings)
    swapped = _swapped_reader(settings)
    topics = _load_topics()[: args.topics]
    personas = _load_personas()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    repeats = max(1, args.repeats)

    metrics_all: list[dict[str, float]] = []
    if args.resume:
        for path in sorted(out_dir.glob("repeat-*.json")):
            metrics_all.append(json.loads(path.read_text(encoding="utf-8")))
        print(f"[eval] 复用已有 {len(metrics_all)} 轮结果", file=sys.stderr)

    bundles: list[EvalBundle] = []
    for index in range(len(metrics_all), repeats):
        print(f"[eval] 第 {index + 1}/{repeats} 轮", file=sys.stderr)
        bundle = await _one_round(args, settings, deps, swapped, topics, personas)
        # 每轮落盘：进程被杀也不丢已完成的轮次
        (out_dir / f"repeat-{index + 1}.json").write_text(
            json.dumps(_metrics(bundle), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (out_dir / f"report-run{index + 1}.md").write_text(eval_markdown(bundle), encoding="utf-8")
        (out_dir / f"report-run{index + 1}.html").write_text(eval_html(bundle), encoding="utf-8")
        metrics_all.append(_metrics(bundle))
        bundles.append(bundle)

    final = bundles[-1] if bundles else synthetic_bundle()
    if len(metrics_all) > 1:
        final = replace(final, ci_rows=_ci_rows(metrics_all))
    return final


def _run_eval(args) -> int:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        bundle = synthetic_bundle()
    else:
        bundle = asyncio.run(_evaluate(args))

    stem = "report-dryrun" if args.dry_run else "report"
    (out_dir / f"{stem}.md").write_text(eval_markdown(bundle), encoding="utf-8")
    (out_dir / f"{stem}.html").write_text(eval_html(bundle), encoding="utf-8")
    print(f"评测报告已写入：{out_dir / (stem + '.md')} 与 {stem}.html")
    return 0


def _load_persona(path: str) -> PersonaInput:
    return PersonaInput.model_validate_json(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(errors="replace")  # GBK 控制台不至于因中文崩溃

    parser = argparse.ArgumentParser(prog="xhs-agent", description="小红书多角色笔记生成")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="跑一次生成")
    run.add_argument("--persona", required=True, help="画像 JSON 文件路径")
    run.add_argument("--topic", required=True, help="笔记主题")
    run.add_argument("--trace-out", default=None, help="把过程事件写到这个 JSONL 文件")

    evaluate = sub.add_parser("eval", help="跑 D9 评测（E1 判别力 / E2 一致性 / E3 消融）")
    evaluate.add_argument("--topics", type=int, default=3, help="E1/E2 用多少个主题")
    evaluate.add_argument("--pairs", type=int, default=3, help="E3 每组跑多少个主题")
    evaluate.add_argument("--out", required=True, help="输出目录（写 report.md 与 report.html）")
    evaluate.add_argument("--dry-run", action="store_true", help="用合成数据渲染报告，不调用任何 API")
    evaluate.add_argument("--repeats", type=int, default=1, help="重复几次（每次重新生成语料），用于均值与 95% CI")
    evaluate.add_argument("--resume", action="store_true", help="复用已有的 repeat-*.json，只跑缺的轮次")

    report = sub.add_parser("report", help="把 JSONL 事件渲染成单文件 HTML 报告")
    report.add_argument("--trace", required=True, help="run 时写出的 JSONL 路径")
    report.add_argument("--out", required=True, help="输出 HTML 路径")
    args = parser.parse_args(argv)

    if args.command == "eval":
        return _run_eval(args)

    if args.command == "report":
        trace_path = Path(args.trace)
        events = read_events(trace_path)
        if not events:
            print(f"读不到事件：{trace_path}", file=sys.stderr)
            return 1
        result = next(
            (event.get("data") or {} for event in reversed(events) if event.get("event") == "result"),
            {},
        )
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(render_report(events, result), encoding="utf-8")
        print(f"报告已写入：{out_path}")
        return 0

    try:
        persona = _load_persona(args.persona)
    except FileNotFoundError:
        print(f"找不到画像文件：{args.persona}", file=sys.stderr)
        return 1
    except ValidationError as exc:
        print(f"画像文件不合规：{args.persona}\n{exc}", file=sys.stderr)
        return 1

    try:
        deps = build_deps()
    except ProviderNotConfigured as exc:
        print(f"配置缺失：{exc}", file=sys.stderr)
        return 1

    try:
        state = asyncio.run(_run_pipeline(new_state(persona, args.topic), deps))
    except (NodeCallFailed, UnknownModelPrice, PlannerContractError) as exc:
        # 跑到一半炸了也要给出可读结果，而不是抛出 traceback（评审 C2）。
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    payload = result_payload(state)
    if args.trace_out:
        trace_path = Path(args.trace_out)
        for event in build_trace(state, payload):
            append_event(trace_path, event)
        payload["meta"]["trace"] = str(trace_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if state.get("status") != "failed" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
