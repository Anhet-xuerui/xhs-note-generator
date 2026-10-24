"""评测统计（Task 1）：三个公式各十行，手写以便测试，不引 scipy。"""

from __future__ import annotations

import pytest

from app.evaluation.stats import cohens_kappa, kendall_tau_b, ordering_accuracy, spearman_rho


def test_kendall_perfect_agreement():
    assert kendall_tau_b([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_kendall_perfect_reversal():
    assert kendall_tau_b([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_kendall_with_ties_is_between_minus_one_and_one():
    tau = kendall_tau_b([1, 2, 2, 3], [1, 2, 3, 4])

    assert -1.0 < tau < 1.0


def test_spearman_identical_is_one():
    assert spearman_rho([5, 3, 9, 1], [5, 3, 9, 1]) == pytest.approx(1.0)


def test_spearman_reversed_is_minus_one():
    assert spearman_rho([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)


def test_cohens_kappa_hand_computed():
    # po = 3/4, pe = 0.5 → κ = 0.5
    assert cohens_kappa([True, True, False, False], [True, True, False, True]) == pytest.approx(0.5)


def test_cohens_kappa_undefined_when_one_rater_is_constant():
    # 两家都全判 True → pe = 1，κ 无定义，返回 None 而不是除零
    assert cohens_kappa([True, True], [True, True]) is None


def test_ordering_accuracy_counts_strict_order():
    groups = [(3.0, 2.0, 1.0), (1.0, 3.0, 2.0), (5.0, 4.0, 4.0)]

    # 只有第一组是严格递减；第三组 mid 与 bad 并列不算对
    assert ordering_accuracy(groups) == pytest.approx(1 / 3)


def test_ordering_accuracy_empty_is_zero():
    assert ordering_accuracy([]) == 0.0
