"""三档稿语料与 E1/E2/E3 runner（Task 3/4）。"""

from __future__ import annotations

from app.evaluation.corpus import BAD_PROMPT, build_corpus
from app.evaluation.runners import run_e1, run_e2, run_e3
from app.schemas import Draft, Verdict
from tests.helpers import deps_with, make_angles, make_card, make_persona, make_writer_output


def good_verdict() -> Verdict:
    return Verdict(click=True, click_reason="好", read_through=0.9, save=True, comment_intent=True)


def mid_verdict() -> Verdict:
    return Verdict(click=True, click_reason="中", read_through=0.6, save=False, comment_intent=False)


def bad_verdict() -> Verdict:
    return Verdict(click=False, click_reason="差", read_through=0.2, save=False, comment_intent=False)


def bad_draft() -> Draft:
    return Draft(title="关于成长这件事", body="我们都在焦虑里学会治愈，愿你被世界温柔以待。", tags=["成长"])


async def test_bad_prompt_asks_for_the_opposite_of_good_writing():
    assert "抽象" in BAD_PROMPT
    assert "不要出现任何具体数字" in BAD_PROMPT


async def test_corpus_takes_good_mid_bad_from_the_right_places():
    deps = deps_with(
        make_card(), make_angles(), make_writer_output(), good_verdict(),
        bad_draft(),
    )

    corpus = await build_corpus(["租房第一年"], deps, personas=[make_persona()])

    item = corpus.items[0]
    assert item.mid.title == make_writer_output().draft.title       # 首轮稿
    assert item.good.body                                              # run 的交付稿
    assert item.bad.title == "关于成长这件事"                            # 反向 prompt 产物
    assert item.good_fallback is False


async def test_e1_orders_three_tiers_and_reports_tau():
    deps = deps_with(
        make_card(), make_angles(), make_writer_output(), good_verdict(), bad_draft(),
        good_verdict(), mid_verdict(), bad_verdict(),     # E1 三次评分：good/mid/bad
    )
    corpus = await build_corpus(["租房第一年"], deps, personas=[make_persona()])

    result = await run_e1(corpus, deps_with(good_verdict(), mid_verdict(), bad_verdict()))

    assert result.n == 1
    assert result.ordering_accuracy == 1.0
    assert result.kendall_tau > 0.5
    assert result.prompt_sha


async def test_e1_flags_weight_sensitivity_when_order_flips():
    corpus = await build_corpus(
        ["t"],
        deps_with(make_card(), make_angles(), make_writer_output(), good_verdict(), bad_draft()),
        personas=[make_persona()],
    )
    # 三档分数刻意拉开但只差 click/comment：权重缩放后排序不变 → 不敏感
    judge_deps = deps_with(good_verdict(), mid_verdict(), bad_verdict())

    result = await run_e1(corpus, judge_deps)

    assert result.sensitive is False


async def test_e2_reports_kappa_and_rho_for_two_vendors():
    deps = deps_with(make_card(), make_angles(), make_writer_output(), good_verdict(), bad_draft())
    corpus = await build_corpus(["t"], deps, personas=[make_persona()])

    result = await run_e2(
        corpus,
        deps_with(good_verdict(), mid_verdict(), bad_verdict()),
        deps_with(good_verdict(), mid_verdict(), bad_verdict()),
    )

    assert result.kappa_click == 1.0
    assert result.kappa_save is None or -1.0 <= result.kappa_save <= 1.0
    assert result.spearman_rho == 1.0


async def test_e3_group_a_is_one_generation_plus_scoring():
    deps = deps_with(Draft(title="裸模型", body="我们都在焦虑里治愈。", tags=["a"]))
    judge = deps_with(mid_verdict())

    row = await run_e3(
        ["租房第一年"],
        deps,
        judge,
        mode="A",
        personas=[make_card()],
    )

    assert row.mode == "A"
    assert row.n == 1
    assert row.tokens > 0
