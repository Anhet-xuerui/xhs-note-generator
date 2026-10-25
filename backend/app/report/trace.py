"""过程事件落盘：一行一条 JSON，便于回放与渲染报告。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_trace(state, result: dict[str, Any]) -> list[dict[str, Any]]:
    """把一次 run 的 state 压成报告需要的事件序列。"""
    events: list[dict[str, Any]] = []
    verdicts = state.get("verdicts") or []
    drafts = state.get("draft_history") or []
    for index, verdict in enumerate(verdicts, start=1):
        event: dict[str, Any] = {"event": "round", "round": index, "verdict": verdict.model_dump()}
        if index <= len(drafts):
            event["draft"] = drafts[index - 1].model_dump()
        events.append(event)
    humanized = state.get("humanized")
    if humanized is not None:
        events.append({"event": "smell", "data": humanized.model_dump()})
    gate = state.get("gate")
    if gate is not None:
        events.append({"event": "gate", "data": gate.model_dump()})
    # 报告是唯一活得过重启的证据：七段 prompt 的全文必须跟着走（S1）。
    prompts = state.get("prompts")
    if prompts:
        events.append({"event": "prompts", "data": prompts})
    events.append({"event": "result", "data": result})
    return events
