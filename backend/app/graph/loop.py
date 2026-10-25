"""手写编排：单轮 run 与三轮循环。

D5 换成 LangGraph 时，这里的分支会原样搬进条件边；在此之前用朴素的 while + 纯函数判定，
让每个退出条件都能被单测直接命中（§7：退出条件不交给模型）。
"""

from __future__ import annotations

from app.agents.cover import run_cover
from app.agents.gatekeeper import run_gatekeeper
from app.agents.humanize import run_humanize
from app.agents.planner import run_planner
from app.agents.profile import run_profile
from app.agents.reader import run_reader
from app.agents.writer import run_writer
from app.graph.decisions import decide, passed
from app.llm.client import Deps, NodeCallFailed
from app.state import RunState


async def _step(deps: Deps, node: str, round_no: int, factory):
    """包一层节点调用，把起止事件推给前端（CLI 场景下 event_sink 为 None，零开销）。"""
    sink = deps.event_sink
    if sink is not None:
        sink({"event": "node_start", "node": node, "round": round_no})
    result = await factory()
    if sink is not None:
        sink({"event": "node_end", "node": node, "round": round_no})
    return result


async def run_once(state: RunState, deps: Deps) -> RunState:
    """画像官 → 策划 → 主笔 → 读者，跑一轮。"""
    state["round"] = 1
    state["status"] = "running"

    state["profile"] = await _step(deps, "profile", 1, lambda: run_profile(state, deps))
    state["angle"] = await _step(deps, "planner", 1, lambda: run_planner(state, deps))

    try:
        draft, _responses = await _step(deps, "writer", 1, lambda: run_writer(state, deps))
    except NodeCallFailed:
        # §10：主笔不降级——没有稿子就没有意义。
        state["status"] = "failed"
        state["draft"] = None
        return state

    state["draft"] = draft
    state.setdefault("draft_history", []).append(draft)

    verdict = await _step(deps, "reader", 1, lambda: run_reader(state, deps))
    state.setdefault("feedback_history", []).append(list(verdict.objections))

    ok = passed(verdict)
    state["status"] = "passed" if ok else "exhausted"
    state["best_round"] = None if ok else 1
    return state


async def run_loop(state: RunState, deps: Deps) -> RunState:
    """三轮上限内的讨论循环；每轮结尾由 `decide()` 决定继续/换角度/停止。"""
    state.setdefault("angle_history", [])
    state.setdefault("draft_history", [])
    state.setdefault("verdicts", [])
    state.setdefault("feedback_history", [])
    state.setdefault("degraded_rounds", [])
    state["status"] = "running"

    try:
        state["profile"] = await _step(deps, "profile", 1, lambda: run_profile(state, deps))
    except NodeCallFailed:
        # §10 没有给画像官降级：没有约束卡就不知道「这个人能说什么」，直接失败。
        state["status"] = "failed"
        return state

    try:
        state["angle"] = await _step(deps, "planner", 1, lambda: run_planner(state, deps))
    except NodeCallFailed:
        # §10：策划失败用兜底值——没有角度就沿用已有角度，实在没有才失败。
        if state.get("angle") is None:
            state["status"] = "failed"
            return state

    decision = None
    while True:
        state["round"] = len(state["verdicts"]) + 1
        try:
            draft, _responses = await _step(
                deps, "writer", state["round"], lambda: run_writer(state, deps)
            )
        except NodeCallFailed:
            state["status"] = "failed"
            state["draft"] = None
            return state

        state["draft"] = draft
        state["draft_history"].append(draft)
        verdict = await _step(deps, "reader", state["round"], lambda: run_reader(state, deps))
        state["feedback_history"].append(list(verdict.objections))

        # §10：第 1 轮读者就挂了 → 直接走未通过路径，不再白烧两轮（评审 I2）。
        if state["round"] == 1 and state["degraded_rounds"]:
            state["status"] = "exhausted"
            state["best_round"] = 1
            break

        decision = decide(
            state["verdicts"], state["angle_history"], degraded_rounds=state["degraded_rounds"]
        )
        if decision.action == "stop":
            break
        if decision.action == "new_angle":
            # 重开角度最多一次：旧角度也进 history，len(history) 到 2 就锁死（§7）。
            previous = state.get("angle")
            if previous is not None:
                state["angle_history"].append(previous)
            reopened = await _step(
                deps, "planner", state["round"], lambda: run_planner(state, deps)
            )
            state["angle"] = reopened
            state["angle_history"].append(reopened)

    if decision is not None:
        state["status"] = decision.status
        state["best_round"] = decision.best_round
    if state["best_round"] is not None:
        # 未通过时交分数最高那一版，不是最后一版（§7）。
        state["draft"] = state["draft_history"][state["best_round"] - 1]
    return state


async def finish_draft(state: RunState, deps: Deps) -> RunState:
    """定稿之后的三个角色：封面 → 人味校订 → 守门人（§7 的主循环尾部）。

    守门人必须排在最后：人味校订会改写句子，改写可能引入违禁词。
    """
    if state.get("status") == "failed" or state.get("draft") is None:
        return state

    await _step(deps, "cover", state["round"], lambda: run_cover(state, deps))
    humanized = await _step(deps, "humanizer", state["round"], lambda: run_humanize(state, deps))
    gate = await _step(
        deps, "gatekeeper", state["round"], lambda: run_gatekeeper(state, deps, humanized)
    )

    if not gate.passed:
        # 命中项再修一次（不计轮次），然后复核；仍不过就 gate_blocked。
        hints = [
            finding.model_dump()
            for finding in gate.findings
            if finding.severity == "blocking" and not finding.false_positive
        ]
        humanized = await _step(
            deps, "humanizer", state["round"], lambda: run_humanize(state, deps, hints=hints)
        )
        gate = await _step(
            deps, "gatekeeper", state["round"], lambda: run_gatekeeper(state, deps, humanized)
        )

    if not gate.passed:
        state["status"] = "gate_blocked"
    return state
