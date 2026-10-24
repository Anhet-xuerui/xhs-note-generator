"""多次重复的聚合：均值 + bootstrap 95% 置信区间（§12 的可复现性要求）。"""

from __future__ import annotations

from dataclasses import dataclass

from app.evaluation.stats import bootstrap_ci


@dataclass(frozen=True)
class Summary:
    mean: float
    low: float
    high: float
    n: int

    def label(self, digits: int = 2) -> str:
        return f"{self.mean:.{digits}f} [{self.low:.{digits}f}, {self.high:.{digits}f}]"

    def pct(self) -> str:
        return f"{self.mean:.0%} [{self.low:.0%}, {self.high:.0%}]"


def summarize(values: list[float], *, iterations: int = 2000) -> Summary:
    low, high = bootstrap_ci(values, iterations=iterations)
    return Summary(mean=sum(values) / len(values), low=low, high=high, n=len(values))
