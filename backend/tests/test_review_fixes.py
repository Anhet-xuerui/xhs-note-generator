"""整支评审的修复用例（C1/C2、I1–I3、I5–I9）。

每组用例对应评审里的一条 finding，先红后绿。
"""

from __future__ import annotations

import httpx2 as httpx
import pytest

from app.agents.profile import run_profile
from app.agents.writer import run_writer
from app.cli import result_payload
from app.config import Settings
from app.graph.decisions import detect_stuck, pick_best_round
from app.graph.loop import run_loop
from app.llm.client import LLMClient, NodeCallFailed
from app.schemas import Draft, PersonaInput, ProfileCard, RunInput, Verdict
from tests.helpers import deps_with, make_angles, make_card, make_state, make_writer_output


def _completion(content: str, *, usage: bool = True) -> dict:
    payload = {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "deepseek-flash",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    }
    if usage:
        payload["usage"] = {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}
    return payload


def _transport(*payloads: dict) -> httpx.MockTransport:
    seq = list(payloads)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=seq.pop(0))

    return httpx.MockTransport(handler)


# --- C1：失败调用也要计费 -------------------------------------------------


async def test_failed_call_carries_usage_in_exception():
    settings = Settings(writer_api_key="k", reader_api_key="r", reader_base_url="https://r.example/v1", reader_model="qwen-plus")
    client = LLMClient(
        settings,
        http_client=httpx.AsyncClient(transport=_transport(_completion("不是 JSON"), _completion("还不是"))),
    )

    with pytest.raises(NodeCallFailed) as excinfo:
        await client.structured(role="writer", system="s", user="u", schema=Verdict)

    assert excinfo.value.usage.calls == 2
    assert excinfo.value.usage.cost_cny > 0


async def test_missing_usage_is_an_error():
    settings = Settings(writer_api_key="k", reader_api_key="r", reader_base_url="https://r.example/v1", reader_model="qwen-plus")
    client = LLMClient(
        settings,
        http_client=httpx.AsyncClient(transport=_transport(_completion('{"click": true, "read_through": 0.8}', usage=False))),
    )

    with pytest.raises(RuntimeError, match="usage"):
        await client.structured(role="writer", system="s", user="u", schema=Verdict)


# --- C2：别的节点挂了不能崩 ------------------------------------------------


async def test_planner_failure_falls_back_to_previous_angle():
    state = make_state()
    state["angle"] = make_angles().angles[0]
    deps = deps_with(
        make_card(),
        NodeCallFailed("planner", 2, RuntimeError("boom")),
        make_writer_output(),
        Verdict(click=True, click_reason="ok", read_through=0.9, save=True, comment_intent=True),
    )

    out = await run_loop(state, deps)

    assert out["angle"] is not None
    assert out["status"] in {"exhausted", "passed"}


async def test_unpriced_reader_model_is_allowed(monkeypatch):
    """D11：价格可缺省；缺席的后果是成本显示「未计价」，不是拒绝启动。"""
    for name, value in {
        "WRITER_API_KEY": "w",
        "READER_API_KEY": "r",
        "READER_BASE_URL": "https://reader.example/v1",
        "READER_MODEL": "not-in-prices",
    }.items():
        monkeypatch.setenv(name, value)

    settings = Settings.load(_env_file=None)

    assert settings.reader_model == "not-in-prices"


def test_reader_may_share_writer_model(monkeypatch):
    """D11：允许同模型，但由 run 快照标出「不独立」，不再在启动时拦。"""
    for name, value in {
        "WRITER_API_KEY": "w",
        "WRITER_BASE_URL": "https://api.deepseek.com",
        "WRITER_MODEL": "deepseek-flash",
        "READER_API_KEY": "r",
        "READER_BASE_URL": "https://api.deepseek.com",
        "READER_MODEL": "deepseek-flash",
    }.items():
        monkeypatch.setenv(name, value)

    settings = Settings.load(_env_file=None)

    assert settings.reader_model == settings.writer_model


# --- I1/I2：降级判定卡不参与「最佳轮」，且第一轮就失败直接收工 -------------


def test_degraded_round_is_not_picked_as_best():
    good = Verdict(click=True, click_reason="a", read_through=0.9, save=False, comment_intent=False)
    degraded_copy = good.model_copy(deep=True)

    assert pick_best_round([good, degraded_copy], degraded_rounds=[2]) == 1


async def test_reader_failure_on_round_one_stops_immediately():
    state = make_state()
    deps = deps_with(
        make_card(), make_angles(), make_writer_output(),
        NodeCallFailed("reader", 2, RuntimeError("boom")),
    )

    out = await run_loop(state, deps)

    assert len(out["verdicts"]) == 1
    assert out["status"] == "exhausted"
    assert out["degraded_rounds"] == [1]


# --- I3：未达标项要描述交付的那一轮 ---------------------------------------


def test_failed_checks_describe_the_delivered_round():
    state = make_state()
    state["best_round"] = 1
    state["verdicts"] = [
        Verdict(click=False, click_reason="第一轮", read_through=0.42, save=False, comment_intent=False),
        Verdict(click=True, click_reason="第三轮", read_through=0.95, save=True, comment_intent=True),
    ]
    state["draft"] = Draft(title="t", body="b", tags=[])

    payload = result_payload(state)

    codes = [c["code"] for c in payload["meta"]["failed_checks"]]
    assert "read_through" in codes          # 第一轮没读完；最后一轮是过的
    assert any("42%" in c["detail"] for c in payload["meta"]["failed_checks"])


# --- I5：只有 1 条素材时不该白烧一次调用 -----------------------------------


async def test_single_material_persona_needs_only_one_hit():
    persona = PersonaInput(
        nickname="x", age_range="25-30", city="上海", occupation="市场", goal="涨粉",
        tone=["直给"], real_material=["被二房东坑过押金"], taboo=[],
    )
    state = {
        "input": RunInput(persona=persona, topic="租房"),
        "profile": ProfileCard(**persona.model_dump(), anchors=[]),
        "angle": make_angles().angles[0],
        "round": 1,
        "feedback_history": [],
    }
    out = make_writer_output(persona)

    draft, _ = await run_writer(state, deps_with(out))

    assert "被二房东坑过押金" in draft.body


# --- I6：client 缓存要区分 key --------------------------------------------


def test_client_cache_is_keyed_by_key_too():
    settings = Settings(writer_api_key="k", reader_api_key="r", reader_base_url="https://r.example/v1", reader_model="qwen-plus")
    client = LLMClient(settings)

    assert client._client("https://same.example/v1", "key-a") is not client._client("https://same.example/v1", "key-b")


# --- I8：anchors 全被过滤掉时要兜底 ---------------------------------------


async def test_empty_anchors_fall_back_to_real_material():
    state = make_state()

    card = await run_profile(state, deps_with(make_card().model_copy(update={"anchors": []})))

    assert card.anchors == state["input"].persona.real_material[:2]


# --- I7：节点层重试不再放大尝试预算 ---------------------------------------


async def test_writer_retry_does_not_multiply_attempt_budget():
    state = make_state()
    deps = deps_with(
        make_writer_output(),                    # 素材不足，触发节点层重试
        make_writer_output(),
    )
    # 让第一次输出既无素材又合法
    deps.llm.queue[0] = make_writer_output(
        PersonaInput(nickname="x", age_range="1", city="c", occupation="o", goal="g",
                     tone=["t"], real_material=["完全不相干的素材"], taboo=[])
    )

    await run_writer(state, deps)

    assert all(a == 1 for a in deps.llm.max_attempts_seen)


# --- I4：二级卡死要在第 2 轮就能触发 --------------------------------------


def test_no_gain_stops_after_second_round():
    high = Verdict(click=True, click_reason="a", read_through=0.9, save=False, comment_intent=False)
    low = Verdict(click=False, click_reason="b", read_through=0.1, save=False, comment_intent=False)

    assert detect_stuck([high, low]) == "stuck_no_gain"
