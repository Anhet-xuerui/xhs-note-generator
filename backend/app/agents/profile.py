"""画像官：把画像原文压成结构化约束卡（§6）。

`real_material` 是整条流程反 AI 味的地基，所以**代码**兜底：模型改写原料一律覆盖回原文，
anchors 必须落在原料之内，taboo 必须进 cannot_say。这些是契约，不是提示词建议。

prompt 文本在 `app/prompts/defaults.py`，运行时从 `deps.prompts` 取（D10-1）。
"""

from __future__ import annotations

import json

from app.context import build_profile_context
from app.llm.client import Deps
from app.schemas import ProfileCard
from app.state import RunState, merge_usage


async def run_profile(state: RunState, deps: Deps) -> ProfileCard:
    context = build_profile_context(state)
    result = await deps.llm.structured(
        role="profile",
        system=deps.prompts.text("profile"),
        user=json.dumps(context, ensure_ascii=False),
        schema=ProfileCard,
    )
    merge_usage(state, result.usage)

    persona = state["input"].persona
    card = result.value
    # 原料与禁区以输入为准：模型只负责摘取和展开，不负责改写事实。
    card.real_material = list(persona.real_material)
    card.taboo = list(persona.taboo)
    card.anchors = [a for a in card.anchors if a in persona.real_material]
    if not card.anchors:
        # 模型改写了措辞时会全被过滤掉；留空会让 §8 的保真校验变成永真（评审 I8）。
        card.anchors = list(persona.real_material[:2])
    for banned in persona.taboo:
        if banned not in card.cannot_say:
            card.cannot_say.append(banned)
    return card
