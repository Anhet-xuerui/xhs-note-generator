"""`node_end` 事件契约：产物、耗时、花费、降级、重试序号（D10-5）。

这一层是前端唯一的数据来源——它错了，界面说什么都是假的。
"""

from __future__ import annotations

import pytest

from app.agents.cover import CoverText
from app.agents.gatekeeper import GateJudgement
from app.agents.humanize import HumanizeOutput
from app.agents.writer import WriterOutput
from app.graph.loop import finish_draft, run_loop
from app.llm.client import NodeCallFailed
from app.prompts import ROLES
from app.schemas import Draft, GateFinding, Usage, Verdict
from tests.helpers import deps_with, make_angles, make_card, make_state

# 正文要同时满足三件事：含 blocking 违禁词（「最」）、有 AI 味（人味校订不会早退）、
# 数字与专名改写前后一致（保真校验不会整篇回退）。少一件，重试路径就走不到。
BODY = "被二房东坑过一个月押金。后来才明白，中介说这栋楼隔音差这句话是什么意思。最后我报警才要回一半。"
WRITER = WriterOutput(
    draft=Draft(title="租房第三年", body=BODY, tags=["租房", "沪漂"]), responses=[]
)
PASS = Verdict(click=True, click_reason="标题具体", read_through=0.9, save=True, comment_intent=True)
HUMANIZED = HumanizeOutput(title="租房第三年", body=BODY, tags=["租房", "沪漂", "避坑"], changes=[])
SMELL_HIT = GateFinding(
    rule_id="absolute-claim",
    severity="blocking",
    matched="最",
    span=(0, 1),
    false_positive=False,
    hint="「最后」改成「终于」",
)
FALSE_POSITIVE = SMELL_HIT.model_copy(update={"false_positive": True})


def _collect(*responses):
    events: list[dict] = []
    deps = deps_with(*responses)
    deps.event_sink = events.append
    return deps, events


async def test_full_run_emits_one_node_end_per_role_with_products() -> None:
    deps, events = _collect(
        make_card(),
        make_angles(),
        WRITER,
        PASS,
        CoverText(cover_text="押金差点没要回来"),
        HUMANIZED,
        GateJudgement(findings=[FALSE_POSITIVE]),
    )

    state = await finish_draft(await run_loop(make_state(), deps), deps)

    ends = [event for event in events if event["event"] == "node_end"]
    assert {event["node"] for event in ends} == set(ROLES)
    assert all(event["product"] for event in ends)
    assert all(event["prompt_sha8"] for event in ends)
    assert all(event["ok"] is True and event["degraded"] is False for event in ends)
    assert state["status"] == "passed"


async def test_gate_retry_emits_nine_events_with_attempt_two() -> None:
    deps, events = _collect(
        make_card(),
        make_angles(),
        WRITER,
        PASS,
        CoverText(cover_text="押金差点没要回来"),
        HUMANIZED,
        GateJudgement(findings=[SMELL_HIT]),  # 第一次：真的命中
        HUMANIZED,  # 带着 hint 再校订一次
        GateJudgement(findings=[FALSE_POSITIVE]),  # 复核：判成误报
    )

    await finish_draft(await run_loop(make_state(), deps), deps)

    ends = [event for event in events if event["event"] == "node_end"]
    assert len(ends) == 9
    gatekeepers = [event for event in ends if event["node"] == "gatekeeper"]
    assert [event["attempt"] for event in gatekeepers] == [1, 2]
    assert [event["seq"] for event in ends] == sorted(event["seq"] for event in ends)


async def test_writer_failure_emits_ok_false_without_product() -> None:
    deps, events = _collect(
        make_card(), make_angles(), NodeCallFailed("writer", 2, RuntimeError("炸了"), Usage())
    )

    state = await run_loop(make_state(), deps)

    assert state["status"] == "failed"
    ends = [event for event in events if event["event"] == "node_end"]
    writer = next(event for event in ends if event["node"] == "writer")
    assert writer["ok"] is False
    assert "product" not in writer
    assert "炸了" in writer["error"]


async def test_reader_fallback_emits_degraded_not_failure() -> None:
    deps, events = _collect(
        make_card(),
        make_angles(),
        WRITER,
        NodeCallFailed("reader", 2, RuntimeError("上游 500"), Usage(cost_cny=0.01)),
    )

    await run_loop(make_state(), deps)

    reader = next(
        event for event in events if event["event"] == "node_end" and event["node"] == "reader"
    )
    assert reader["ok"] is True
    assert reader["degraded"] is True
    assert reader["degraded_reason"]
    assert reader["product"]["click"] is False


async def test_node_usage_delta_sums_to_total() -> None:
    deps, events = _collect(
        make_card(),
        make_angles(),
        WRITER,
        PASS,
        CoverText(cover_text="押金差点没要回来"),
        HUMANIZED,
        GateJudgement(findings=[FALSE_POSITIVE]),
    )

    state = await finish_draft(await run_loop(make_state(), deps), deps)

    total = sum(event["usage"]["cost_cny"] for event in events if event["event"] == "node_end")
    assert total == pytest.approx(state["usage"].cost_cny)
