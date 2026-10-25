"""运行状态（设计文档 §10）。

节点之间**只**通过 `RunState` 交换数据；`total=False` 是因为刚开跑时大部分键还没值。
`gate` 在 D1–D3 恒为 None（守门人是 D4），类型先放宽，D4 收窄为 `GateResult`。
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from app.schemas import (
    Angle,
    Draft,
    HumanizedDraft,
    Objection,
    ProfileCard,
    RunInput,
    SmellReport,
    Usage,
    Verdict,
    WriterResponse,
)

RunStatus = Literal["running", "passed", "exhausted", "failed", "gate_blocked"]


class RunState(TypedDict, total=False):
    run_id: str
    input: RunInput
    profile: ProfileCard | None
    angle: Angle | None
    angle_history: list[Angle]
    round: int
    draft: Draft | None
    draft_history: list[Draft]
    verdicts: list[Verdict]
    feedback_history: list[list[Objection]]
    writer_responses: list[WriterResponse]
    best_round: int | None
    status: RunStatus
    usage: Usage
    gate: Any | None
    reading_scene: str
    degraded_rounds: list[int]
    humanized: HumanizedDraft | None
    smell: SmellReport | None
    # D10：本 run 用的 prompt 快照（role → {text, sha8, source}）
    prompts: dict[str, dict[str, str]]
    # D10-12：谁走了兜底、为什么。`_step` 靠它给 node_end 打 degraded 标。
    degraded_nodes: list[dict[str, str | int]]
    # D10-5：事件身份，供时间线排序与标「复核」
    node_seq: int
    node_attempts: dict[str, int]


def mark_degraded(state: RunState, node: str, reason: str) -> None:
    """兜底也必须留痕：调用失败不能被界面显示成「完成」（D10-12）。"""
    state.setdefault("degraded_nodes", []).append(
        {"node": node, "round": state.get("round", 1), "reason": reason}
    )


def merge_usage(state: RunState, usage: Usage) -> Usage:
    """把一次调用的用量并入 state：每个节点调用完就累加，不允许事后估算（§10）。"""
    current = state.get("usage")
    merged = usage if current is None else current.merge(usage)
    state["usage"] = merged
    return merged
