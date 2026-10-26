"""prompt 默认层与 PromptSet（D10 Task 1）。

只证明三件事：七角色齐全、指纹稳定、agent 真的从 `Deps.prompts` 取文本。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.prompts import DEFAULTS, ROLES, PromptSet, prompt_sha8
from app.prompts.store import (
    READER_FORBIDDEN,
    EmptyPrompt,
    PromptGuardError,
    PromptStore,
    PromptTooLong,
    UnknownPromptRole,
)

CHECKER = Path(__file__).resolve().parents[2] / "scripts" / "check_invariants.py"


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


def test_store_roundtrip_and_reset(tmp_path: Path) -> None:
    path = tmp_path / "prompts.json"
    store = PromptStore(path)

    store.set("writer", "新 prompt")

    assert PromptStore(path).snapshot().text("writer") == "新 prompt"
    assert store.snapshot().sha8("writer") == prompt_sha8("新 prompt")

    store.reset("writer")

    assert store.snapshot().text("writer") == DEFAULTS["writer"]
    assert store.snapshot().edited_roles() == []


def test_reset_all_clears_every_override(tmp_path: Path) -> None:
    store = PromptStore(tmp_path / "p.json")
    store.set("writer", "a")
    store.set("planner", "b")

    assert store.snapshot().edited_roles() == ["planner", "writer"]  # ROLES 的顺序

    store.reset()

    assert store.snapshot().edited_roles() == []


def test_missing_file_means_all_defaults(tmp_path: Path) -> None:
    path = tmp_path / "nope.json"
    store = PromptStore(path)

    assert store.snapshot().edited_roles() == []

    store.set("cover", "x")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert "cover" in data["overrides"]


def test_corrupt_file_falls_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")

    assert PromptStore(path).snapshot().text("writer") == DEFAULTS["writer"]


@pytest.mark.parametrize(
    ("role", "text", "exc"),
    [
        ("nobody", "x", UnknownPromptRole),
        ("writer", "   ", EmptyPrompt),
        ("writer", "x" * 20001, PromptTooLong),
    ],
)
def test_store_rejects_bad_input(tmp_path: Path, role: str, text: str, exc: type[Exception]) -> None:
    with pytest.raises(exc):
        PromptStore(tmp_path / "p.json").set(role, text)


@pytest.mark.parametrize("word", sorted(READER_FORBIDDEN))
def test_reader_guard_blocks_isolated_identifiers(tmp_path: Path, word: str) -> None:
    with pytest.raises(PromptGuardError):
        PromptStore(tmp_path / "p.json").set("reader", f"参考 {word} 打分")

    # 同一个词写给主笔是正当的：主笔本来就该看 real_material。
    PromptStore(tmp_path / "p2.json").set("writer", f"用 {word} 写")


@pytest.mark.parametrize(
    "text",
    ["REAL_MATERIAL", "Real_Material 看一眼", "看real_material打分", "VERDICTS", "Angle"],
)
def test_reader_guard_is_case_insensitive_and_survives_cjk_glue(tmp_path: Path, text: str) -> None:
    """大小写变体与「中文直接贴着英文」都是最容易漏的两种写法。"""
    with pytest.raises(PromptGuardError):
        PromptStore(tmp_path / "p.json").set("reader", text)


def test_reader_guard_does_not_match_inside_english_words(tmp_path: Path) -> None:
    """`angle` 不该把 triangle / rectangle 一起毙掉，否则守卫看起来像 bug。"""
    PromptStore(tmp_path / "p.json").set("reader", "画一个 triangle，再画 rectangle，别画 Angular")


def test_guard_list_matches_checker() -> None:
    """两份清单漂移过一次就是事故：checker 挡住字面，这里挡住写入。"""
    source = CHECKER.read_text(encoding="utf-8")
    body = re.search(r"READER_HIDDEN = \{(.*?)\}", source, re.S)

    assert body is not None
    assert set(re.findall(r'"(\w+)"', body.group(1))) == set(READER_FORBIDDEN)


def test_snapshot_is_frozen_against_later_edits(tmp_path: Path) -> None:
    store = PromptStore(tmp_path / "p.json")
    snapshot = store.snapshot()

    store.set("writer", "改过的")

    assert snapshot.text("writer") == DEFAULTS["writer"]


def test_build_deps_reads_active_store_and_can_be_pinned(monkeypatch, tmp_path: Path) -> None:
    """界面/CLI 走覆盖层；评测显式传 defaults，量具不跟着被测对象变（D10-9）。"""
    from app import cli
    from tests.helpers import make_settings

    monkeypatch.setenv("XHS_PROMPT_STORE", str(tmp_path / "prompts.json"))
    PromptStore(tmp_path / "prompts.json").set("writer", "覆盖版")
    monkeypatch.setattr(cli.Settings, "load", classmethod(lambda cls: make_settings()))

    assert cli.build_deps().prompts.text("writer") == "覆盖版"
    assert cli.build_deps(prompts=PromptSet.defaults()).prompts.text("writer") == DEFAULTS["writer"]


def test_default_path_is_anchored_to_backend(monkeypatch) -> None:
    """从仓库根目录启动服务时，覆盖层不能悄悄写到另一个 data/ 里去。"""
    monkeypatch.delenv("XHS_PROMPT_STORE", raising=False)

    expected = Path(__file__).resolve().parents[1] / "data" / "prompts.json"

    assert PromptStore.default_path() == expected
