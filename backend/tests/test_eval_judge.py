"""独立评审器（Task 2）：任何一篇稿子，都能被指定 provider 当成读者打分。"""

from __future__ import annotations

from app.evaluation.judge import judge_draft, reader_prompt_sha256
from app.schemas import Draft, Objection, PersonaInput, Verdict
from tests.helpers import deps_with

BODY = "第一年租房我什么都不懂。签约那天中介笑得很热情。后来才知道隔音是硬伤。"


def persona() -> PersonaInput:
    return PersonaInput(
        nickname="沪漂打工人",
        age_range="25-30",
        city="上海",
        occupation="市场营销",
        goal="涨粉",
        tone=["自嘲"],
        real_material=["被二房东坑过押金"],
        taboo=[],
    )


def draft() -> Draft:
    return Draft(title="租房第三年才知道的事", body=BODY, tags=["租房"])


async def test_judges_with_the_given_provider():
    deps = deps_with(Verdict(click=True, click_reason="标题具体", read_through=0.9, save=True, comment_intent=False))

    judgement = await judge_draft(draft(), persona(), deps, role_provider="judge_b")

    assert judgement.verdict.click is True
    assert deps.llm.roles == ["judge_b"]
    assert judgement.usage.calls == 1


async def test_drops_objections_whose_quote_is_missing():
    verdict = Verdict(
        click=False,
        click_reason="太像广告",
        read_through=0.2,
        save=False,
        comment_intent=False,
        objections=[
            Objection(sentence_index=1, quote="正文里没有这句", problem_type="ai_smell", suggestion="删"),
            Objection(sentence_index=1, quote="签约那天中介笑得很热情", problem_type="no_evidence", suggestion="补细节"),
        ],
    )

    judgement = await judge_draft(draft(), persona(), deps_with(verdict))

    assert [o.quote for o in judgement.verdict.objections] == ["签约那天中介笑得很热情"]


def test_prompt_fingerprint_is_stable_and_short():
    first = reader_prompt_sha256()

    assert first == reader_prompt_sha256()
    assert len(first) == 12
