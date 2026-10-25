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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from openai import APIConnectionError, APIStatusError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import PRICES, Settings, UnknownModelPrice
from app.prompts import PromptSet
from app.schemas import Usage

if TYPE_CHECKING:  # pragma: no cover
    import httpx2

TModel = TypeVar("TModel", bound=BaseModel)

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*|\s*```$")

# 上游 5xx / 429 多半是网络或限流，重试一次常常就好了；4xx 重试只会重复犯错。
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class NodeCallFailed(RuntimeError):
    """节点调用失败。**必须带上已花掉的用量**，否则成本会被系统性低估（评审 C1）。"""

    def __init__(self, role: str, attempts: int, last_error: BaseException, usage: Usage | None = None) -> None:
        super().__init__(f"节点 {role} 调用失败（{attempts} 次尝试）：{last_error}")
        self.role = role
        self.attempts = attempts
        self.last_error = last_error
        self.usage = usage or Usage()


class MissingUsage(RuntimeError):
    """响应缺少 usage：计费无从计算，宁可报错也不按 0 记。"""


@dataclass(slots=True)
class CallResult(Generic[TModel]):
    value: TModel
    usage: Usage
    degraded: bool = False
    attempts: int = 1


@dataclass(slots=True)
class Deps:
    """节点依赖集合：所有 agent 只吃这个，不自己读环境变量。"""

    llm: LLMClient
    settings: Settings
    # 可选的事件出口：SSE 端点把节点起止推给前端；CLI 不传就是 None。
    event_sink: Callable[[dict[str, Any]], None] | None = None
    # 本次 run 用的 prompt 文本；默认取默认版，API 注入快照（D10-1/D10-3）。
    prompts: PromptSet = field(default_factory=PromptSet.defaults)


def extract_json(text: str) -> str:
    """从可能带代码围栏或解释文字的输出里取出 JSON 对象。"""
    raw = _FENCE_RE.sub("", text.strip()).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("响应中没有 JSON 对象")
    return raw[start : end + 1]


class LLMClient:
    def __init__(self, settings: Settings, *, http_client: httpx2.AsyncClient | None = None) -> None:
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
        # 按 (base_url, api_key) 缓存：同一 base_url 下读者与主笔 key 不同时必须各用各的。
        key = f"{base_url}|{api_key}"
        client = self._clients.get(key)
        if client is None:
            client = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=self._settings.request_timeout_s,
                max_retries=0,  # 重试由本层统一管，SDK 自己重试会让 attempts 失真
                http_client=self._http,
            )
            self._clients[key] = client
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
        max_attempts: int | None = None,
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
        budget = max_attempts if max_attempts is not None else 1 + max(0, self._settings.max_retries)
        last_error: BaseException | None = None

        for attempt in range(1, budget + 1):
            try:
                response = await client.chat.completions.create(**request)
                usage.calls += 1
                self._accumulate(usage, response.usage)
                content = response.choices[0].message.content or ""
            except MissingUsage as exc:
                # provider 不回 usage：计费无从计算，按节点失败处理（可降级），不要炸整个 run。
                usage.elapsed_s = time.perf_counter() - started
                raise NodeCallFailed(role, attempt, exc, usage=usage) from exc
            except APIConnectionError as exc:
                usage.calls += 1
                last_error = exc
                continue
            except APIStatusError as exc:
                usage.calls += 1
                last_error = exc
                if exc.status_code not in RETRYABLE_STATUS:
                    usage.elapsed_s = time.perf_counter() - started
                    usage.cost_cny = self._cost_cny(model, usage.input_tokens, usage.output_tokens)
                    raise NodeCallFailed(role, attempt, exc, usage=usage) from exc
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
        raise NodeCallFailed(role, budget, last_error or RuntimeError("未知失败"), usage=usage)

    @staticmethod
    def _accumulate(usage: Usage, raw: Any) -> None:
        if raw is None:
            raise MissingUsage("响应里没有 usage 字段，无法计费；请检查 provider 是否兼容 OpenAI 协议。")
        usage.input_tokens += getattr(raw, "prompt_tokens", 0) or 0
        usage.output_tokens += getattr(raw, "completion_tokens", 0) or 0
