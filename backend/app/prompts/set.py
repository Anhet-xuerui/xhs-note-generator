"""某一次 run 的 prompt 快照（设计 D10-3）。

`PromptSet` 是不可变的：一旦创建，后续编辑覆盖层不会改到它。
这是「事后看这个 run，看到的一定是它当时用的文本」这件事的机械保证。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from app.prompts.defaults import DEFAULTS, ROLES

Source = Literal["default", "edited"]


def prompt_sha8(text: str) -> str:
    """短指纹：够用来对表，不够用来复原，正好——全文也在快照里。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


@dataclass(frozen=True, slots=True)
class PromptSet:
    texts: Mapping[str, str]
    sources: Mapping[str, Source]

    def __post_init__(self) -> None:
        missing = [role for role in ROLES if role not in self.texts]
        if missing:
            raise ValueError(f"PromptSet 缺少角色：{missing}")

    @classmethod
    def defaults(cls) -> PromptSet:
        return cls(texts=dict(DEFAULTS), sources={role: "default" for role in ROLES})

    @classmethod
    def from_overrides(cls, overrides: Mapping[str, str]) -> PromptSet:
        texts = dict(DEFAULTS) | {role: text for role, text in overrides.items() if role in DEFAULTS}
        sources: dict[str, Source] = {
            role: "edited" if role in overrides else "default" for role in ROLES
        }
        return cls(texts=texts, sources=sources)

    def with_text(self, role: str, text: str) -> PromptSet:
        self._require(role)
        return PromptSet(
            texts=dict(self.texts) | {role: text},
            sources=dict(self.sources) | {role: "edited"},
        )

    def text(self, role: str) -> str:
        return self.texts[self._require(role)]

    def sha8(self, role: str) -> str:
        return prompt_sha8(self.text(role))

    def edited_roles(self) -> list[str]:
        return [role for role in ROLES if self.sources.get(role) == "edited"]

    def record(self) -> dict[str, dict[str, str]]:
        return {
            role: {"text": self.text(role), "sha8": self.sha8(role), "source": self.sources[role]}
            for role in ROLES
        }

    def _require(self, role: str) -> str:
        if role not in self.texts:
            raise KeyError(f"未知角色：{role}")
        return role
