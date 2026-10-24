"""角色上下文白名单与三条信息隔离（Task 4，对应 §6）。"""

from __future__ import annotations

import json

from app.context import (
    build_planner_context,
    build_reader_context,
    build_writer_context,
    split_sentences,
)
from app.schemas import (
    Angle,
    Draft,
    Objection,
    PersonaInput,
    ProfileCard,
    RunInput,
    Verdict,
)

SECRET_MATERIAL = "中介带我看房时偷偷说这栋楼隔音差"


def make_state(**overrides):
    persona = PersonaInput(
        nickname="沪漂第三年的市场岗打工人",
        age_range="25-30",
        city="上海",
        occupation="市场营销",
        goal="涨粉",
        tone=["自嘲", "直给"],
        real_material=[SECRET_MATERIAL, "被二房东坑过一个月押金"],
        taboo=["不提公司名"],
    )
    card = ProfileCard(**persona.model_dump(), anchors=[SECRET_MATERIAL], can_say=["我跟你说"], cannot_say=["公司名"])
    state = {
        "run_id": "run-1",
        "input": RunInput(persona=persona, topic="租房第一年我终于搞清楚的事"),
        "profile": card,
        "angle": Angle(
            hook="把租房踩坑写成清单",
            target_emotion="实用",
            title_candidates=["中介不会告诉你的三件事", "租房三年才懂的事"],
            chosen=True,
            why_not_others="另外两个太抒情，给不了可执行信息",
        ),
        "angle_history": [],
        "round": 2,
        "draft": Draft(
            title="租房第三年，我才知道中介不会告诉你的三件事",
            cover_text="中介没说的三件事",
            body="第一年我什么都不懂。签约那天中介笑得很热情！后来我才知道隔音是硬伤？",
            tags=["租房", "沪漂", "避坑"],
        ),
        "draft_history": [],
        "verdicts": [Verdict(click=False, read_through=0.2, save=False, comment_intent=False)],
        "feedback_history": [
            [
                Objection(
                    sentence_index=2,
                    quote="签约那天中介笑得很热情",
                    problem_type="no_evidence",
                    suggestion="补一个具体细节，比如他说了什么",
                )
            ]
        ],
        "writer_responses": [],
        "best_round": None,
        "status": "running",
        "usage": None,
    }
    state.update(overrides)
    return state


def test_reader_context_hides_real_material_angle_and_history():
    ctx = build_reader_context(make_state())
    dumped = json.dumps(ctx, ensure_ascii=False)

    assert SECRET_MATERIAL not in dumped
    assert "被二房东坑过" not in dumped
    assert "租房踩坑写成清单" not in dumped  # 策划意图
    hidden = {"real_material", "angle", "verdicts", "feedback_history", "previous_objections"}
    assert hidden.isdisjoint(ctx)


def test_planner_context_has_no_draft():
    ctx = build_planner_context(make_state())

    assert "body" not in json.dumps(ctx, ensure_ascii=False)
    assert "租房踩坑写成清单" not in json.dumps(ctx, ensure_ascii=False)


def test_writer_context_has_no_rule_library():
    ctx = build_writer_context(make_state())

    assert set(ctx) == {
        "round",
        "topic",
        "persona",
        "angle",
        "previous_objections",
        "previous_draft",
        "gate_findings",
    }
    assert ctx["gate_findings"] == []


def test_split_sentences_of_empty_body_is_empty():
    assert split_sentences("") == []


def test_reader_context_tolerates_single_sentence_body():
    state = make_state()
    state["draft"] = Draft(title="t", body="就一句话。", tags=[])

    assert build_reader_context(state)["note"]["sentences"] == [{"index": 1, "text": "就一句话。"}]


def test_context_does_not_require_optional_state_keys():
    """刚开跑时没有 profile / angle / draft，builder 不能 KeyError。"""
    minimal = {
        "input": RunInput(
            persona=PersonaInput(
                nickname="x",
                age_range="25-30",
                city="杭州",
                occupation="学生",
                goal="表达",
                tone=["直给"],
                real_material=["宿舍断电那晚"],
            ),
            topic="x",
        ),
        "round": 1,
    }

    ctx = build_reader_context(minimal)

    assert ctx["note"]["body"] == ""
    assert ctx["reader_profile"]["city"] == "杭州"
    assert ctx["reader_profile"].get("scene") is None  # 不编造刷手机场景
