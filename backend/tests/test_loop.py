"""单轮编排（Task 9）。"""

from __future__ import annotations

from app.graph.loop import run_once
from app.llm.client import NodeCallFailed
from app.schemas import Verdict

from tests.helpers import deps_with, make_angles, make_card, make_state, make_writer_output


def passing_verdict() -> Verdict:
    return Verdict(click=True, click_reason="标题具体", read_through=0.9, save=True, comment_intent=True)


def failing_verdict() -> Verdict:
    return Verdict(click=False, click_reason="太像广告", read_through=0.2, save=False, comment_intent=False)


async def test_run_once_fills_every_state_field():
    state = make_state()
    deps = deps_with(make_card(), make_angles(), make_writer_output(), passing_verdict())

    out = await run_once(state, deps)

    assert out["profile"] and out["angle"] and out["draft"]
    assert len(out["verdicts"]) == 1
    assert out["round"] == 1
    assert out["usage"].calls == 4  # 画像官 / 策划 / 主笔 / 读者 各一次


async def test_run_once_marks_exhausted_when_verdict_fails():
    state = make_state()
    deps = deps_with(make_card(), make_angles(), make_writer_output(), failing_verdict())

    out = await run_once(state, deps)

    assert out["status"] == "exhausted"


async def test_writer_failure_marks_run_failed():
    state = make_state()
    deps = deps_with(make_card(), make_angles(), NodeCallFailed("writer", 2, RuntimeError("boom")))

    out = await run_once(state, deps)

    assert out["status"] == "failed"
    assert out["draft"] is None
