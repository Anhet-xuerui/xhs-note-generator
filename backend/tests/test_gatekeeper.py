"""规则库与守门人（Task 5，§9：正则先筛，模型只判误报 + 给改写建议）。"""

from __future__ import annotations

import pytest

from app.agents.gatekeeper import GateJudgement, run_gatekeeper
from app.llm.client import NodeCallFailed
from app.rules.engine import load_rules, match, match_structure
from app.schemas import GateFinding, HumanizedDraft
from tests.helpers import deps_with


def draft_with(body: str, tags: list[str] | None = None) -> HumanizedDraft:
    return HumanizedDraft(
        title="租房第三年才知道的事",
        cover_text="押金差点没要回来",
        body=body,
        tags=tags if tags is not None else ["租房", "沪漂", "避坑"],
        smell_before=62,
        smell_after=28,
        changes=[],
        fidelity="passed",
    )


def test_rule_library_has_three_blocking_categories():
    ids = {rule.id for rule in load_rules()}

    assert {"absolute-claim", "medical-efficacy", "diversion"} <= ids


def test_matches_absolute_words_with_spans():
    findings = match("这是最好的选择，100%有效", load_rules())

    assert {f.rule_id for f in findings} == {"absolute-claim"}
    assert findings[0].matched in {"最", "100%"}
    assert findings[0].span[0] >= 0


def test_structure_rules_warn_on_short_body_and_few_tags():
    findings = match_structure("太短了", ["只有一个标签"])

    assert {f.rule_id for f in findings} == {"body-length", "tag-count"}
    assert all(f.severity == "warning" for f in findings)


async def test_model_marks_false_positive_for_last_and_first():
    body = "最后我还是搬走了，第一次租房就这样结束，后来想想也没什么。"
    judgement = GateJudgement(
        findings=[
            GateFinding(rule_id="absolute-claim", severity="blocking", matched="最", span=(0, 1), false_positive=True, hint="「最后」不是极限词"),
            GateFinding(rule_id="absolute-claim", severity="blocking", matched="第一", span=(8, 10), false_positive=True, hint="「第一次」不是极限词"),
        ]
    )

    result = await run_gatekeeper({}, deps_with(judgement), draft_with(body))

    assert result.passed


async def test_blocking_hit_without_false_positive_fails():
    body = "这个方法保证一个月祛痘，亲测有效。"
    judgement = GateJudgement(
        findings=[
            GateFinding(rule_id="absolute-claim", severity="blocking", matched="保证", span=(4, 6), false_positive=False, hint="改成主观表达"),
            GateFinding(rule_id="medical-efficacy", severity="blocking", matched="祛痘", span=(9, 11), false_positive=False, hint="不承诺效果"),
        ]
    )

    result = await run_gatekeeper({}, deps_with(judgement), draft_with(body))

    assert not result.passed
    # 对账后 findings 是「全部正则命中 + 模型的误报判定」，不是模型原样返回的两条
    assert {f.rule_id for f in result.findings} >= {"absolute-claim", "medical-efficacy"}
    assert all(not f.false_positive for f in result.findings if f.severity == "blocking")


async def test_model_failure_keeps_regex_findings_and_fails():
    result = await run_gatekeeper({}, deps_with(NodeCallFailed("gatekeeper", 2, RuntimeError("boom"))), draft_with("保证有效"))

    assert not result.passed
    assert result.findings


async def test_no_hits_skips_model_call():
    deps = deps_with()

    # 正文要够长，否则 body-length 结构规则会命中，就不是「无命中」场景了
    clean = "那年冬天我搬了三次家，每次都自己扛箱子上下楼。" * 20
    result = await run_gatekeeper({}, deps, draft_with(clean))

    assert result.passed
    assert deps.llm.roles == []


@pytest.mark.parametrize("word", ["加微信", "私信我", "评论区扣1"])
def test_diversion_is_blocking(word):
    findings = match(f"想要清单的{word}", load_rules())

    assert any(f.rule_id == "diversion" and f.severity == "blocking" for f in findings)

async def test_missing_blocking_finding_is_not_dropped():
    """C4 回归：模型漏回一条命中 ≠ 放行；只允许改判 false_positive。"""
    body = "这个方法保证一个月见效，亲测有效。" + "那年冬天我搬了三次家。" * 20
    partial = GateJudgement(
        findings=[
            GateFinding(rule_id="medical-efficacy", severity="blocking", matched="见效", span=(14, 16), false_positive=False, hint="改"),
        ]
    )

    result = await run_gatekeeper({}, deps_with(partial), draft_with(body))

    assert not result.passed
    assert any(f.rule_id == "absolute-claim" and not f.false_positive for f in result.findings)


async def test_invented_finding_is_ignored():
    body = "那年冬天我搬了三次家。" * 20
    invented = GateJudgement(
        findings=[GateFinding(rule_id="absolute-claim", severity="blocking", matched="最", span=(0, 1), false_positive=False, hint="编的")]
    )

    result = await run_gatekeeper({}, deps_with(invented), draft_with(body))

    assert result.passed
