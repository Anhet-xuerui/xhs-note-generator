"""读者节点（Task 8，§6：我是刷到这条的陌生人，不是审稿人）。"""

from __future__ import annotations

from app.agents.reader import render_reader_prompt, run_reader
from app.llm.client import NodeCallFailed
from app.schemas import (
    Angle,
    Draft,
    Objection,
    PersonaInput,
    ProfileCard,
    RunInput,
    Verdict,
)

from tests.helpers import deps_with

BODY = "第一年我什么都不懂。签约那天中介笑得很热情！后来我才知道隔音是硬伤？"


def make_state(*, body: str = BODY, verdicts: list[Verdict] | None = None):
    persona = PersonaInput(
        nickname="沪漂打工人",
        age_range="25-30",
        city="上海",
        occupation="市场营销",
        goal="涨粉",
        tone=["自嘲"],
        real_material=["被二房东坑过一个月押金"],
        taboo=[],
    )
    card = ProfileCard(**persona.model_dump(), anchors=["被二房东坑过一个月押金"])
    return {
        "input": RunInput(persona=persona, topic="租房第一年"),
        "profile": card,
        "angle": Angle(
            hook="把租房踩坑写成清单",
            target_emotion="实用",
            title_candidates=["a", "b"],
            chosen=True,
            why_not_others="x",
        ),
        "round": 1,
        "draft": Draft(title="租房第三年才知道的事", cover_text="中介没说的三件事", body=body, tags=["租房"]),
        "verdicts": list(verdicts or []),
    }


def verdict(**overrides) -> Verdict:
    base = dict(click=True, click_reason="标题具体", read_through=0.9, save=True, comment_intent=False)
    base.update(overrides)
    return Verdict(**base)


async def test_reader_uses_reader_provider():
    deps = deps_with(verdict())

    await run_reader(make_state(), deps)

    assert deps.llm.roles == ["reader"]


async def test_degrades_to_previous_verdict():
    previous = verdict(click=False, save=False, read_through=0.2)
    state = make_state(verdicts=[verdict(), previous])
    deps = deps_with(NodeCallFailed("reader", 2, RuntimeError("boom")))

    result = await run_reader(state, deps)

    assert result is previous


async def test_degrades_to_failing_verdict_on_round_one():
    deps = deps_with(NodeCallFailed("reader", 2, RuntimeError("boom")))

    result = await run_reader(make_state(), deps)

    assert (result.click, result.save, result.read_through) == (False, False, 0.0)


async def test_drops_objections_whose_quote_is_not_in_body():
    hallucinated = verdict(
        objections=[
            Objection(
                sentence_index=2,
                quote="正文里根本没有这句",
                problem_type="ai_smell",
                suggestion="删掉",
            )
        ]
    )

    result = await run_reader(make_state(), deps_with(hallucinated))

    assert result.objections == []


async def test_empty_body_does_not_crash():
    result = await run_reader(make_state(body=""), deps_with(verdict()))

    assert result.objections == []


def test_prompt_carries_note_and_sentences_but_not_real_material():
    from app.context import build_reader_context

    prompt = render_reader_prompt(build_reader_context(make_state()))

    assert "租房第三年才知道的事" in prompt
    assert "sentences" in prompt                      # 句子编号是判定卡的锚点
    assert "被二房东坑过一个月押金" not in prompt      # §6 第一条隔离
