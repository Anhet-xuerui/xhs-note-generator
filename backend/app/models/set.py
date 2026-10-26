"""模型三层：默认（.env）→ 覆盖（data/models.json）→ 每次 run 的快照。

和 prompt 同一套思路，但少一个约束：**价格可以没有**。
没登记价格的模型照样能跑：token 照记，钱记成「未计价」，绝不写成 0。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.config import PRICES, Settings
from app.prompts.defaults import ROLES

# 没有 Settings 时（测试注入 deps_factory）的兜底：只影响界面默认值，不影响计费。
FALLBACK_MODELS: dict[str, str] = {
    role: ("glm-5.3-flash" if role == "reader" else "deepseek-v4.1-flash") for role in ROLES
}


def default_models(settings: Settings) -> dict[str, str]:
    """读者单独一组，其余六个角色跟写作侧走（和 .env 的写法一致）。"""
    return {
        role: (settings.reader_model or "") if role == "reader" else settings.writer_model
        for role in ROLES
    }


@dataclass(frozen=True, slots=True)
class ModelSet:
    models: Mapping[str, str]
    sources: Mapping[str, str]

    def __post_init__(self) -> None:
        missing = [role for role in ROLES if role not in self.models]
        if missing:
            raise ValueError(f"ModelSet 缺少角色：{missing}")

    @classmethod
    def defaults(cls, defaults: Mapping[str, str]) -> ModelSet:
        return cls(
            models={role: defaults.get(role, "") for role in ROLES},
            sources={role: "default" for role in ROLES},
        )

    @classmethod
    def from_overrides(cls, overrides: Mapping[str, str], defaults: Mapping[str, str]) -> ModelSet:
        base = {role: defaults.get(role, "") for role in ROLES}
        models = dict(base) | {role: model for role, model in overrides.items() if role in base}
        sources = {role: ("edited" if role in overrides else "default") for role in ROLES}
        return cls(models=models, sources=sources)

    def model(self, role: str) -> str:
        if role not in self.models:
            raise KeyError(f"未知角色：{role}")
        return self.models[role]

    def with_model(self, role: str, model: str) -> ModelSet:
        self.model(role)
        return ModelSet(
            models=dict(self.models) | {role: model},
            sources=dict(self.sources) | {role: "edited"},
        )

    def edited_roles(self) -> list[str]:
        return [role for role in ROLES if self.sources.get(role) == "edited"]

    def reader_independent(self) -> bool:
        """读者与写作侧是不是同一个模型——同一个就不是独立评审（报告要标出来）。"""
        return self.models.get("reader") != self.models.get("writer")

    def record(self) -> dict[str, dict[str, str]]:
        rows: dict[str, dict[str, str]] = {}
        for role in ROLES:
            model = self.model(role)
            rows[role] = {
                "model": model,
                "source": self.sources[role],
                "priced": "yes" if model in PRICES else "no",
            }
        return rows
