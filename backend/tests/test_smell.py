"""AI 味检测器（Task 2）：六类规则，全程序化，不依赖模型判断（§8）。"""

from __future__ import annotations

from app.humanize.smell import ABSTRACT_NOUNS, detect


def test_abstract_nouns_are_flagged_with_spans():
    text = "这件事让我成长了很多，也治愈了我。"

    report = detect(text)
    hit = next(h for h in report.hits if h.category == "abstract_noun")

    assert "成长" in hit.examples and "治愈" in hit.examples
    assert hit.spans[0][0] == len("这件事让我")


def test_ai_patterns_match_not_x_but_y():
    report = detect("这不是租房，而是成年人的第一课。这不仅是一次搬家，更是告别。")

    assert any(h.category == "ai_pattern" for h in report.hits)


def test_uniform_paragraphs_flagged():
    report = detect("第一段长度差不多。\n\n第二段长度也差不多。\n\n第三段仍然差不多。")

    assert any(h.category == "uniform_paragraph" for h in report.hits)


def test_concrete_text_scores_low():
    text = "2023年3月，我在上海中山公园附近租了个38平的一居室，月租5200。签合同那天中介说：“这楼隔音差。”"

    report = detect(text)

    assert report.score <= 20
    assert not any(h.category == "no_anchor" for h in report.hits)


def test_empty_text_scores_zero_and_does_not_crash():
    report = detect("")

    assert report.score == 0
    assert report.hits == []


def test_score_is_capped_at_hundred():
    text = "".join(ABSTRACT_NOUNS) + "\n\n" + "这不是A而是B。愿你被治愈。"

    assert detect(text).score <= 100
