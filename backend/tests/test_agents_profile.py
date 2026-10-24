"""画像官节点（Task 5，§6：把画像压成「这个人能说什么、不能说什么」）。"""

from __future__ import annotations

from app.agents.profile import run_profile
from app.schemas import PersonaInput, ProfileCard, RunInput

from tests.helpers import deps_with


def make_state(real_material=None, taboo=None):
    persona = PersonaInput(
        nickname="沪漂第三年的市场岗打工人",
        age_range="25-30",
        city="上海",
        occupation="市场营销",
        goal="涨粉",
        tone=["自嘲", "直给"],
        real_material=real_material or ["被二房东坑过一个月押金", "中介说这栋楼隔音差"],
        taboo=taboo if taboo is not None else ["不提公司名"],
    )
    return {"input": RunInput(persona=persona, topic="租房第一年我终于搞清楚的事")}


def card(**overrides) -> ProfileCard:
    base = dict(
        nickname="沪漂打工人",
        age_range="25-30",
        city="上海",
        occupation="市场营销",
        goal="涨粉",
        tone=["自嘲"],
        real_material=["被改写的原料"],
        taboo=[],
        anchors=["被二房东坑过一个月押金"],
        can_say=["我跟你说"],
        cannot_say=[],
    )
    base.update(overrides)
    return ProfileCard(**base)


async def test_profile_card_keeps_every_real_material_item():
    """模型改写原料时必须被覆盖回原文：原料是反 AI 味的地基（§6）。"""
    state = make_state()

    result = await run_profile(state, deps_with(card()))

    assert result.real_material == ["被二房东坑过一个月押金", "中介说这栋楼隔音差"]


async def test_anchors_outside_real_material_are_dropped():
    state = make_state()

    result = await run_profile(state, deps_with(card(anchors=["被二房东坑过一个月押金", "编造的锚点"])))

    assert result.anchors == ["被二房东坑过一个月押金"]


async def test_taboo_is_carried_into_cannot_say():
    state = make_state(taboo=["不提公司名", "不承诺涨粉"])

    result = await run_profile(state, deps_with(card(cannot_say=[])))

    assert set(state["input"].persona.taboo) <= set(result.cannot_say)


async def test_usage_is_accumulated_into_state():
    state = make_state()

    await run_profile(state, deps_with(card()))

    assert state["usage"].calls == 1
