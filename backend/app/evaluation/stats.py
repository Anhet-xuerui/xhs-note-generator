"""评测统计：Kendall τ-b、Spearman ρ、Cohen κ、三档排序正确率。

手写而不是引 scipy：每个都是十行以内的定义式，能单测、无重依赖，
而且报告里能直接指着公式说清「这个数是怎么来的」。
"""

from __future__ import annotations

from collections.abc import Sequence


def _pairs(n: int) -> list[tuple[int, int]]:
    return [(i, j) for i in range(n) for j in range(i + 1, n)]


def kendall_tau_b(x: Sequence[float], y: Sequence[float]) -> float:
    """Kendall τ-b：并列按 tau-b 修正，分母是两边「非并列对」的几何均值。"""
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("kendall_tau_b 需要等长且至少 2 个样本")

    concordant = discordant = ties_x = ties_y = 0
    for i, j in _pairs(len(x)):
        dx = (x[i] > x[j]) - (x[i] < x[j])
        dy = (y[i] > y[j]) - (y[i] < y[j])
        if dx == 0 and dy == 0:
            continue
        if dx == 0:
            ties_x += 1
        elif dy == 0:
            ties_y += 1
        elif dx == dy:
            concordant += 1
        else:
            discordant += 1

    n0 = len(_pairs(len(x)))
    denominator = (n0 - ties_x) * (n0 - ties_y)
    if denominator <= 0:
        return 0.0
    return (concordant - discordant) / (denominator**0.5)


def _ranks(values: Sequence[float]) -> list[float]:
    """平均秩（并列取位置均值）。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        average = (position + end) / 2 + 1
        for k in range(position, end + 1):
            ranks[order[k]] = average
        position = end + 1
    return ranks


def spearman_rho(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("spearman_rho 需要等长且至少 2 个样本")
    rx, ry = _ranks(x), _ranks(y)
    n = len(rx)
    mean_x, mean_y = sum(rx) / n, sum(ry) / n
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry, strict=True))
    var_x = sum((a - mean_x) ** 2 for a in rx)
    var_y = sum((b - mean_y) ** 2 for b in ry)
    if var_x == 0 or var_y == 0:
        return 0.0
    return cov / (var_x * var_y) ** 0.5


def cohens_kappa(a: Sequence[bool], b: Sequence[bool]) -> float | None:
    """二值一致性。任一方全判同一类时 pe=1，κ 无定义——返回 None，别除零。"""
    if len(a) != len(b) or not a:
        raise ValueError("cohens_kappa 需要等长且非空")
    n = len(a)
    observed = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    p_a_true = sum(1 for x in a if x) / n
    p_b_true = sum(1 for y in b if y) / n
    expected = p_a_true * p_b_true + (1 - p_a_true) * (1 - p_b_true)
    if expected >= 1.0:
        return None
    return (observed - expected) / (1 - expected)


def ordering_accuracy(groups: Sequence[tuple[float, float, float]]) -> float:
    """每组 (good, mid, bad) 是否严格递减；并列不算对（并列时 τ 会自己体现）。"""
    if not groups:
        return 0.0
    correct = sum(1 for good, mid, bad in groups if good > mid > bad)
    return correct / len(groups)


def bootstrap_ci(
    values: Sequence[float],
    *,
    iterations: int = 2000,
    seed: int = 42,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """均值的 bootstrap 百分位置信区间。样本量小时它比正态近似诚实得多。"""
    import random

    if not values:
        raise ValueError("bootstrap_ci 需要至少一个样本")
    data = list(values)
    if len(set(data)) == 1:
        return data[0], data[0]

    rng = random.Random(seed)
    means = []
    n = len(data)
    for _ in range(iterations):
        sample = [data[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lower = means[int((alpha / 2) * iterations)]
    upper = means[int((1 - alpha / 2) * iterations) - 1]
    return lower, upper
