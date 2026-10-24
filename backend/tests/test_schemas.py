"""数据契约（Task 3）：画像、角度、稿子、判定卡、用量。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import Angle, PersonaInput, Usage, Verdict


def test_real_material_bounds():
    with pytest.raises(ValidationError):
        PersonaInput(
            nickname="x",
            age_range="25-30",
            city="上海",
            occupation="市场",
            goal="涨粉",
            tone=["直给"],
            real_material=[],
        )


def test_taboo_defaults_to_empty_list():
    p = PersonaInput(
        nickname="x",
        age_range="25-30",
        city="上海",
        occupation="市场",
        goal="涨粉",
        tone=["直给"],
        real_material=["被二房东坑过押金"],
    )
    assert p.taboo == []


def test_verdict_schema_is_frozen():
    """判分卡字段冻结（§7）：改字段等于让全部评测作废。"""
    assert set(Verdict.model_fields) == {
        "click",
        "click_reason",
        "drop_at_sentence",
        "read_through",
        "save",
        "comment_intent",
        "objections",
    }


def test_usage_merge_sums_all_fields():
    a, b = Usage(10, 5, 0.1, 1, 1.0), Usage(20, 7, 0.2, 2, 2.0)

    merged = a.merge(b)

    assert (merged.input_tokens, merged.output_tokens) == (30, 12)
    assert (merged.calls, merged.elapsed_s) == (3, 3.0)
    # 浮点相加不能断言字面相等：0.1 + 0.2 != 0.3
    assert merged.cost_cny == pytest.approx(0.3)


def test_angle_requires_exactly_two_to_three_titles():
    with pytest.raises(ValidationError):
        Angle(
            hook="h",
            target_emotion="实用",
            title_candidates=["只有一个"],
            chosen=True,
            why_not_others="x",
        )
