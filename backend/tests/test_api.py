"""FastAPI 服务：提交 / 快照 / 报告 / 覆写判定 / 事件回放（Task API）+ prompt 接口（D10）。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.cover import CoverText
from app.agents.gatekeeper import GateJudgement
from app.agents.humanize import HumanizeOutput
from app.api.app import create_app
from app.api.bus import RunBus
from app.prompts import ROLES, PromptStore
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


def _fake_deps(bus: RunBus, run_id: str):
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


def _client() -> TestClient:
    return TestClient(create_app(deps_factory=_fake_deps))


def _client_with_store(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(deps_factory=_fake_deps, prompt_store=PromptStore(tmp_path / "prompts.json"))
    )


def _client_and_captured(tmp_path: Path) -> tuple[TestClient, dict]:
    """同一套假响应，但把造出来的 Deps 留下来——用来断言 agent 真的收到了覆盖层文本。"""
    captured: dict = {}

    def factory(bus: RunBus, run_id: str):
        deps = _fake_deps(bus, run_id)
        captured["deps"] = deps
        return deps

    app = create_app(deps_factory=factory, prompt_store=PromptStore(tmp_path / "prompts.json"))
    return TestClient(app), captured


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
    # 逐轮判定卡必须出现在报告里（评审 I2：之前只有节点事件，表是空的）
    assert "第 1 轮" in page.text
    assert "会点开" in page.text


def test_override_verdict_updates_last_card():
    client = _client()
    run_id = _create(client)
    _wait(client, run_id)

    response = client.post(f"/runs/{run_id}/override-verdict", json={"click": False})

    assert response.status_code == 200
    payload = response.json()
    assert payload["verdict"]["click"] is False
    # 改判之后结论要跟着变，否则这个接口等于没做事（评审 I10）
    assert payload["status"] == "exhausted"
    assert payload["best_round"] == 1
    assert client.get(f"/runs/{run_id}").json()["status"] == "exhausted"


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

def test_empty_topic_is_rejected_not_500():
    """评审 M12：空主题应该 422，而不是在 handler 里炸成 500。"""
    client = _client()

    response = client.post("/runs", json={"persona": PERSONA, "topic": ""})

    assert response.status_code == 422


def test_prompts_endpoint_lists_seven_defaults(tmp_path: Path):
    body = _client_with_store(tmp_path).get("/prompts").json()

    assert body["roles"] == list(ROLES)
    assert len(body["items"]) == 7
    assert {item["source"] for item in body["items"]} == {"default"}
    assert all(item["sha8"] and item["default_text"] for item in body["items"])


def test_put_and_delete_prompt_roundtrip(tmp_path: Path):
    client = _client_with_store(tmp_path)

    assert client.put("/prompts/writer", json={"text": "新 prompt"}).json()["source"] == "edited"
    edited = [item["role"] for item in client.get("/prompts").json()["items"] if item["source"] == "edited"]
    assert edited == ["writer"]

    assert client.delete("/prompts/writer").json()["source"] == "default"

    client.put("/prompts/writer", json={"text": "新 prompt"})
    client.put("/prompts/cover", json={"text": "新封面"})
    client.delete("/prompts")

    assert all(item["source"] == "default" for item in client.get("/prompts").json()["items"])


@pytest.mark.parametrize("text", ["", "   ", "x" * 20001], ids=["empty", "blank", "too-long"])
def test_put_prompt_rejects_bad_text(tmp_path: Path, text: str):
    response = _client_with_store(tmp_path).put("/prompts/writer", json={"text": text})

    assert response.status_code == 422


def test_put_prompt_unknown_role_is_404(tmp_path: Path):
    response = _client_with_store(tmp_path).put("/prompts/nobody", json={"text": "x"})

    assert response.status_code == 404


def test_put_reader_prompt_is_guarded(tmp_path: Path):
    response = _client_with_store(tmp_path).put(
        "/prompts/reader", json={"text": "看看 real_material 再打分"}
    )

    assert response.status_code == 409
    assert "real_material" in response.json()["detail"]


def test_run_uses_active_prompt_and_snapshots_it(tmp_path: Path):
    client, captured = _client_and_captured(tmp_path)
    client.put("/prompts/writer", json={"text": "改过的主笔 prompt"})

    run_id = _create(client)
    payload = _wait(client, run_id)

    deps = captured["deps"]
    assert deps.prompts.text("writer") == "改过的主笔 prompt"
    assert deps.llm.systems[2] == "改过的主笔 prompt"  # profile, planner, writer…
    assert payload["meta"]["prompts_edited"] == ["writer"]
    assert set(payload["meta"]["prompts_sha8"]) == set(ROLES)

    items = client.get(f"/runs/{run_id}/prompts").json()["items"]
    writer = next(item for item in items if item["role"] == "writer")
    assert writer["source"] == "edited"
    assert writer["text"] == "改过的主笔 prompt"


def test_run_snapshot_survives_later_edit(tmp_path: Path):
    """改完 prompt 回去看旧 run，看到的必须是旧文本（D10-4）。"""
    client, _ = _client_and_captured(tmp_path)
    client.put("/prompts/writer", json={"text": "第一版"})
    run_id = _create(client)
    _wait(client, run_id)

    client.put("/prompts/writer", json={"text": "第二版"})

    items = client.get(f"/runs/{run_id}/prompts").json()["items"]
    assert next(item for item in items if item["role"] == "writer")["text"] == "第一版"


def test_list_runs_is_newest_first(tmp_path: Path):
    client, _ = _client_and_captured(tmp_path)
    first = _create(client)
    _wait(client, first)
    second = _create(client)
    _wait(client, second)

    items = client.get("/runs").json()["items"]

    assert [item["run_id"] for item in items][:2] == [second, first]
    assert items[0]["topic"] == "租房第一年"
    assert items[0]["prompts_edited"] == []
    assert items[0]["created_at"]
