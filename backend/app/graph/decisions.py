"""判定与控制逻辑（§7）：通过条件、评分、两级卡死、角度重开、轮次上限。

全部是纯函数——这是「退出条件不交给模型」的落点：模型只说第几句划走、想不想点，
算不算过、要不要继续、最后交哪一轮，都由这里决定。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from app.schemas import Objection, Verdict

# 轮次硬上限：不对外开放调高（§7/§17）。
MAX_ROUNDS = 3
PASS_READ_THROUGH = 0.6
BLOCKING_PROBLEM_TYPES = frozenset({"ai_smell", "no_evidence"})
MAX_ANGLE_HISTORY_FOR_REOPEN = 2
ANGLE_HOOK_READ_THROUGH = 0.3
ANGLE_HOOK_SENTENCES = 3

Action = Literal["continue", "new_angle", "stop"]
Status = Literal["running", "passed", "exhausted"]
StopReason = Literal["passed", "stuck_repeat", "stuck_no_gain", "max_rounds"]


@dataclass(frozen=True)
class ScoreWeights:
    """评分权重（§7）。权重是拍的初始值，D9 的 E1 会做 ±30% 敏感性检查，所以它是可替换的。"""

    click: float = 3.0
    save: float = 4.0
    comment_intent: float = 2.0
    read_through: float = 2.0
    blocking: float = -0.5

    def scaled(self, factor: float) -> "ScoreWeights":
        return replace(
            self,
            click=self.click * factor,
            save=self.save * factor,
            comment_intent=self.comment_intent * factor,
            read_through=self.read_through * factor,
            blocking=self.blocking * factor,
        )


DEFAULT_WEIGHTS = ScoreWeights()


@dataclass(frozen=True)
class VerdictEvaluation:
    passed: bool
    score: float
    read_through: float
    failed_checks: list[dict]


@dataclass(frozen=True)
class LoopDecision:
    action: Action
    status: Status
    stop_reason: StopReason | None
    best_round: int | None
    evaluation: VerdictEvaluation


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


def score(verdict: Verdict, weights: ScoreWeights = DEFAULT_WEIGHTS) -> float:
    blocking = len(blocking_objections(verdict))
    return round(
        weights.click * int(verdict.click)
        + weights.save * int(verdict.save)
        + weights.comment_intent * int(verdict.comment_intent)
        + weights.read_through * verdict.read_through
        + weights.blocking * blocking,
        4,
    )


def evaluate(verdict: Verdict, weights: ScoreWeights = DEFAULT_WEIGHTS) -> VerdictEvaluation:
    """给人看的结论：过没过、多少分、卡在哪几项。"""
    checks: list[dict] = []
    if not verdict.click:
        checks.append({"code": "click", "label": "不会点开", "detail": verdict.click_reason or "标题没抓住"})
    if not verdict.save:
        checks.append({"code": "save", "label": "不会收藏", "detail": "看完不会想存下来"})
    if verdict.read_through < PASS_READ_THROUGH:
        detail = f"只读完 {verdict.read_through:.0%}（通过线 {PASS_READ_THROUGH:.0%}）"
        if verdict.drop_at_sentence:
            detail = f"第 {verdict.drop_at_sentence} 句划走，" + detail
        checks.append({"code": "read_through", "label": "没读完", "detail": detail})
    for objection in blocking_objections(verdict):
        checks.append(
            {
                "code": "blocking",
                "label": f"第 {objection.sentence_index} 句硬伤",
                "detail": f"{objection.problem_type}：「{objection.quote}」",
            }
        )
    return VerdictEvaluation(
        passed=passed(verdict),
        score=score(verdict, weights),
        read_through=verdict.read_through,
        failed_checks=checks,
    )


def verdicts_identical(a: Verdict, b: Verdict) -> bool:
    """一级卡死：判定卡与异议完全相同（objections 比内容，不比顺序）。"""
    if a.model_dump(exclude={"objections"}) != b.model_dump(exclude={"objections"}):
        return False
    key = lambda o: (o.sentence_index, o.quote, o.problem_type, o.suggestion)  # noqa: E731
    return sorted(a.objections, key=key) == sorted(b.objections, key=key)


def detect_stuck(verdicts: list[Verdict], weights: ScoreWeights = DEFAULT_WEIGHTS) -> StopReason | None:
    """两级卡死检测。一级在实践中几乎不成立，二级才是实际生效的那个（§7）。"""
    if len(verdicts) >= 2 and verdicts_identical(verdicts[-1], verdicts[-2]):
        return "stuck_repeat"
    if len(verdicts) >= 3:
        scores = [score(v, weights) for v in verdicts]
        if scores[-1] - scores[-2] <= 0 and scores[-2] - scores[-3] <= 0:
            return "stuck_no_gain"
    return None


def needs_new_angle(round_no: int, verdict: Verdict, angle_history: list) -> bool:
    """角度错了的信号由代码判定：读者看不到角度，也不会说「你角度错了」（§7）。"""
    if round_no < 2 or len(angle_history) >= MAX_ANGLE_HISTORY_FOR_REOPEN:
        return False
    if verdict.click or verdict.read_through >= ANGLE_HOOK_READ_THROUGH:
        return False
    return any(
        o.problem_type in {"hook_weak", "wrong_tone"} and o.sentence_index <= ANGLE_HOOK_SENTENCES
        for o in verdict.objections
    )


def round_cap_reached(round_no: int) -> bool:
    return round_no >= MAX_ROUNDS


def pick_best_round(verdicts: list[Verdict], weights: ScoreWeights = DEFAULT_WEIGHTS) -> int:
    """最高分那一轮（1-based）；同分取更晚一轮——它已吸收前面的意见。"""
    best_index = 0
    best_score = score(verdicts[0], weights)
    for i, verdict in enumerate(verdicts[1:], start=1):
        current = score(verdict, weights)
        if current >= best_score:
            best_index, best_score = i, current
    return best_index + 1


def decide(
    verdicts: list[Verdict],
    angle_history: list,
    weights: ScoreWeights = DEFAULT_WEIGHTS,
) -> LoopDecision:
    """判定顺序：通过 → 一级卡死 → 二级卡死 → 轮次上限 → 角度重开 → 继续。"""
    if not verdicts:
        raise ValueError("decide() 需要至少一张判定卡")
    last = verdicts[-1]
    round_no = len(verdicts)
    evaluation = evaluate(last, weights)

    if evaluation.passed:
        return LoopDecision("stop", "passed", "passed", None, evaluation)

    stuck = detect_stuck(verdicts, weights)
    if stuck is not None:
        return LoopDecision("stop", "exhausted", stuck, pick_best_round(verdicts, weights), evaluation)

    if round_cap_reached(round_no):
        return LoopDecision(
            "stop", "exhausted", "max_rounds", pick_best_round(verdicts, weights), evaluation
        )

    if needs_new_angle(round_no, last, angle_history):
        return LoopDecision("new_angle", "running", None, pick_best_round(verdicts, weights), evaluation)

    return LoopDecision("continue", "running", None, pick_best_round(verdicts, weights), evaluation)
