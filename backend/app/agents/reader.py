"""读者：换一家厂商的模型，看不到写作意图，只回答六个可数字段（§6/§7）。

prompt 文本一旦跑过评测就属于冻结物（§12），改动前先想清楚：改它等于让 E1/E2 作废。
默认文本在 `app/prompts/defaults.py`，运行时从 `deps.prompts` 取；界面上改的那一版记在 run 快照里（D10-3）。
本节点额外做两件事，都在代码里而不是提示词里：

1. 调用失败时降级：有历史判定就沿用上一轮，第 1 轮就失败则按未通过处理（§10）；
2. 引文校验：`Objection.quote` 必须真出现在正文里，否则丢弃——模型会编句子。
"""

from __future__ import annotations

import json

from app.context import build_reader_context
from app.llm.client import Deps, NodeCallFailed
from app.schemas import Verdict
from app.state import RunState, mark_degraded, merge_usage


def render_reader_prompt(context: dict) -> str:
    """把编号句子的笔记正文渲染成 user 消息。"""
    return "【这条笔记】\n" + json.dumps(context, ensure_ascii=False, indent=2)


def _fallback_verdict() -> Verdict:
    return Verdict(
        click=False,
        click_reason="读者调用失败，按未通过处理",
        read_through=0.0,
        save=False,
        comment_intent=False,
        objections=[],
    )


def _drop_hallucinated(verdict: Verdict, body: str) -> Verdict:
    verdict.objections = [o for o in verdict.objections if o.quote and o.quote in body]
    return verdict


async def run_reader(state: RunState, deps: Deps) -> Verdict:
    context = build_reader_context(state)
    try:
        result = await deps.llm.structured(
            role="reader",
            system=deps.prompts.text("reader"),
            model=deps.models.model("reader"),
            user=render_reader_prompt(context),
            schema=Verdict,
        )
    except NodeCallFailed as exc:
        # 失败的那几次调用也花了钱，必须并进用量，否则成本被系统性低估（评审 C1）。
        merge_usage(state, exc.usage)
        state.setdefault("degraded_rounds", []).append(state.get("round", 1))
        history = state.get("verdicts") or []
        # 降级：沿用上一轮判定；第 1 轮就失败则按未通过路径走（§10）。
        fallback = history[-1] if history else _fallback_verdict()
        mark_degraded(state, "reader", "读者调用失败，按未通过处理")
        state.setdefault("verdicts", []).append(fallback)
        return fallback

    merge_usage(state, result.usage)
    draft = state.get("draft")
    body = draft.body if draft else ""
    verdict = _drop_hallucinated(result.value, body)
    state.setdefault("verdicts", []).append(verdict)
    return verdict
