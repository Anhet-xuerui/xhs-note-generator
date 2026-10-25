"""FastAPI 服务：提交 / 快照 / 报告 / 覆写判定 / 事件回放（Task API）。"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.agents.cover import CoverText
from app.agents.gatekeeper import GateJudgement
from app.agents.humanize import HumanizeOutput
from app.api.app import create_app
from app.api.bus import RunBus
from app.schemas import GateFinding, Verdict
from tests.helpers import deps_with, make_angles, make_card, make_persona, make_writer_output

PERSONA = make_persona().model_dump()
BODY = make_writer_output().draft.body

PASS = Verdict(click=True, click_reason="标题具体", read_through=0.9, save=True, comment_intent=True)
FP = GateJudgement(
    findings=[
        GateFinding(
            rule_id="absolute-claim",
            severity="blocking",
            matched="最",
            span=(0, 1),
            false_positive=True,
            hint="「最后」不是极限词",
        )
    ]
)


def _client() -> TestClient:
    def factory(bus: RunBus, run_id: str):
        deps = deps_with(
            make_card(),
            make_angles(),
            make_writer_output(),
            PASS,
            CoverText(cover_text="押金差点没要回来"),
            HumanizeOutput(title="租房第三年", body=BODY, tags=["租房", "沪漂", "避坑"], changes=[]),
            FP,
        )
        deps.event_sink = lambda event: bus.publish(run_id, event)
        return deps

    return TestClient(create_app(deps_factory=factory))


def _create(client: TestClient) -> str:
    response = client.post("/runs", json={"persona": PERSONA, "topic": "租房第一年"})
    assert response.status_code == 200
    return response.json()["run_id"]


def _wait(client: TestClient, run_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/runs/{run_id}").json()
        if payload["status"] != "running":
            return payload
        time.sleep(0.05)
    raise AssertionError("run 未在超时内完成")


def test_index_serves_the_built_vue_app():
    from app.api.app import INDEX

    if not INDEX.exists():
        pytest.skip("前端未构建：cd frontend && pnpm build")

    page = _client().get("/")

    assert page.status_code == 200
    assert 'id="app"' in page.text
    assert "小红书多角色笔记生成" in page.text


def test_create_run_reaches_result():
    client = _client()
    run_id = _create(client)

    payload = _wait(client, run_id)

    assert payload["status"] == "passed"
    assert payload["title"]
    assert payload["meta"]["usage"]["calls"] == 7


def test_unknown_run_returns_404():
    assert _client().get("/runs/nope").status_code == 404


def test_report_page_renders_after_run():
    client = _client()
    run_id = _create(client)
    _wait(client, run_id)

    page = client.get(f"/runs/{run_id}/report")

    assert page.status_code == 200
    assert page.text.startswith("<!doctype html>")


def test_override_verdict_updates_last_card():
    client = _client()
    run_id = _create(client)
    _wait(client, run_id)

    response = client.post(f"/runs/{run_id}/override-verdict", json={"click": False})

    assert response.status_code == 200
    assert response.json()["verdict"]["click"] is False


async def test_bus_replays_history_before_live_events():
    bus = RunBus()
    bus.publish("r1", {"event": "node_start", "node": "profile"})
    bus.publish("r1", {"event": "done"})

    seen = [event async for event in bus.subscribe("r1")]

    assert [event["event"] for event in seen] == ["node_start", "done"]


def test_events_endpoint_requires_known_run():
    assert _client().get("/runs/nope/events").status_code == 404


@pytest.mark.parametrize("path", ["/health"])
def test_health(path):
    assert _client().get(path).json() == {"ok": True}

def test_events_stream_delivers_the_whole_timeline():
    """评审 C1 的回归：SSE 必须真的把事件吐出来，否则界面永远停在「生成中」。"""
    client = _client()
    run_id = _create(client)
    _wait(client, run_id)

    with client.stream("GET", f"/runs/{run_id}/events") as response:
        body = b"".join(response.iter_bytes()).decode("utf-8")

    assert response.status_code == 200
    assert "node_start" in body
    assert "result" in body
    assert body.count("node_start") >= 6


def test_config_failure_becomes_an_error_event_not_a_hang():
    """评审 C2 的回归：deps 构造失败也要落 error + result，状态不能停在 running。"""

    def broken_factory(bus, run_id):
        raise RuntimeError("缺少 READER_ 配置")

    client = TestClient(create_app(deps_factory=broken_factory))
    run_id = _create(client)
    payload = _wait(client, run_id)

    assert payload["status"] == "failed"

    with client.stream("GET", f"/runs/{run_id}/events") as response:
        body = b"".join(response.iter_bytes()).decode("utf-8")
    assert "event: error" in body
    assert "event: result" in body
