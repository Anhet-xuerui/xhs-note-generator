"""两两比较（E1 修订版）。"""

from __future__ import annotations

from app.evaluation.pairwise import PairChoice, compare_pair
from app.schemas import Draft, PersonaInput
from tests.helpers import deps_with


def persona() -> PersonaInput:
    return PersonaInput(
        nickname="沪漂打工人",
        age_range="25-30",
        city="上海",
        occupation="市场营销",
        goal="涨粉",
        tone=["直给"],
        real_material=["被二房东坑过押金"],
        taboo=[],
    )


def draft(title: str, body: str) -> Draft:
    return Draft(title=title, body=body, tags=["租房"])


GOOD = draft("好稿", "2023年我在上海租了个38平的房子，月租5200。")
MID = draft("中稿", "租房这件事让我学到了很多，也成长了不少。")


async def test_consistent_answer_picks_a():
    # 正序选 A（=好稿），换序后选 B（也是好稿）→ 一致，好稿胜
    deps = deps_with(PairChoice(winner="A"), PairChoice(winner="B"))

    result = await compare_pair(GOOD, MID, persona(), deps)

    assert result.winner == "a"
    assert result.consistent is True
    assert result.usage.calls == 2


async def test_picks_b_when_both_orders_point_at_b():
    deps = deps_with(PairChoice(winner="B"), PairChoice(winner="A"))

    result = await compare_pair(GOOD, MID, persona(), deps)

    assert result.winner == "b"
    assert result.consistent is True


async def test_inconsistent_answer_is_tie():
    # 两次都选「先出现的那篇」= 位置偏好，不是真实偏好 → tie
    deps = deps_with(PairChoice(winner="A"), PairChoice(winner="A"))

    result = await compare_pair(GOOD, MID, persona(), deps)

    assert result.winner == "tie"
    assert result.consistent is False


async def test_both_notes_are_in_the_prompt():
    deps = deps_with(PairChoice(winner="A"), PairChoice(winner="B"))

    await compare_pair(GOOD, MID, persona(), deps)

    prompt = deps.llm.users[0]
    assert "好稿" in prompt and "中稿" in prompt

async def test_runner_accuracy_counts_only_consistent_comparisons():
    """位置偏好导致的不一致记 tie、不进分母，但单独报出来。"""
    from app.evaluation.corpus import Corpus, CorpusItem
    from app.evaluation.runners import run_e1_pairwise

    corpus = Corpus(
        items=[
            CorpusItem(
                topic="t",
                persona=persona(),
                good=GOOD,
                mid=MID,
                bad=draft("差稿", "我们都在焦虑里治愈，愿你被温柔以待。"),
                good_fallback=False,
            )
        ]
    )
    # 3 对 × 2 次；全选先出现的那篇 → 三次比较里两次一致（A/B 顺序映射后）
    deps = deps_with(*([PairChoice(winner="A"), PairChoice(winner="B")] * 3))

    result = await run_e1_pairwise(corpus, deps)

    assert result.comparisons == 3
    assert result.accuracy == 1.0
    assert result.tie_rate == 0.0
