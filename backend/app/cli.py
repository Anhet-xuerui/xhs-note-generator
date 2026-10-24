"""命令行入口：关掉页面也能跑（§3 A2）。

    python -m app.cli run --persona scripts/personas/p01.json --topic "租房第一年"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from pydantic import ValidationError

from app.agents.planner import PlannerContractError
from app.config import ProviderNotConfigured, Settings, UnknownModelPrice
from app.evaluation.corpus import build_corpus
from app.evaluation.report import EvalBundle, synthetic_bundle
from app.evaluation.report import html as eval_html
from app.evaluation.report import markdown as eval_markdown
from app.evaluation.runners import run_e1, run_e2, run_e3
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


def _run_eval(args) -> int:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        bundle = synthetic_bundle()
    else:
        settings = Settings.load()
        deps = Deps(llm=LLMClient(settings), settings=settings)
        swapped = _swapped_reader(settings)
        topics = _load_topics()[: args.topics]
        personas = _load_personas()

        corpus = asyncio.run(build_corpus(topics, deps, personas=personas))
        e1 = asyncio.run(run_e1(corpus, deps))
        e2 = asyncio.run(run_e2(corpus, deps, swapped))
        e3 = {
            "A": asyncio.run(run_e3(topics[: args.pairs], deps, deps, mode="A", personas=personas)),
            "B": asyncio.run(run_e3(topics[: args.pairs], deps, deps, mode="B", personas=personas)),
            "C": asyncio.run(run_e3(topics[: args.pairs], swapped, deps, mode="C", personas=personas)),
        }
        host = (settings.reader_base_url or "").split("//")[-1].split("/")[0]
        bundle = EvalBundle(
            topics=topics,
            corpus_n=len(corpus.items),
            prompt_sha=e1.prompt_sha,
            writer_model=settings.writer_model,
            reader_model=settings.reader_model or "",
            reader_host=host,
            e1=e1,
            e2=e2,
            e3=e3,
        )

    (out_dir / "report.md").write_text(eval_markdown(bundle), encoding="utf-8")
    (out_dir / "report.html").write_text(eval_html(bundle), encoding="utf-8")
    print(f"评测报告已写入：{out_dir / 'report.md'} 与 report.html")
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
