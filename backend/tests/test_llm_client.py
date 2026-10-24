"""LLM 客户端：JSON 围栏、校验失败重问、超时重试、计费（Task 2）。

全部用 `httpx2.MockTransport` 伪造 OpenAI 兼容响应，不打网络（openai 3.x 的传输层是 httpx2）。
"""

from __future__ import annotations

import json

import httpx2 as httpx
import pytest
from pydantic import BaseModel

from app.config import PRICES, Settings
from app.llm.client import LLMClient, NodeCallFailed, UnknownModelPrice


class Sample(BaseModel):
    click: bool
    read_through: float


def _completion(content: str) -> dict:
    return {
        "id": "cmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "deepseek-flash",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
    }


def transport(*contents: str, captured: list[dict] | None = None) -> httpx.MockTransport:
    """按顺序返回给定 content；captured 收集请求体，用于断言参数。"""
    seq = list(contents)

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(json.loads(request.content))
        return httpx.Response(200, json=_completion(seq.pop(0)))

    return httpx.MockTransport(handler)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        writer_api_key="w-key",
        reader_api_key="r-key",
        reader_base_url="https://reader.example/v1",
        reader_model="qwen-plus",
    )


async def test_strips_code_fence_and_parses(settings):
    fence = chr(96) * 3
    body = f'{fence}json\n{{"click": true, "read_through": 0.8}}\n{fence}'
    client = LLMClient(settings, http_client=httpx.AsyncClient(transport=transport(body)))

    result = await client.structured(role="writer", system="s", user="u", schema=Sample)

    assert result.value.click is True
    assert result.attempts == 1
    assert result.degraded is False


async def test_retries_once_with_validation_error(settings):
    bad = '{"click": true, "read_through": "abc"}'
    good = '{"click": true, "read_through": 0.8}'
    client = LLMClient(settings, http_client=httpx.AsyncClient(transport=transport(bad, good)))

    result = await client.structured(role="writer", system="s", user="u", schema=Sample)

    assert result.attempts == 2
    assert result.usage.calls == 2


async def test_raises_after_two_failures(settings):
    bad = '{"click": true, "read_through": "abc"}'
    client = LLMClient(settings, http_client=httpx.AsyncClient(transport=transport(bad, bad)))

    with pytest.raises(NodeCallFailed):
        await client.structured(role="writer", system="s", user="u", schema=Sample)


async def test_cost_uses_price_table_and_rate(settings):
    body = '{"click": true, "read_through": 0.8}'
    client = LLMClient(settings, http_client=httpx.AsyncClient(transport=transport(body)))

    result = await client.structured(role="writer", system="s", user="u", schema=Sample)

    pin, pout = PRICES[settings.writer_model]
    expected_usd = (1000 * pin + 500 * pout) / 1_000_000
    assert result.usage.cost_cny == pytest.approx(expected_usd * settings.usd_cny_rate)


async def test_unpriced_model_raises(settings):
    settings.reader_model = "unknown-model"
    body = '{"click": true, "read_through": 0.8}'
    client = LLMClient(settings, http_client=httpx.AsyncClient(transport=transport(body)))

    with pytest.raises(UnknownModelPrice, match="unknown-model"):
        await client.structured(role="reader", system="s", user="u", schema=Sample)


async def test_transport_timeout_retries_once_then_succeeds(settings):
    """超时属于传输层失败，与 schema 失败共用「两次调用」预算（§10）。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("boom", request=request)
        return httpx.Response(200, json=_completion('{"click": true, "read_through": 0.8}'))

    client = LLMClient(
        settings, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    result = await client.structured(role="writer", system="s", user="u", schema=Sample)

    assert result.attempts == 2
    assert result.usage.calls == 2


async def test_thinking_disabled_and_json_mode_requested(settings):
    captured: list[dict] = []
    body = '{"click": true, "read_through": 0.8}'
    client = LLMClient(
        settings, http_client=httpx.AsyncClient(transport=transport(body, captured=captured))
    )

    await client.structured(role="writer", system="s", user="u", schema=Sample)

    assert captured[0]["thinking"] == {"type": "disabled"}
    assert captured[0]["response_format"] == {"type": "json_object"}
