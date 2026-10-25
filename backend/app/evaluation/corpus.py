"""三档稿语料（§12 E1）：good = 跑通的成稿，mid = 首轮稿，bad = 反向 prompt 生成。"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.graph.loop import run_loop
from app.llm.client import Deps
from app.schemas import Draft, PersonaInput, RunInput, Usage
from app.state import RunState

# 反向 prompt 本身就是「AI 味」的可操作定义，值得单独展示给面试官看。
BAD_PROMPT = """你要写一篇小红书笔记，但请故意写成最典型的 AI 味，用来做对照实验：

- 多用抽象形容词与名词：焦虑、成长、治愈、松弛感、内耗。
- 多用排比、对仗和四字词。
- 不要出现任何具体数字、时间、地点或对话。
- 每一段结尾加一个 emoji。
- 结尾加一句升华（「愿你」「其实我们都在」这类）。

输出 JSON：{"title": "...", "body": "...", "tags": ["..."]}"""

DEFAULT_PERSONA = PersonaInput(
    nickname="沪漂第三年的市场岗打工人",
    age_range="25-30",
    city="上海",
    occupation="市场营销",
    goal="涨粉",
    tone=["自嘲", "直给"],
    real_material=[
        "被二房东坑过一个月押金，最后靠报警才要回来一半",
        "中介带我看房时说这栋楼隔音差，我当时没听懂",
    ],
    taboo=["不提公司名"],
)


@dataclass(frozen=True)
class CorpusItem:
    topic: str
    persona: PersonaInput
    good: Draft
    mid: Draft
    bad: Draft
    good_fallback: bool


@dataclass(frozen=True)
class Corpus:
    items: list[CorpusItem] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


def _state(persona: PersonaInput, topic: str) -> RunState:
    return {
        "run_id": "eval",
        "input": RunInput(persona=persona, topic=topic),
        "profile": None,
        "angle": None,
        "angle_history": [],
        "round": 0,
        "draft": None,
        "draft_history": [],
        "verdicts": [],
        "feedback_history": [],
        "writer_responses": [],
        "best_round": None,
        "status": "running",
    }


async def _generate_bad(topic: str, persona: PersonaInput, deps: Deps) -> Draft:
    import json

    result = await deps.llm.structured(
        role="writer",
        system=BAD_PROMPT,
        user=json.dumps({"topic": topic, "persona": persona.model_dump()}, ensure_ascii=False),
        schema=Draft,
    )
    return result.value


async def build_corpus(
    topics: list[str],
    deps: Deps,
    *,
    personas: list[PersonaInput] | None = None,
) -> Corpus:
    """每个主题跑一次完整讨论循环，取交付稿当 good、首轮稿当 mid，再反向生成 bad。"""
    roster = personas or [DEFAULT_PERSONA]
    items: list[CorpusItem] = []
    total = Usage()

    for index, topic in enumerate(topics):
        persona = roster[index % len(roster)]
        state = await run_loop(_state(persona, topic), deps)

        history = state.get("draft_history") or []
        delivered = state.get("draft")
        if delivered is None or not history:
            continue  # 主笔就挂了，这条主题不进语料

        total = total.merge(state.get("usage") or Usage())
        items.append(
            CorpusItem(
                topic=topic,
                persona=persona,
                good=delivered,
                mid=history[0],
                bad=await _generate_bad(topic, persona, deps),
                good_fallback=state.get("status") != "passed",
            )
        )

    return Corpus(items=items, usage=total)
