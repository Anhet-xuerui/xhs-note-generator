"""单轮编排与三轮循环（Task 9 / Task 10）。"""

from __future__ import annotations

from app.agents.writer import WriterOutput
from app.graph.loop import run_loop, run_once
from app.llm.client import NodeCallFailed
from app.schemas import Objection, Verdict, WriterResponse
from tests.helpers import deps_with, make_angles, make_card, make_state, make_writer_output


def passing_verdict() -> Verdict:
    return Verdict(click=True, click_reason="标题具体", read_through=0.9, save=True, comment_intent=True)


def failing_verdict() -> Verdict:
    return Verdict(click=False, click_reason="太像广告", read_through=0.2, save=False, comment_intent=False)


def wo(tag: str, responses: int = 0) -> WriterOutput:
    """每轮一版不同的稿子；有上一轮异议时必须逐条回应（Task 7 的契约）。"""
    base = make_writer_output()
    return WriterOutput(
        draft=base.draft.model_copy(update={"title": f"标题{tag}"}),
        responses=[WriterResponse(objection_index=i, decision="accept", reason="改") for i in range(responses)],
    )


def hook_weak(reason: str) -> Verdict:
    return Verdict(
        click=False,
        click_reason=reason,
        read_through=0.2,
        save=False,
        comment_intent=False,
        objections=[
            # quote 必须在正文里真实存在，否则会被读者的引文校验丢掉（Task 8）
            Objection(
                sentence_index=2,
                quote="被二房东坑过一个月押金",
                problem_type="hook_weak",
                suggestion="换个开头",
            )
        ],
    )


# --- 单轮（Task 9） --------------------------------------------------------


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


# --- 三轮循环（Task 10） ---------------------------------------------------


async def test_stops_on_pass():
    state = make_state()
    deps = deps_with(
        make_card(), make_angles(),
        wo("1"), failing_verdict(),
        wo("2"), passing_verdict(),
    )

    out = await run_loop(state, deps)

    assert out["status"] == "passed"
    assert len(out["verdicts"]) == 2
    assert out["best_round"] is None


async def test_returns_best_round_not_last():
    state = make_state()
    high = Verdict(click=True, click_reason="标题好", read_through=0.9, save=False, comment_intent=False)
    lower = Verdict(click=False, click_reason="b", read_through=0.5, save=False, comment_intent=False)
    lowest = Verdict(click=False, click_reason="c", read_through=0.2, save=False, comment_intent=False)
    deps = deps_with(
        make_card(), make_angles(),
        wo("1"), high,
        wo("2"), lower,
        wo("3"), lowest,
    )

    out = await run_loop(state, deps)

    assert out["status"] == "exhausted"
    assert out["best_round"] == 1
    assert out["draft"] is out["draft_history"][0]


async def test_stuck_on_two_identical_verdicts():
    state = make_state()
    first = hook_weak("同一句")
    second = first.model_copy(deep=True)
    deps = deps_with(
        make_card(), make_angles(),
        wo("1"), first,
        wo("2", responses=1), second,
    )

    out = await run_loop(state, deps)

    assert len(out["verdicts"]) == 2
    assert out["status"] == "exhausted"


async def test_new_angle_at_most_once():
    state = make_state()
    deps = deps_with(
        make_card(), make_angles(),
        wo("1"), hook_weak("r1"),
        wo("2", responses=1), hook_weak("r2"),
        make_angles(),                       # 重开角度只允许这一次
        wo("3", responses=1), hook_weak("r3"),
    )

    out = await run_loop(state, deps)

    assert len(out["angle_history"]) == 2


async def test_never_exceeds_three_rounds():
    state = make_state()
    v1 = Verdict(click=False, click_reason="a", read_through=0.1, save=False, comment_intent=False)
    v2 = Verdict(click=True, click_reason="b", read_through=0.2, save=False, comment_intent=False)
    v3 = Verdict(click=True, click_reason="c", read_through=0.2, save=False, comment_intent=True)
    deps = deps_with(
        make_card(), make_angles(),
        wo("1"), v1,
        wo("2"), v2,
        wo("3"), v3,
    )

    out = await run_loop(state, deps)

    assert len(out["verdicts"]) == 3
    assert out["status"] == "exhausted"
    assert out["best_round"] == 3
