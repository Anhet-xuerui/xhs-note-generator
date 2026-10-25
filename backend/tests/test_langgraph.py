"""LangGraph 编排：与手写 loop 行为一致，且能落 checkpoint。"""

from __future__ import annotations

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agents.cover import CoverText
from app.agents.gatekeeper import GateJudgement
from app.agents.humanize import HumanizeOutput
from app.graph.langgraph_pipeline import build_graph, prepare
from app.schemas import Verdict
from tests.helpers import deps_with, make_angles, make_card, make_state, make_writer_output

BODY = make_writer_output().draft.body


def passing() -> Verdict:
    return Verdict(click=True, click_reason="ok", read_through=0.9, save=True, comment_intent=True)


def rising(rt: float) -> Verdict:
    return Verdict(click=True, click_reason="still not enough", read_through=rt, save=False, comment_intent=False)


def tail() -> list:
    return [
        CoverText(cover_text="押金差点没要回来"),
        HumanizeOutput(title="t", body=BODY, tags=["a", "b", "c"], changes=[]),
        GateJudgement(findings=[]),
    ]


async def test_graph_matches_loop_on_passing_run():
    deps = deps_with(make_card(), make_angles(), make_writer_output(), passing(), *tail())
    graph = build_graph(deps)

    out = await graph.ainvoke(prepare(dict(make_state())))

    assert out["status"] == "passed"
    assert len(out["verdicts"]) == 1
    assert out["draft"].cover_text == "押金差点没要回来"
    assert deps.llm.roles == [
        "profile",
        "planner",
        "writer",
        "reader",
        "cover",
        "humanizer",
        "gatekeeper",
    ]


async def test_graph_stops_at_round_cap():
    deps = deps_with(
        make_card(),
        make_angles(),
        make_writer_output(), rising(0.1),
        make_writer_output(), rising(0.6),
        make_writer_output(), rising(0.9),
        *tail(),
    )
    graph = build_graph(deps)

    out = await graph.ainvoke(prepare(dict(make_state())))

    assert out["status"] == "exhausted"
    assert len(out["verdicts"]) == 3
    assert out["best_round"] == 3


async def test_checkpoint_persists_state(tmp_path):
    deps = deps_with(make_card(), make_angles(), make_writer_output(), passing(), *tail())
    config = {"configurable": {"thread_id": "run-1"}}

    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.sqlite")) as saver:
        graph = build_graph(deps, saver)
        out = await graph.ainvoke(prepare(dict(make_state())), config)
        snapshot = await graph.aget_state(config)

    assert out["status"] == "passed"
    assert snapshot.values["status"] == "passed"
    assert snapshot.values["draft"].title == out["draft"].title
