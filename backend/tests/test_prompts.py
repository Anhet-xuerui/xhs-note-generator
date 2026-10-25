"""prompt 默认层与 PromptSet（D10 Task 1）。

只证明三件事：七角色齐全、指纹稳定、agent 真的从 `Deps.prompts` 取文本。
"""

from __future__ import annotations

from app.prompts import DEFAULTS, ROLES, PromptSet, prompt_sha8


def test_seven_roles_in_fixed_order() -> None:
    assert ROLES == (
        "profile",
        "planner",
        "writer",
        "reader",
        "cover",
        "humanizer",
        "gatekeeper",
    )
    assert set(DEFAULTS) == set(ROLES)


def test_default_set_is_all_nonempty_and_sourced_default() -> None:
    pset = PromptSet.defaults()

    assert all(pset.text(role).strip() for role in ROLES)
    assert pset.edited_roles() == []
    assert set(pset.record()) == set(ROLES)
    assert all(item["source"] == "default" for item in pset.record().values())


def test_prompt_sha8_is_stable_and_eight_chars() -> None:
    assert prompt_sha8("abc") == prompt_sha8("abc")
    assert prompt_sha8("abc") != prompt_sha8("abd")
    assert len(prompt_sha8("abc")) == 8


def test_with_text_marks_role_edited_and_leaves_others_alone() -> None:
    pset = PromptSet.defaults().with_text("writer", "改过的")

    assert pset.text("writer") == "改过的"
    assert pset.edited_roles() == ["writer"]
    assert pset.text("reader") == DEFAULTS["reader"]


async def test_agent_reads_prompt_from_deps() -> None:
    from app.agents.profile import run_profile
    from app.llm.client import Deps
    from tests.helpers import FakeLLM, make_card, make_settings, make_state

    llm = FakeLLM(make_card())
    deps = Deps(
        llm=llm,
        settings=make_settings(),
        prompts=PromptSet.defaults().with_text("profile", "改过的画像官 prompt"),
    )

    await run_profile(make_state(), deps)

    assert llm.systems == ["改过的画像官 prompt"]
