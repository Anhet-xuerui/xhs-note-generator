"""策划节点（Task 6，§7：三个角度、自选其一、必须写清为什么不选另外两个）。"""

from __future__ import annotations

import json

import pytest

from app.agents.planner import AngleSet, PlannerContractError, run_planner
from app.schemas import Angle, PersonaInput, ProfileCard, RunInput
from tests.helpers import deps_with


def make_state():
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
    return {"input": RunInput(persona=persona, topic="租房第一年"), "profile": card, "round": 1}


def angle(hook: str, *, chosen: bool = False, why: str = "另外两个太抒情，给不了可执行信息") -> Angle:
    return Angle(
        hook=hook,
        target_emotion="实用",
        title_candidates=["中介不会告诉你的三件事", "租房三年才懂的事"],
        chosen=chosen,
        why_not_others=why,
    )


async def test_picks_chosen_not_first():
    state = make_state()
    payload = AngleSet(angles=[angle("第一个"), angle("第二个"), angle("第三个角度", chosen=True)])

    result = await run_planner(state, deps_with(payload))

    assert result.hook == "第三个角度"


async def test_rejects_zero_chosen():
    state = make_state()
    payload = AngleSet(angles=[angle("a"), angle("b"), angle("c")])

    with pytest.raises(PlannerContractError, match="chosen"):
        await run_planner(state, deps_with(payload, payload))  # 违反契约会重出一次，两次都不合规才抛


async def test_rejects_two_chosen():
    state = make_state()
    payload = AngleSet(angles=[angle("a", chosen=True), angle("b", chosen=True), angle("c")])

    with pytest.raises(PlannerContractError, match="chosen"):
        await run_planner(state, deps_with(payload, payload))  # 违反契约会重出一次，两次都不合规才抛


async def test_rejects_empty_why_not_others():
    state = make_state()
    payload = AngleSet(angles=[angle("a", chosen=True, why=""), angle("b"), angle("c")])

    with pytest.raises(PlannerContractError, match="why_not_others"):
        await run_planner(state, deps_with(payload, payload))


async def test_planner_sees_no_draft():
    state = make_state()
    deps = deps_with(AngleSet(angles=[angle("a", chosen=True), angle("b"), angle("c")]))

    await run_planner(state, deps)

    sent = deps.llm.users[0]
    assert "body" not in json.dumps(json.loads(sent), ensure_ascii=False)

async def test_contract_violation_triggers_exactly_one_retry():
    """第一次不合规、第二次合规：应当带着错误重出一次而不是直接失败。"""
    state = make_state()
    bad = AngleSet(angles=[angle("a"), angle("b"), angle("c")])
    good = AngleSet(angles=[angle("a", chosen=True), angle("b"), angle("c")])
    deps = deps_with(bad, good)

    result = await run_planner(state, deps)

    assert result.hook == "a"
    assert len(deps.llm.roles) == 2
    assert "违反了契约" in deps.llm.users[1]
