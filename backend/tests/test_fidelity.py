"""事实保真校验（Task 3，§8 的四条硬约束）。"""

from __future__ import annotations

from app.humanize.fidelity import check
from app.schemas import ProfileCard

ANCHOR = "被二房东坑过一个月押金"


def card() -> ProfileCard:
    return ProfileCard(
        nickname="沪漂打工人",
        age_range="25-30",
        city="上海",
        occupation="市场营销",
        goal="涨粉",
        tone=["自嘲"],
        real_material=[ANCHOR, "中介说这栋楼隔音差"],
        taboo=[],
        anchors=[ANCHOR],
    )


def test_ok_when_numbers_and_anchors_survive():
    before = f"月租5200元，{ANCHOR}，签合同那天中介笑得很热情。"
    after = f"月租5200元，{ANCHOR}，签合同那天中介笑得很客气。"

    assert check(before, after, card()).ok


def test_rejected_when_number_changes():
    before = f"月租5200元，{ANCHOR}。"
    after = f"月租五千多元，{ANCHOR}。"

    result = check(before, after, card())

    assert not result.ok
    assert "数字" in result.reason


def test_rejected_when_anchor_dropped():
    before = f"{ANCHOR}，月租5200元，签合同那天中介笑得很热情。"
    after = "押金这事我算是认了，月租5200元，签合同那天中介笑得很客气。"

    result = check(before, after, card())

    assert not result.ok
    assert "素材" in result.reason


def test_rejected_when_too_short():
    before = (ANCHOR + "，那天很狼狈。") * 4
    after = ANCHOR + "。"

    result = check(before, after, card())

    assert not result.ok
    assert "长度" in result.reason


def test_empty_before_is_ok():
    assert check("", "任意", card()).ok


def test_rejected_when_proper_noun_changes():
    before = "我在中山公园附近租房，月租5200元，被二房东坑过一个月押金。"
    after = "我在人民广场附近租房，月租5200元，被二房东坑过一个月押金。"

    result = check(before, after, card())

    assert not result.ok
    assert "专名" in result.reason

def test_anchor_absent_from_before_is_not_required():
    """评审 I8：主笔只用 2 条素材，剩下 8 条不该逼着改写结果里出现。"""
    profile = card().model_copy(update={"anchors": [ANCHOR, "从没写进正文的素材"]})
    before = f"月租5200元，{ANCHOR}，签合同那天中介笑得很热情。"
    after = f"月租5200元，{ANCHOR}，签合同那天中介笑得很客气。"

    assert check(before, after, profile).ok
