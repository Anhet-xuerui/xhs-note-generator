"""按角色裁剪上下文——信息隔离的**唯一**实现处（设计文档 §6）。

三条隔离（改动前先看 §6，破坏它们等于把七个角色退化成同一个模型的七次自我对话）：

1. 读者看不到 `real_material`、策划意图、历史判定；
2. 策划看不到成稿；
3. 主笔看不到规则库全文，只看守门人的具体命中项。

每个 builder 只读白名单字段，不做 prompt 拼接。
"""

from __future__ import annotations

import re

from app.schemas import Angle, PersonaInput, ProfileCard
from app.state import RunState

_SENTENCE_RE = re.compile(r"[^。！？!?\n]+[。！？!?]?")


def split_sentences(text: str) -> list[dict]:
    """按中文标点切句，编号 1-based——给读者的 `sentence_index` 一个真实锚点。"""
    if not text:
        return []
    parts = [s.strip() for s in _SENTENCE_RE.findall(text)]
    return [{"index": i, "text": s} for i, s in enumerate((p for p in parts if p), start=1)]


def _persona(state: RunState) -> PersonaInput:
    return state["input"].persona


def _dump(model) -> dict | None:
    return model.model_dump() if model is not None else None


def build_profile_context(state: RunState) -> dict:
    """画像官：画像原文 + 主题。"""
    return {"persona": _persona(state).model_dump(), "topic": state["input"].topic}


def build_planner_context(state: RunState) -> dict:
    """策划：约束卡 + 上一轮判定卡（**不含成稿全文**）。"""
    verdicts = state.get("verdicts") or []
    card: ProfileCard | None = state.get("profile")
    return {
        "profile": (card or _persona(state)).model_dump(),
        "topic": state["input"].topic,
        "last_verdict": _dump(verdicts[-1]) if verdicts else None,
    }


def build_writer_context(state: RunState) -> dict:
    """主笔：约束卡全量 + 选定角度 + 上一轮 Objection[]（**不含规则库全文**）。"""
    card: ProfileCard | None = state.get("profile")
    angle: Angle | None = state.get("angle")
    feedback = state.get("feedback_history") or []
    gate = state.get("gate")
    # why_not_others 是策划的辩护词，留给策划；带上它会把写法带偏。
    angle_ctx = (
        None
        if angle is None
        else {
            "hook": angle.hook,
            "target_emotion": angle.target_emotion,
            "title_candidates": angle.title_candidates,
        }
    )
    return {
        "round": state.get("round", 1),
        "topic": state["input"].topic,
        "persona": (card or _persona(state)).model_dump(),
        "angle": angle_ctx,
        "previous_objections": [o.model_dump() for o in (feedback[-1] if feedback else [])],
        "previous_draft": _dump(state.get("draft")),
        "gate_findings": list(getattr(gate, "findings", None) or []),
    }


def build_reader_context(state: RunState) -> dict:
    """读者：成稿全文 + 画像的读者侧字段（**不含 real_material**）。"""
    draft = state.get("draft")
    persona = _persona(state)
    body = draft.body if draft else ""

    reader_profile: dict = {
        "age_range": persona.age_range,
        "city": persona.city,
        "occupation": persona.occupation,
    }
    # 刷手机场景不是画像字段；调用方没给就不传，绝不用常量替模型编一个。
    scene = state.get("reading_scene")
    if scene:
        reader_profile["scene"] = scene

    return {
        "reader_profile": reader_profile,
        "note": {
            "title": draft.title if draft else None,
            "cover_text": draft.cover_text if draft else None,
            "body": body,
            "tags": list(draft.tags) if draft else [],
            "sentences": split_sentences(body),
        },
    }
