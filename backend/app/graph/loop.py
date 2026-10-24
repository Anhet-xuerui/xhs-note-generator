"""手写编排：单轮 run 与三轮循环。

D5 换成 LangGraph 时，这里的分支会原样搬进条件边；在此之前用朴素的 while + 纯函数判定，
让每个退出条件都能被单测直接命中（§7：退出条件不交给模型）。
"""

from __future__ import annotations

from app.agents.planner import run_planner
from app.agents.profile import run_profile
from app.agents.reader import run_reader
from app.agents.writer import run_writer
from app.graph.decisions import decide, passed
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
    """三轮上限内的讨论循环；每轮结尾由 `decide()` 决定继续/换角度/停止。"""
    for key in ("angle_history", "draft_history", "verdicts", "feedback_history"):
        state.setdefault(key, [])
    state["status"] = "running"

    state["profile"] = await run_profile(state, deps)
    state["angle"] = await run_planner(state, deps)

    decision = None
    while True:
        state["round"] = len(state["verdicts"]) + 1
        try:
            draft, _responses = await run_writer(state, deps)
        except NodeCallFailed:
            state["status"] = "failed"
            state["draft"] = None
            return state

        state["draft"] = draft
        state["draft_history"].append(draft)
        verdict = await run_reader(state, deps)
        state["feedback_history"].append(list(verdict.objections))

        decision = decide(state["verdicts"], state["angle_history"])
        if decision.action == "stop":
            break
        if decision.action == "new_angle":
            # 重开角度最多一次：旧角度也进 history，len(history) 到 2 就锁死（§7）。
            state["angle_history"].append(state["angle"])
            state["angle"] = await run_planner(state, deps)
            state["angle_history"].append(state["angle"])

    assert decision is not None
    state["status"] = decision.status
    state["best_round"] = decision.best_round
    if decision.best_round is not None:
        # 未通过时交分数最高那一版，不是最后一版（§7）。
        state["draft"] = state["draft_history"][decision.best_round - 1]
    return state
