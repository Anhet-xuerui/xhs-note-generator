"""封面角色（Task 1，§6：只看标题与首句，牺牲信息量换点击）。"""

from __future__ import annotations

from app.agents.cover import CoverText, run_cover

from app.schemas import Draft

from tests.helpers import deps_with, make_state

MARKER = "第二句才出现的独特标记"


def state_with_body() -> dict:
    state = make_state()
    state["draft"] = Draft(
        title="租房第三年，我才知道中介不会告诉你的三件事",
        body=f"第一句：租房第一年我就踩坑了。{MARKER}，中介笑得很热情。",
        tags=["租房"],
    )
    return state


async def test_cover_sees_only_title_and_first_sentence():
    deps = deps_with(CoverText(cover_text="中介没说的三件事"))

    await run_cover(state_with_body(), deps)

    sent = deps.llm.users[0]
    assert '"title"' in sent
    assert '"first_sentence"' in sent
    assert MARKER not in sent            # 正文其余部分不出现在上下文里
    assert deps.llm.roles == ["cover"]


async def test_cover_truncates_to_twelve_chars():
    deps = deps_with(CoverText(cover_text="这是一句明显超过十二个字的封面文案"))

    text = await run_cover(state_with_body(), deps)

    assert len(text) == 12


async def test_cover_writes_back_to_draft():
    state = state_with_body()
    deps = deps_with(CoverText(cover_text="押金差点没要回来"))

    await run_cover(state, deps)

    assert state["draft"].cover_text == "押金差点没要回来"
