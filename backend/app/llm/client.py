"""LLM 调用层：结构化输出 + 围栏剥离 + 校验失败重问 + 超时重试 + 计费。

失败预算统一为「最多两次调用」，两类失败共用这一个预算（设计文档 §10）：

- 返回内容不符合 pydantic schema → 把 `ValidationError` 原文追加进对话，重问 1 次；
- 传输层超时/连接错误 → 同样重问 1 次（消息不变）。

两次都失败 → `NodeCallFailed`，由调用方决定降级还是让 run 失败。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from openai import APIConnectionError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import PRICES, Settings

if TYPE_CHECKING:  # pragma: no cover
    import httpx2

TModel = TypeVar("TModel", bound=BaseModel)

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*|\s*```$")


class NodeCallFailed(RuntimeError):
    """节点调用两次仍失败。"""

    def __init__(self, role: str, attempts: int, last_error: BaseException) -> None:
        super().__init__(f"节点 {role} 调用失败（{attempts} 次尝试）：{last_error}")
        self.role = role
        self.attempts = attempts
        self.last_error = last_error


class UnknownModelPrice(RuntimeError):
    """价格表里没有这个模型——宁可报错，也不要按 0 计费把成本数字变成假的。"""

    def __init__(self, model: str) -> None:
        super().__init__(f"模型 {model} 未登记价格：请加进 app/config.py 的 PRICES（含抓取日期）。")
        self.model = model


@dataclass(slots=True)
class Usage:
    """累计用量。字段名与顺序在 Task 3 换成 pydantic 版时必须保持一致。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_cny: float = 0.0
    calls: int = 0
    elapsed_s: float = 0.0


@dataclass(slots=True)
class CallResult(Generic[TModel]):
    value: TModel
    usage: Usage
    degraded: bool = False
    attempts: int = 1


@dataclass(slots=True)
class Deps:
    """节点依赖集合：所有 agent 只吃这个，不自己读环境变量。"""

    llm: "LLMClient"
    settings: Settings


def extract_json(text: str) -> str:
    """从可能带代码围栏或解释文字的输出里取出 JSON 对象。"""
    raw = _FENCE_RE.sub("", text.strip()).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("响应中没有 JSON 对象")
    return raw[start : end + 1]


class LLMClient:
    def __init__(self, settings: Settings, *, http_client: "httpx2.AsyncClient | None" = None) -> None:
        self._settings = settings
        self._http = http_client
        self._clients: dict[str, AsyncOpenAI] = {}

    # -- provider -----------------------------------------------------------

    def _provider(self, role: str) -> tuple[str, str, str]:
        if role == "reader":
            return (
                self._settings.reader_base_url or "",
                self._settings.reader_api_key or "",
                self._settings.reader_model or "",
            )
        return (
            self._settings.writer_base_url,
            self._settings.writer_api_key or "",
            self._settings.writer_model,
        )

    def _client(self, base_url: str, api_key: str) -> AsyncOpenAI:
        client = self._clients.get(base_url)
        if client is None:
            client = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=self._settings.request_timeout_s,
                max_retries=0,  # 重试由本层统一管，SDK 自己重试会让 attempts 失真
                http_client=self._http,
            )
            self._clients[base_url] = client
        return client

    # -- 计费 ---------------------------------------------------------------

    def _price(self, model: str) -> tuple[float, float]:
        try:
            return PRICES[model]
        except KeyError as exc:
            raise UnknownModelPrice(model) from exc

    def _cost_cny(self, model: str, input_tokens: int, output_tokens: int) -> float:
        pin, pout = self._price(model)
        usd = (input_tokens * pin + output_tokens * pout) / 1_000_000
        return usd * self._settings.usd_cny_rate

    # -- 主入口 -------------------------------------------------------------

    async def structured(
        self,
        *,
        role: str,
        system: str,
        user: str,
        schema: type[TModel],
    ) -> CallResult[TModel]:
        base_url, api_key, model = self._provider(role)
        self._price(model)  # 未登记价格：在花钱之前就失败
        client = self._client(base_url, api_key)

        request: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        if self._settings.thinking_enabled:
            request["extra_body"] = {"thinking": {"type": "enabled"}}
        else:
            # 关掉思考：本项目要的是稳定结构化输出与低时延（§3 G1），不是推理题。
            request["extra_body"] = {"thinking": {"type": "disabled"}}
            request["temperature"] = 0.7

        usage = Usage()
        started = time.perf_counter()
        max_attempts = 1 + max(0, self._settings.max_retries)
        last_error: BaseException | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                response = await client.chat.completions.create(**request)
                usage.calls += 1
                self._accumulate(usage, response.usage)
                content = response.choices[0].message.content or ""
            except APIConnectionError as exc:
                usage.calls += 1
                last_error = exc
                continue

            try:
                payload = json.loads(extract_json(content))
                value = schema.model_validate(payload)
            except (ValueError, ValidationError) as exc:
                last_error = exc
                request["messages"] = [
                    *request["messages"],
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            f"上面的输出无法解析为 {schema.__name__}：{exc}\n"
                            "只输出一个符合该 schema 的 JSON 对象，不要任何解释或代码围栏。"
                        ),
                    },
                ]
                continue

            usage.elapsed_s = time.perf_counter() - started
            usage.cost_cny = self._cost_cny(model, usage.input_tokens, usage.output_tokens)
            return CallResult(value=value, usage=usage, attempts=attempt)

        usage.elapsed_s = time.perf_counter() - started
        usage.cost_cny = self._cost_cny(model, usage.input_tokens, usage.output_tokens)
        raise NodeCallFailed(role, max_attempts, last_error or RuntimeError("未知失败"))

    @staticmethod
    def _accumulate(usage: Usage, raw: Any) -> None:
        if raw is None:
            return
        usage.input_tokens += getattr(raw, "prompt_tokens", 0) or 0
        usage.output_tokens += getattr(raw, "completion_tokens", 0) or 0
