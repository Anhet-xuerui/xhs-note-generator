"""三个实验的 runner（§12）：E1 判别力、E2 双厂商一致性、E3 消融。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from app.evaluation.corpus import DEFAULT_PERSONA, Corpus, _state
from app.evaluation.judge import Judgement, judge_draft, reader_prompt_sha256
from app.evaluation.stats import cohens_kappa, kendall_tau_b, ordering_accuracy, spearman_rho
from app.graph.decisions import ScoreWeights, passed, score
from app.graph.loop import run_loop
from app.humanize.smell import detect
from app.llm.client import Deps
from app.schemas import Draft, PersonaInput, Usage

BARE_SYSTEM = """你是小红书写手。按给定的主题和画像写一篇笔记，输出 JSON：
{"title": "...", "body": "...", "tags": ["..."]}
没有额外要求，正常发挥即可。"""


@dataclass(frozen=True)
class E1Result:
    n: int
    ordering_accuracy: float
    kendall_tau: float
    by_weights: dict[float, float]
    sensitive: bool
    prompt_sha: str
    usage: Usage


@dataclass(frozen=True)
class E1PairwiseResult:
    comparisons: int
    accuracy: float
    tie_rate: float
    usage: Usage


@dataclass(frozen=True)
class E2Result:
    n: int
    kappa_click: float | None
    kappa_save: float | None
    spearman_rho: float
    prompt_sha: str
    usage: Usage


@dataclass(frozen=True)
class E3PairResult:
    """A/B/C 三组稿子两两比较的胜率（§12 E3 的可用版本）。

    通过率建立在绝对判定卡上，而 E1 已证明那张卡只有 28% 的排序能力；
    两两比较不要求判定器维持一把尺子，只要求一次局部判断。
    """

    n: int
    win_a_over_b: float
    win_b_over_c: float
    win_a_over_c: float
    tie_rate: float
    tokens: dict[str, int]
    cost_cny: dict[str, float]
    usage: Usage


@dataclass(frozen=True)
class E3Row:
    mode: str
    n: int
    pass_rate: float
    mean_score: float
    tokens: int
    cost_cny: float
    elapsed_s: float
    smell_before: float | None = None
    smell_after: float | None = None
    note: str = ""


def _sum_usage(usages: list[Usage]) -> Usage:
    total = Usage()
    for usage in usages:
        total = total.merge(usage)
    return total


async def _judge_three(item, deps) -> tuple[Judgement, Judgement, Judgement]:
    return (
        await judge_draft(item.good, item.persona, deps),
        await judge_draft(item.mid, item.persona, deps),
        await judge_draft(item.bad, item.persona, deps),
    )


async def run_e1(
    corpus: Corpus,
    judge_deps: Deps,
    *,
    weights_variants: tuple[float, ...] = (1.0, 1.3, 0.7),
) -> E1Result:
    rows: list[tuple[Judgement, Judgement, Judgement]] = []
    for item in corpus.items:
        rows.append(await _judge_three(item, judge_deps))

    usages = [j.usage for row in rows for j in row]

    def accuracy(weights: ScoreWeights) -> float:
        groups = [
            (
                score(g.verdict, weights),
                score(m.verdict, weights),
                score(b.verdict, weights),
            )
            for g, m, b in rows
        ]
        return ordering_accuracy(groups)

    by_weights = {variant: accuracy(ScoreWeights().scaled(variant)) for variant in weights_variants}
    base = by_weights.get(1.0, accuracy(ScoreWeights()))

    expected: list[float] = []
    actual: list[float] = []
    for g, m, b in rows:
        expected.extend([3.0, 2.0, 1.0])
        actual.extend([score(g.verdict), score(m.verdict), score(b.verdict)])
    tau = kendall_tau_b(expected, actual) if len(actual) >= 2 else 0.0

    return E1Result(
        n=len(rows),
        ordering_accuracy=base,
        kendall_tau=tau,
        by_weights=by_weights,
        sensitive=len({round(value, 6) for value in by_weights.values()}) > 1,
        prompt_sha=reader_prompt_sha256(),
        usage=_sum_usage(usages),
    )


async def run_e1_pairwise(corpus: Corpus, judge_deps: Deps) -> E1PairwiseResult:
    """E1 修订版：三对比较（good>mid、mid>bad、good>bad），每对问两次防位置偏好。"""
    from app.evaluation.pairwise import compare_pair

    total = correct = ties = 0
    usages: list[Usage] = []

    for item in corpus.items:
        for first, second in (
            (item.good, item.mid),
            (item.mid, item.bad),
            (item.good, item.bad),
        ):
            comparison = await compare_pair(first, second, item.persona, judge_deps)
            usages.append(comparison.usage)
            total += 1
            if comparison.winner == "tie":
                ties += 1
            elif comparison.winner == "a":
                correct += 1

    decided = total - ties
    return E1PairwiseResult(
        comparisons=total,
        accuracy=(correct / decided) if decided else 0.0,
        tie_rate=(ties / total) if total else 0.0,
        usage=_sum_usage(usages),
    )


async def run_e2(corpus: Corpus, deps_a: Deps, deps_b: Deps) -> E2Result:
    click_a, click_b, save_a, save_b = [], [], [], []
    score_a, score_b = [], []
    usages: list[Usage] = []

    for item in corpus.items:
        for draft in (item.good, item.mid, item.bad):
            ja = await judge_draft(draft, item.persona, deps_a)
            jb = await judge_draft(draft, item.persona, deps_b)
            click_a.append(ja.verdict.click)
            click_b.append(jb.verdict.click)
            save_a.append(ja.verdict.save)
            save_b.append(jb.verdict.save)
            score_a.append(score(ja.verdict))
            score_b.append(score(jb.verdict))
            usages.extend([ja.usage, jb.usage])

    return E2Result(
        n=len(score_a),
        kappa_click=cohens_kappa(click_a, click_b) if click_a else None,
        kappa_save=cohens_kappa(save_a, save_b) if save_a else None,
        spearman_rho=spearman_rho(score_a, score_b) if len(score_a) >= 2 else 0.0,
        prompt_sha=reader_prompt_sha256(),
        usage=_sum_usage(usages),
    )


async def run_e3(
    topics: list[str],
    deps: Deps,
    judge_deps: Deps,
    *,
    mode: str,
    personas: list[PersonaInput] | None = None,
) -> E3Row:
    """A 裸模型 / B 完整链路 / C 完整链路但读者与主笔同厂商（由调用方传入同厂商 deps）。"""
    roster = personas or [DEFAULT_PERSONA]
    usages: list[Usage] = []
    judgements: list[Judgement] = []
    smells: list[float] = []
    started = time.perf_counter()

    for index, topic in enumerate(topics):
        persona = roster[index % len(roster)]
        draft: Draft | None = None

        if mode == "A":
            result = await deps.llm.structured(
                role="writer",
                system=BARE_SYSTEM,
                user=json.dumps({"topic": topic, "persona": persona.model_dump()}, ensure_ascii=False),
                schema=Draft,
            )
            draft = result.value
            usages.append(result.usage)
        else:
            state = await run_loop(_state(persona, topic), deps)
            draft = state.get("draft")
            if draft is None:
                continue
            if state.get("usage"):
                usages.append(state["usage"])

        judged = await judge_draft(draft, persona, judge_deps)
        judgements.append(judged)
        usages.append(judged.usage)
        smells.append(float(detect(draft.body).score))

    n = len(judgements)
    total = _sum_usage(usages)
    return E3Row(
        mode=mode,
        n=n,
        pass_rate=(sum(1 for j in judgements if passed(j.verdict)) / n) if n else 0.0,
        mean_score=(sum(score(j.verdict) for j in judgements) / n) if n else 0.0,
        tokens=total.input_tokens + total.output_tokens,
        cost_cny=round(total.cost_cny, 4),
        elapsed_s=round(time.perf_counter() - started, 1),
        smell_before=(sum(smells) / n) if n else None,
        smell_after=None,
    )


async def _draft_for(
    mode: str,
    topic: str,
    persona: PersonaInput,
    deps: Deps,
    same_vendor_deps: Deps,
) -> tuple[Draft | None, Usage]:
    if mode == "A":
        result = await deps.llm.structured(
            role="writer",
            system=BARE_SYSTEM,
            user=json.dumps({"topic": topic, "persona": persona.model_dump()}, ensure_ascii=False),
            schema=Draft,
        )
        return result.value, result.usage
    state = await run_loop(_state(persona, topic), same_vendor_deps if mode == "C" else deps)
    return state.get("draft"), state.get("usage") or Usage()


async def run_e3_pairwise(
    topics: list[str],
    deps: Deps,
    same_vendor_deps: Deps,
    judge_deps: Deps,
    *,
    personas: list[PersonaInput] | None = None,
) -> E3PairResult:
    """同一批主题分别用 A（裸模型）/ B（完整链路）/ C（同厂商读者）成稿，再两两比较。"""
    from app.evaluation.pairwise import compare_pair

    roster = personas or [DEFAULT_PERSONA]
    tokens = {"A": 0, "B": 0, "C": 0}
    cost = {"A": 0.0, "B": 0.0, "C": 0.0}
    wins = {"ab": 0, "bc": 0, "ac": 0}
    decided = {"ab": 0, "bc": 0, "ac": 0}
    ties = total = 0
    usages: list[Usage] = []

    for index, topic in enumerate(topics):
        persona = roster[index % len(roster)]
        drafts: dict[str, Draft | None] = {}
        for mode in ("A", "B", "C"):
            draft, usage = await _draft_for(mode, topic, persona, deps, same_vendor_deps)
            drafts[mode] = draft
            tokens[mode] += usage.input_tokens + usage.output_tokens
            cost[mode] += usage.cost_cny
            usages.append(usage)

        for key, left, right in (("ab", "A", "B"), ("bc", "B", "C"), ("ac", "A", "C")):
            left_draft, right_draft = drafts[left], drafts[right]
            if left_draft is None or right_draft is None:
                continue
            comparison = await compare_pair(left_draft, right_draft, persona, judge_deps)
            usages.append(comparison.usage)
            total += 1
            if comparison.winner == "tie":
                ties += 1
                continue
            decided[key] += 1
            if comparison.winner == "a":
                wins[key] += 1

    def rate(key: str) -> float:
        return wins[key] / decided[key] if decided[key] else 0.0

    return E3PairResult(
        n=len(topics),
        win_a_over_b=rate("ab"),
        win_b_over_c=rate("bc"),
        win_a_over_c=rate("ac"),
        tie_rate=(ties / total) if total else 0.0,
        tokens=tokens,
        cost_cny={k: round(v, 4) for k, v in cost.items()},
        usage=_sum_usage(usages),
    )
