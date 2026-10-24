"""主笔节点（Task 7，§6：具体、像人话、用足 real_material；逐条回应上一轮异议）。"""

from __future__ import annotations

import pytest

from app.agents.writer import WriterContractError, WriterOutput, run_writer
from app.schemas import (
    Angle,
    Draft,
    Objection,
    PersonaInput,
    ProfileCard,
    RunInput,
    WriterResponse,
)
from tests.helpers import deps_with

MATERIAL_A = "被二房东坑过一个月押金"
MATERIAL_B = "中介说这栋楼隔音差"


def make_state(*, with_feedback: bool):
    persona = PersonaInput(
        nickname="沪漂打工人",
        age_range="25-30",
        city="上海",
        occupation="市场营销",
        goal="涨粉",
        tone=["自嘲", "直给"],
        real_material=[MATERIAL_A, MATERIAL_B],
        taboo=[],
    )
    card = ProfileCard(**persona.model_dump(), anchors=[MATERIAL_A, MATERIAL_B])
    state = {
        "input": RunInput(persona=persona, topic="租房第一年"),
        "profile": card,
        "angle": Angle(
            hook="把租房踩坑写成清单",
            target_emotion="实用",
            title_candidates=["a", "b"],
            chosen=True,
            why_not_others="另外两个太抒情",
        ),
        "round": 2 if with_feedback else 1,
        "draft": Draft(title="上一版", body="上一版正文", tags=[]),
    }
    if with_feedback:
        state["feedback_history"] = [
            [
                Objection(sentence_index=1, quote="上一版正文", problem_type="ai_smell", suggestion="删抽象词"),
                Objection(sentence_index=1, quote="上一版正文", problem_type="no_evidence", suggestion="补细节"),
                Objection(sentence_index=1, quote="上一版正文", problem_type="too_long", suggestion="砍一半"),
            ]
        ]
    return state


def good_body() -> str:
    return f"第一年租房，{MATERIAL_A}。后来搬家才发现，{MATERIAL_B}。"


def writer_output(body: str, responses: list[WriterResponse] | None = None) -> WriterOutput:
    return WriterOutput(
        draft=Draft(title="租房第三年才知道的事", body=body, tags=["租房"]),
        responses=responses or [],
    )


async def test_first_round_has_no_responses():
    state = make_state(with_feedback=False)

    draft, responses = await run_writer(state, deps_with(writer_output(good_body(), [
        WriterResponse(objection_index=0, decision="accept", reason="不该有")
    ])))

    assert responses == []
    assert draft.body


async def test_every_objection_gets_a_response():
    state = make_state(with_feedback=True)
    responses = [
        WriterResponse(objection_index=i, decision="accept", reason=f"改第{i}条")
        for i in (0, 1, 2)
    ]

    _, out = await run_writer(state, deps_with(writer_output(good_body(), responses)))

    assert [r.objection_index for r in out] == [0, 1, 2]


async def test_missing_response_is_rejected():
    state = make_state(with_feedback=True)
    partial = [WriterResponse(objection_index=0, decision="accept", reason="只回一条")]

    with pytest.raises(WriterContractError, match="objection_index"):
        await run_writer(state, deps_with(writer_output(good_body(), partial)))


async def test_underused_material_triggers_one_retry():
    """§6：主笔的判据之一是「用足 real_material」。一条都没用时就地重出一次。"""
    state = make_state(with_feedback=False)
    deps = deps_with(
        writer_output("租房第一年，我们都在长大。"),           # 0 条原料
        writer_output(good_body()),                            # 2 条原料
    )

    draft, _ = await run_writer(state, deps)

    assert MATERIAL_A[:6] in draft.body
    assert len(deps.llm.roles) == 2
    assert "real_material" in deps.llm.users[1]


async def test_body_uses_at_least_two_real_material_items():
    state = make_state(with_feedback=True)
    responses = [
        WriterResponse(objection_index=i, decision="reject", reason="这条不适用") for i in range(3)
    ]

    draft, _ = await run_writer(state, deps_with(writer_output(good_body(), responses)))

    hits = sum(1 for m in state["input"].persona.real_material if m[:6] in draft.body)
    assert hits >= 2
