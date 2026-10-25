# mypy: ignore-errors
# 这一层是 LangGraph 泛型 API 的薄适配器：图的状态是运行时 dict，节点仍吃 RunState。
# 把 LangGraph 的 TypeVar 约束与我们的 TypedDict 对齐只会堆满 cast，收益为零；
# 所以只在这个文件关掉类型检查，其余模块仍然严格。
"""LangGraph 编排：把 `run_loop` 的分支搬进条件边。

选它不是为了「流行」，而是状态显式：每次 run 都能落 checkpoint、可中断、可回放（§10）。
节点函数还是原来那七个，判定还是 `decisions.py` 的纯函数——换的只是接线方式。
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from app.agents.planner import run_planner
from app.agents.profile import run_profile
from app.agents.reader import run_reader
from app.agents.writer import run_writer
from app.graph.decisions import decide
from app.graph.loop import finish_draft
from app.llm.client import Deps, NodeCallFailed
from app.state import RunState

ROUTE = {"stop": "finish", "new_angle": "reopen", "continue": "writer"}


def prepare(state: RunState) -> RunState:
    for key in ("angle_history", "draft_history", "verdicts", "feedback_history", "degraded_rounds"):
        state.setdefault(key, [])
    state["status"] = "running"
    return state


def build_graph(deps: Deps, saver: BaseCheckpointSaver | None = None):
    async def profile(state: dict[str, Any]) -> dict[str, Any]:
        state["profile"] = await run_profile(state, deps)
        return state

    async def planner(state: dict[str, Any]) -> dict[str, Any]:
        state["angle"] = await run_planner(state, deps)
        return state

    async def writer(state: dict[str, Any]) -> dict[str, Any]:
        state["round"] = len(state.get("verdicts") or []) + 1
        try:
            draft, _responses = await run_writer(state, deps)
        except NodeCallFailed:
            state["status"] = "failed"
            state["draft"] = None
            return state
        state["draft"] = draft
        state["draft_history"].append(draft)
        return state

    async def reader(state: dict[str, Any]) -> dict[str, Any]:
        verdict = await run_reader(state, deps)
        state["feedback_history"].append(list(verdict.objections))
        return state

    async def judge(state: dict[str, Any]) -> dict[str, Any]:
        """判定必须发生在**普通节点**里：条件边的返回值只用来选路，写回状态不保证生效。"""
        if state.get("status") == "failed":
            state["_action"] = "stop"
            return state
        if state["round"] == 1 and state.get("degraded_rounds"):
            # §10：第 1 轮读者就挂了 → 直接走未通过路径，不再白烧两轮。
            state["status"] = "exhausted"
            state["best_round"] = 1
            state["_action"] = "stop"
            return state
        decision = decide(
            state["verdicts"], state["angle_history"], degraded_rounds=state["degraded_rounds"]
        )
        state["_action"] = decision.action
        state["_decision"] = {
            "action": decision.action,
            "status": decision.status,
            "best_round": decision.best_round,
        }
        return state

    def route(state: dict[str, Any]) -> str:
        return state.get("_action", "stop")

    async def reopen(state: dict[str, Any]) -> dict[str, Any]:
        previous = state.get("angle")
        if previous is not None:
            state["angle_history"].append(previous)
        reopened = await run_planner(state, deps)
        state["angle"] = reopened
        state["angle_history"].append(reopened)
        return state

    async def finish(state: dict[str, Any]) -> dict[str, Any]:
        decision = state.pop("_decision", None)
        if decision is not None:
            state["status"] = decision["status"]
            state["best_round"] = decision["best_round"]
        if state.get("best_round") is not None:
            state["draft"] = state["draft_history"][state["best_round"] - 1]
        await finish_draft(state, deps)
        return state

    graph = StateGraph(dict)
    graph.add_node("profile", profile)
    graph.add_node("planner", planner)
    graph.add_node("writer", writer)
    graph.add_node("reader", reader)
    graph.add_node("judge", judge)
    graph.add_node("reopen", reopen)
    graph.add_node("finish", finish)

    graph.add_edge(START, "profile")
    graph.add_edge("profile", "planner")
    graph.add_edge("planner", "writer")
    graph.add_edge("writer", "reader")
    graph.add_edge("reader", "judge")
    graph.add_conditional_edges("judge", route, ROUTE)
    graph.add_edge("reopen", "writer")
    graph.add_edge("finish", END)

    return graph.compile(checkpointer=saver)


async def run_with_graph(
    state: RunState,
    deps: Deps,
    *,
    saver: BaseCheckpointSaver | None = None,
    thread_id: str = "run",
):
    graph = build_graph(deps, saver)
    config = {"configurable": {"thread_id": thread_id}} if saver is not None else {}
    result = await graph.ainvoke(prepare(dict(state)), config)
    return result, graph, config
