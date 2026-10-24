"""人味校订节点（Task 4，§8：只做减法 + 保真回退）。"""

from __future__ import annotations

from app.agents.humanize import HumanizeOutput, run_humanize
from app.llm.client import NodeCallFailed
from app.schemas import ChangeLog, Draft, ProfileCard

from tests.helpers import deps_with, make_state

ANCHOR = "被二房东坑过一个月押金"


def make_humanize_state(body: str) -> dict:
    state = make_state()
    state["profile"] = ProfileCard(
        nickname="沪漂打工人",
        age_range="25-30",
        city="上海",
        occupation="市场营销",
        goal="涨粉",
        tone=["自嘲"],
        real_material=[ANCHOR],
        taboo=[],
        anchors=[ANCHOR],
    )
    state["draft"] = Draft(title="租房第三年才知道的事", body=body, tags=["租房"], cover_text="押金差点没要回来")
    return state


SMELLY = f"{ANCHOR}，月租5200元。那段时间我成长了很多，也很治愈。"
CLEAN = f"{ANCHOR}，月租5200元。那段时间我瘦了六斤，天天跑派出所。"


async def test_prompt_carries_the_hits_to_rewrite():
    deps = deps_with(
        HumanizeOutput(title="t", body=CLEAN, tags=["租房"], changes=[ChangeLog(before="成长了很多", after="瘦了六斤", category="abstract_noun", reason="换成具体变化")])
    )

    out = await run_humanize(make_humanize_state(SMELLY), deps)

    assert "abstract_noun" in deps.llm.users[0]          # 命中项进了 prompt
    assert deps.llm.roles == ["humanizer"]
    assert out.fidelity == "passed"
    assert out.smell_after < out.smell_before


async def test_reverts_when_number_lost():
    body = f"{ANCHOR}，月租5200元。那段时间我成长了很多，也很治愈。"
    lossy = f"{ANCHOR}，月租五千多元。那段时间我瘦了六斤，天天跑派出所。"
    deps = deps_with(HumanizeOutput(title="t", body=lossy, tags=["租房"], changes=[]))

    out = await run_humanize(make_humanize_state(body), deps)

    assert out.fidelity == "reverted"
    assert out.body == body
    assert out.smell_after == out.smell_before


async def test_skips_on_llm_failure():
    body = SMELLY
    deps = deps_with(NodeCallFailed("humanizer", 1, RuntimeError("boom")))

    out = await run_humanize(make_humanize_state(body), deps)

    assert out.fidelity == "skipped"
    assert out.body == body
