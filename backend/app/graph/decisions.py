"""判定与控制逻辑（§7）。

Task 9 只落地「通过条件」——CLI 必须输出 status，而把同一个公式复制到两处就是两套真相。
评分、两级卡死、`needs_new_angle` 在 Task 10 补齐。
"""

from __future__ import annotations

from app.schemas import Objection, Verdict

PASS_READ_THROUGH = 0.6
BLOCKING_PROBLEM_TYPES = frozenset({"ai_smell", "no_evidence"})


def blocking_objections(verdict: Verdict) -> list[Objection]:
    """硬伤：像 AI 写的、说了结论没依据。"""
    return [o for o in verdict.objections if o.problem_type in BLOCKING_PROBLEM_TYPES]


def passed(verdict: Verdict) -> bool:
    """通过条件是硬编码，不让模型自己说「可以了」（§7）。"""
    return (
        verdict.click
        and verdict.save
        and verdict.read_through >= PASS_READ_THROUGH
        and not blocking_objections(verdict)
    )
