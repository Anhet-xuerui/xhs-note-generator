"""两两比较（E1 修订版）：不比绝对分，直接问「这两篇你更想收藏哪篇」。

绝对打分要求判定器在脑子里维持一把尺子；两两比较只要求一次局部判断，
按 §16 的预案，这是判别力不达标时该先试的改法。

位置偏好是这类比较的经典偏差，所以每对都问两次、互换 A/B 顺序：
两次指向同一篇才算一致，否则记 tie，并单独统计不一致率。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.context import build_reader_context
from app.llm.client import Deps
from app.schemas import Draft, PersonaInput, RunInput, Usage

PAIR_SYSTEM = """你是这篇小红书笔记的目标读者。你在信息流里同时刷到两篇笔记，
只能收藏一篇——哪一篇你会更想收藏（以后遇到同样的事，你会翻出来照着做）？

不要评价文笔，不要说「各有千秋」，必须选一篇。
输出 JSON：{"winner": "A" 或 "B", "reason": "一句话"}"""


class PairChoice(BaseModel):
    winner: str = Field(pattern="^[AB]$")
    reason: str = ""


@dataclass(frozen=True)
class PairComparison:
    winner: str  # "a" / "b" / "tie"
    consistent: bool
    usage: Usage


def _note(draft: Draft, persona: PersonaInput) -> dict:
    context = build_reader_context(
        {"input": RunInput(persona=persona, topic="评测"), "draft": draft, "round": 1}
    )
    return context["note"]


async def _ask(first: Draft, second: Draft, persona: PersonaInput, deps: Deps):
    payload = {
        "reader_profile": {
            "age_range": persona.age_range,
            "city": persona.city,
            "occupation": persona.occupation,
        },
        "note_A": _note(first, persona),
        "note_B": _note(second, persona),
    }
    return await deps.llm.structured(
        role="reader",
        system=PAIR_SYSTEM,
        user=json.dumps(payload, ensure_ascii=False),
        schema=PairChoice,
    )


async def compare_pair(a: Draft, b: Draft, persona: PersonaInput, deps: Deps) -> PairComparison:
    forward = await _ask(a, b, persona, deps)
    backward = await _ask(b, a, persona, deps)

    # 换序后选 "A" 等于选了 b：映射回原始位置再比。
    first_pick = "a" if forward.value.winner == "A" else "b"
    second_pick = "b" if backward.value.winner == "A" else "a"

    return PairComparison(
        winner=first_pick if first_pick == second_pick else "tie",
        consistent=first_pick == second_pick,
        usage=forward.usage.merge(backward.usage),
    )
