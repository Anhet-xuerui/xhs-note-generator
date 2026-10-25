"""手写编排：单轮 run 与三轮循环。

D5 换成 LangGraph 时，这里的分支会原样搬进条件边；在此之前用朴素的 while + 纯函数判定，
让每个退出条件都能被单测直接命中（§7：退出条件不交给模型）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any, TypeVar

from app.agents.cover import run_cover
from app.agents.gatekeeper import run_gatekeeper
from app.agents.humanize import run_humanize
from app.agents.planner import run_planner
from app.agents.profile import run_profile
from app.agents.reader import run_reader
from app.agents.writer import run_writer
from app.graph.decisions import decide, passed
from app.llm.client import Deps, NodeCallFailed
from app.schemas import Usage
from app.state import RunState

T = TypeVar("T")


def _usage_delta(before: Usage | None, after: Usage | None) -> dict[str, float | int]:
    """节点自己的花费 = 调用前后的实测差，不是估算（约束 5）。"""
    start = before or Usage()
    end = after or Usage()
    return {
        "input_tokens": end.input_tokens - start.input_tokens,
        "output_tokens": end.output_tokens - start.output_tokens,
        "cost_cny": round(end.cost_cny - start.cost_cny, 6),
        "calls": end.calls - start.calls,
    }


def _default_serialize(value: Any) -> Any:
    dump = getattr(value, "model_dump", None)
    return dump() if callable(dump) else value


def _identity(state: RunState, node: str, round_no: int) -> tuple[int, int]:
    """一次调用在时间线上的坐标：`seq` 全局递增，`attempt` 是本节点本轮第几次。"""
    seq = state.get("node_seq", 0) + 1
    state["node_seq"] = seq
    attempts = state.setdefault("node_attempts", {})
    key = f"{node}:{round_no}"
    attempt = attempts.get(key, 0) + 1
    attempts[key] = attempt
    return seq, attempt


async def _step(
    state: RunState,
    deps: Deps,
    node: str,
    round_no: int,
    factory: Callable[[], Awaitable[T]],
    *,
    serialize: Callable[[T], Any] | None = None,
) -> T:
    """包一层节点调用，把起止事件推给前端（CLI 场景下 event_sink 为 None，零开销）。

    起止之外还发：产物、耗时、本次花费、prompt 指纹、是否走了兜底（D10-5/D10-12）。
    """
    sink = deps.event_sink
    seq, attempt = _identity(state, node, round_no)
    started = perf_counter()
    usage_before = state.get("usage")
    degraded_before = len(state.get("degraded_nodes") or [])

    def base() -> dict[str, Any]:
        return {"node": node, "round": round_no, "attempt": attempt, "seq": seq}

    if sink is not None:
        sink({"event": "node_start", **base()})

    try:
        result = await factory()
    except Exception as exc:
        if sink is not None:
            sink(
                {
                    "event": "node_end",
                    **base(),
                    "ok": False,
                    "degraded": False,
                    "error": str(exc),
                    "elapsed_ms": int((perf_counter() - started) * 1000),
                    "usage": _usage_delta(usage_before, state.get("usage")),
                    "prompt_sha8": deps.prompts.sha8(node),
                }
            )
        raise

    if sink is not None:
        fresh = (state.get("degraded_nodes") or [])[degraded_before:]
        event: dict[str, Any] = {
            "event": "node_end",
            **base(),
            "ok": True,
            "degraded": bool(fresh),
            "elapsed_ms": int((perf_counter() - started) * 1000),
            "usage": _usage_delta(usage_before, state.get("usage")),
            "prompt_sha8": deps.prompts.sha8(node),
            "product": (serialize or _default_serialize)(result),
        }
        if fresh:
            event["degraded_reason"] = fresh[-1].get("reason", "")
        sink(event)
    return result


_WRITER_PRODUCT = lambda pair: {  # noqa: E731 - 一行能让调用点保持可读
    "draft": pair[0].model_dump(),
    "responses": [response.model_dump() for response in pair[1]],
}
_COVER_PRODUCT = lambda text: {"cover_text": text}  # noqa: E731


async def run_once(state: RunState, deps: Deps) -> RunState:
    """画像官 → 策划 → 主笔 → 读者，跑一轮。"""
    state["round"] = 1
    state["status"] = "running"

    state["profile"] = await _step(state, deps, "profile", 1, lambda: run_profile(state, deps))
    state["angle"] = await _step(state, deps, "planner", 1, lambda: run_planner(state, deps))

    try:
        draft, _responses = await _step(
            state, deps, "writer", 1, lambda: run_writer(state, deps), serialize=_WRITER_PRODUCT
        )
    except NodeCallFailed:
        # §10：主笔不降级——没有稿子就没有意义。
        state["status"] = "failed"
        state["draft"] = None
        return state

    state["draft"] = draft
    state.setdefault("draft_history", []).append(draft)

    verdict = await _step(state, deps, "reader", 1, lambda: run_reader(state, deps))
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
        state["profile"] = await _step(state, deps, "profile", 1, lambda: run_profile(state, deps))
    except NodeCallFailed:
        # §10 没有给画像官降级：没有约束卡就不知道「这个人能说什么」，直接失败。
        state["status"] = "failed"
        return state

    try:
        state["angle"] = await _step(state, deps, "planner", 1, lambda: run_planner(state, deps))
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
                state,
                deps,
                "writer",
                state["round"],
                lambda: run_writer(state, deps),
                serialize=_WRITER_PRODUCT,
            )
        except NodeCallFailed:
            state["status"] = "failed"
            state["draft"] = None
            return state

        state["draft"] = draft
        state["draft_history"].append(draft)
        verdict = await _step(
            state, deps, "reader", state["round"], lambda: run_reader(state, deps)
        )
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
                state, deps, "planner", state["round"], lambda: run_planner(state, deps)
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

    await _step(
        state, deps, "cover", state["round"], lambda: run_cover(state, deps), serialize=_COVER_PRODUCT
    )
    humanized = await _step(
        state, deps, "humanizer", state["round"], lambda: run_humanize(state, deps)
    )
    gate = await _step(
        state,
        deps,
        "gatekeeper",
        state["round"],
        lambda: run_gatekeeper(state, deps, humanized),
    )

    if not gate.passed:
        # 命中项再修一次（不计轮次），然后复核；仍不过就 gate_blocked。
        hints = [
            finding.model_dump()
            for finding in gate.findings
            if finding.severity == "blocking" and not finding.false_positive
        ]
        humanized = await _step(
            state,
            deps,
            "humanizer",
            state["round"],
            lambda: run_humanize(state, deps, hints=hints),
        )
        gate = await _step(
            state,
            deps,
            "gatekeeper",
            state["round"],
            lambda: run_gatekeeper(state, deps, humanized),
        )

    if not gate.passed:
        state["status"] = "gate_blocked"
    return state
