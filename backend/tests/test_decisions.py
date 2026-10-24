"""判定与控制逻辑（Task 10）：纯函数，逐条对应 §7。"""

from __future__ import annotations

from app.graph.decisions import (
    MAX_ROUNDS,
    ScoreWeights,
    decide,
    detect_stuck,
    evaluate,
    needs_new_angle,
    passed,
    pick_best_round,
    score,
    verdicts_identical,
)
from app.schemas import Objection, Verdict


def v(click=False, save=False, read_through=0.5, comment=False, objections=None, reason="理由") -> Verdict:
    return Verdict(
        click=click,
        click_reason=reason,
        read_through=read_through,
        save=save,
        comment_intent=comment,
        objections=objections or [],
    )


def test_passed_requires_click_save_read_through_and_no_blocking():
    assert passed(v(click=True, save=True, read_through=0.9))
    assert not passed(v(click=True, save=True, read_through=0.59))
    assert not passed(
        v(
            click=True,
            save=True,
            read_through=0.9,
            objections=[Objection(sentence_index=1, quote="q", problem_type="ai_smell", suggestion="s")],
        )
    )


def test_score_matches_documented_formula():
    verdict = v(click=True, save=True, read_through=0.5, comment=True)

    assert score(verdict) == 3 + 4 + 2 + 1.0


def test_score_weights_are_scalable():
    verdict = v(click=True, save=True, read_through=1.0, comment=True)

    assert score(verdict, ScoreWeights().scaled(1.3)) > score(verdict)


def test_needs_new_angle_only_after_round_one_and_within_budget():
    hook = Objection(sentence_index=2, quote="q", problem_type="hook_weak", suggestion="s")
    bad_open = v(click=False, read_through=0.2, objections=[hook])

    assert not needs_new_angle(1, bad_open, [])          # 第一轮不换角度
    assert needs_new_angle(2, bad_open, [])
    assert not needs_new_angle(2, bad_open, ["a", "b"])  # 最多重开一次
    assert not needs_new_angle(2, v(click=True, read_through=0.2, objections=[hook]), [])


def test_identical_verdicts_trigger_stuck_repeat():
    first = v(read_through=0.4, objections=[Objection(sentence_index=1, quote="q", problem_type="unclear", suggestion="s")])
    second = first.model_copy(deep=True)

    assert verdicts_identical(first, second)
    assert detect_stuck([first, second]) == "stuck_repeat"


def test_two_flat_rounds_trigger_stuck_no_gain():
    # 分数持平但判定卡不同（理由不同）——一级卡死不成立，靠二级兜底
    flat = [v(read_through=0.4, reason="a"), v(read_through=0.4, reason="b"), v(read_through=0.4, reason="c")]

    assert detect_stuck(flat) == "stuck_no_gain"


def test_pick_best_round_prefers_higher_score_and_later_on_tie():
    verdicts = [v(click=False, read_through=0.1), v(click=True, read_through=0.8), v(click=False, read_through=0.2)]

    assert pick_best_round(verdicts) == 2
    assert pick_best_round([v(read_through=0.5), v(read_through=0.5)]) == 2


def test_decide_stops_on_max_rounds_with_best_round():
    verdicts = [v(click=True, read_through=0.4), v(click=True, read_through=0.8), v(click=False, read_through=0.2)]

    decision = decide(verdicts, [])

    assert decision.action == "stop"
    assert decision.stop_reason == "max_rounds"
    assert decision.best_round == 2
    assert len(verdicts) == MAX_ROUNDS


def test_evaluate_lists_failed_checks():
    verdict = v(click=False, save=False, read_through=0.42)

    evaluation = evaluate(verdict)

    codes = [c["code"] for c in evaluation.failed_checks]
    assert codes == ["click", "save", "read_through"]
    assert "42%" in evaluation.failed_checks[-1]["detail"]
