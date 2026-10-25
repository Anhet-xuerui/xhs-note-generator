"""D4 链路：封面 → 人味校订 → 守门人（Task 6）。"""

from __future__ import annotations

from app.agents.cover import CoverText
from app.agents.gatekeeper import GateJudgement
from app.agents.humanize import HumanizeOutput
from app.graph.loop import finish_draft, run_loop
from app.schemas import GateFinding, Verdict
from tests.helpers import deps_with, make_angles, make_card, make_state, make_writer_output

ANCHOR = "被二房东坑过一个月押金"
BODY = f"{ANCHOR}，月租5200元。那年冬天我搬了三次家，每次都自己扛箱子上下楼。" * 6
# 长度必须和主笔原文接近，否则人味校订会被保真回退、守门人根本看不到「保证」
BASE_BODY = make_writer_output().draft.body
BAD_BODY = BASE_BODY + "保证有效。"


def passing() -> Verdict:
    return Verdict(click=True, click_reason="标题具体", read_through=0.9, save=True, comment_intent=True)


def humanized(body: str) -> HumanizeOutput:
    return HumanizeOutput(title=make_writer_output().draft.title, body=body, tags=["租房", "沪漂", "避坑"], changes=[])


async def test_full_pipeline_adds_cover_smell_and_gate():
    state = make_state()
    deps = deps_with(
        make_card(), make_angles(), make_writer_output(), passing(),
        CoverText(cover_text="押金差点没要回来"),
        humanized(make_writer_output().draft.body),
        GateJudgement(findings=[]),
    )

    out = await finish_draft(await run_loop(state, deps), deps)

    assert out["humanized"] is not None
    assert out["smell"] is not None
    assert out["gate"] is not None and out["gate"].passed
    assert out["draft"].cover_text == "押金差点没要回来"
    assert out["status"] == "passed"


async def test_blocking_gate_marks_gate_blocked_and_retries_humanize_once():
    state = make_state()
    blocking = GateJudgement(
        findings=[
            GateFinding(rule_id="absolute-claim", severity="blocking", matched="保证", span=(0, 2), false_positive=False, hint="去掉承诺"),
        ]
    )
    deps = deps_with(
        make_card(), make_angles(), make_writer_output(), passing(),
        CoverText(cover_text="押金差点没要回来"),
        humanized(BAD_BODY), blocking,
        humanized(BAD_BODY), blocking,
    )

    out = await finish_draft(await run_loop(state, deps), deps)

    assert deps.llm.roles.count("humanizer") == 2
    assert out["status"] == "gate_blocked"


async def test_gate_blocked_still_reports_draft():
    state = make_state()
    blocking = GateJudgement(
        findings=[
            GateFinding(rule_id="medical-efficacy", severity="blocking", matched="见效", span=(0, 2), false_positive=False, hint="改成个人体验"),
        ]
    )
    deps = deps_with(
        make_card(), make_angles(), make_writer_output(), passing(),
        CoverText(cover_text="押金差点没要回来"),
        humanized(BAD_BODY), blocking,
        humanized(BAD_BODY), blocking,
    )

    out = await finish_draft(await run_loop(state, deps), deps)

    assert out["status"] == "gate_blocked"
    assert out["draft"].body                     # 稿子照给，标注未过合规


async def test_warning_only_gate_passes():
    state = make_state()
    warning = GateJudgement(
        findings=[GateFinding(rule_id="tag-count", severity="warning", matched="2", span=(0, 0), false_positive=False, hint="3–8 个")]
    )
    deps = deps_with(
        make_card(), make_angles(), make_writer_output(), passing(),
        CoverText(cover_text="押金差点没要回来"),
        humanized(make_writer_output().draft.body),
        warning,
    )

    out = await finish_draft(await run_loop(state, deps), deps)

    assert out["gate"].passed
    assert out["status"] == "passed"
