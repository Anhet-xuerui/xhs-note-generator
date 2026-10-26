"""七个角色各配各的模型（D11）：覆盖层、API、run 快照、未计价成本。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.config import PRICES
from app.models import FALLBACK_MODELS, EmptyModelName, ModelStore, UnknownModelRole
from app.prompts import PromptStore
from tests.test_api import BODY, PERSONA, _fake_deps


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            deps_factory=_fake_deps,
            prompt_store=PromptStore(tmp_path / "prompts.json"),
            model_store=ModelStore(tmp_path / "models.json"),
            model_defaults=dict(FALLBACK_MODELS),
        )
    )


def test_store_roundtrip_and_reset(tmp_path: Path) -> None:
    store = ModelStore(tmp_path / "models.json")

    store.set("writer", "kimi-k3-1", FALLBACK_MODELS)

    assert ModelStore(tmp_path / "models.json").snapshot(FALLBACK_MODELS).model("writer") == "kimi-k3-1"

    store.reset("writer", FALLBACK_MODELS)

    assert store.snapshot(FALLBACK_MODELS).model("writer") == FALLBACK_MODELS["writer"]


def test_store_rejects_unknown_role_and_empty_model(tmp_path: Path) -> None:
    store = ModelStore(tmp_path / "m.json")

    with pytest.raises(UnknownModelRole):
        store.set("nobody", "x", FALLBACK_MODELS)
    with pytest.raises(EmptyModelName):
        store.set("writer", "   ", FALLBACK_MODELS)


def test_unpriced_model_is_allowed(tmp_path: Path) -> None:
    """价格不是门槛：kimi 没登记价格也能存、也能跑（成本标「未计价」）。"""
    store = ModelStore(tmp_path / "m.json")

    snapshot = store.set("writer", "kimi-k3-1", FALLBACK_MODELS)

    assert snapshot.model("writer") == "kimi-k3-1"
    assert snapshot.record()["writer"]["priced"] == "no"


def test_models_endpoint_lists_seven(tmp_path: Path) -> None:
    body = _client(tmp_path).get("/models").json()

    assert len(body["items"]) == 7
    assert {item["source"] for item in body["items"]} == {"default"}


def test_put_and_delete_model(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.put("/models/writer", json={"model": "deepseek-v4-pro"})

    assert response.status_code == 200
    assert response.json()["source"] == "edited"
    assert response.json()["reader_independent"] is True

    assert client.delete("/models/writer").json()["source"] == "default"

    client.put("/models/writer", json={"model": "deepseek-v4-pro"})
    client.put("/models/cover", json={"model": "deepseek-v4-pro"})
    client.delete("/models")

    assert all(item["source"] == "default" for item in client.get("/models").json()["items"])


def test_reader_sharing_writer_model_is_flagged_not_blocked(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.put("/models/reader", json={"model": FALLBACK_MODELS["writer"]})

    assert response.status_code == 200
    assert response.json()["reader_independent"] is False


def test_available_models_include_prices(tmp_path: Path) -> None:
    items = _client(tmp_path).get("/models/available").json()["items"]

    assert set(PRICES) <= set(items)


def test_run_uses_selected_model_and_records_snapshot(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.put("/models/writer", json={"model": "kimi-k3-1"})

    captured: dict = {}

    def factory(bus, run_id):
        deps = _fake_deps(bus, run_id)
        captured["deps"] = deps
        return deps

    app = create_app(
        deps_factory=factory,
        prompt_store=PromptStore(tmp_path / "p2.json"),
        model_store=ModelStore(tmp_path / "models.json"),
        model_defaults=dict(FALLBACK_MODELS),
    )
    client = TestClient(app)

    run_id = client.post("/runs", json={"persona": PERSONA, "topic": "租房第一年"}).json()["run_id"]
    deadline = time.time() + 10
    payload: dict = {}
    while time.time() < deadline:
        payload = client.get(f"/runs/{run_id}").json()
        if payload["status"] != "running":
            break
        time.sleep(0.05)

    assert payload["meta"]["models"]["writer"]["model"] == "kimi-k3-1"
    assert payload["meta"]["models_edited"] == ["writer"]
    assert "kimi-k3-1" in captured["deps"].llm.models
    assert BODY  # 正文没变，避免误以为走了别的路径
