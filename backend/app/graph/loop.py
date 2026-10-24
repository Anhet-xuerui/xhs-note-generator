"""手写编排：单轮 run 与后续三轮循环。

D5 换成 LangGraph 时，这里的分支逻辑原样搬进条件边；在此之前用一个朴素的顺序流程，
让每个退出条件都能被单测直接命中。
"""

from __future__ import annotations

from app.agents.planner import run_planner
from app.agents.profile import run_profile
from app.agents.reader import run_reader
from app.agents.writer import run_writer
from app.graph.decisions import passed
from app.llm.client import Deps, NodeCallFailed
from app.state import RunState


async def run_once(state: RunState, deps: Deps) -> RunState:
    """画像官 → 策划 → 主笔 → 读者，跑一轮。"""
    state["round"] = 1
    state["status"] = "running"

    state["profile"] = await run_profile(state, deps)
    state["angle"] = await run_planner(state, deps)

    try:
        draft, _responses = await run_writer(state, deps)
    except NodeCallFailed:
        # §10：主笔不降级——没有稿子就没有意义。
        state["status"] = "failed"
        state["draft"] = None
        return state

    state["draft"] = draft
    state.setdefault("draft_history", []).append(draft)

    verdict = await run_reader(state, deps)
    state.setdefault("feedback_history", []).append(list(verdict.objections))

    ok = passed(verdict)
    state["status"] = "passed" if ok else "exhausted"
    state["best_round"] = None if ok else 1
    return state


async def run_loop(state: RunState, deps: Deps) -> RunState:
    """当前只跑一轮；三轮循环在 Task 10 补全（签名不变）。"""
    return await run_once(state, deps)
