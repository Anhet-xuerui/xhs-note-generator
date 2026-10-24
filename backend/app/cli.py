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
from app.graph.decisions import evaluate
from app.graph.loop import finish_draft, run_loop
from app.llm.client import Deps, LLMClient, NodeCallFailed
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
    args = parser.parse_args(argv)

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

    print(json.dumps(result_payload(state), ensure_ascii=False, indent=2))
    return 0 if state.get("status") != "failed" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
