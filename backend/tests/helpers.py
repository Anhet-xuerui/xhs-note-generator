"""测试辅助：假 LLM 与 deps 构造。

放在独立模块而不是 conftest，避免测试之间靠隐式导入互相看见。
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.llm.client import CallResult, Deps
from app.schemas import Usage


class FakeLLM:
    """按顺序吐出预设响应；可塞异常来模拟调用失败。"""

    def __init__(self, *responses: Any) -> None:
        self.queue = list(responses)
        self.roles: list[str] = []
        self.users: list[str] = []

    async def structured(self, *, role: str, system: str, user: str, schema: type):
        self.roles.append(role)
        self.users.append(user)
        item = self.queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        usage = Usage(input_tokens=100, output_tokens=50, cost_cny=0.01, calls=1, elapsed_s=0.5)
        return CallResult(value=item, usage=usage, attempts=1)


def make_settings(**overrides: Any) -> Settings:
    base = {
        "writer_api_key": "w-key",
        "reader_api_key": "r-key",
        "reader_base_url": "https://reader.example/v1",
        "reader_model": "qwen-plus",
    }
    base.update(overrides)
    return Settings(**base)


def deps_with(*responses: Any) -> Deps:
    return Deps(llm=FakeLLM(*responses), settings=make_settings())
