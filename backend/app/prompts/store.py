"""prompt 覆盖层：`data/prompts.json` 的读写与校验（设计 D10-1 / D10-6 / §8）。

只有「改过的角色」才落盘，没改过的一律用代码里的默认值（S3）。
写入是原子的（临时文件 + `os.replace`）：单人本地够用，不值得引锁。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from app.prompts.defaults import DEFAULTS, ROLES
from app.prompts.set import PromptSet

MAX_PROMPT_CHARS = 20000
FILE_VERSION = 1
# store.py → prompts → app → backend：从哪个目录启动都一样，覆盖层只有一份。
BACKEND_ROOT = Path(__file__).resolve().parents[2]

# 与 scripts/check_invariants.py 的 READER_HIDDEN 同集合；
# tests/test_prompts.py 有一条用例盯着两边别漂移。
READER_FORBIDDEN = frozenset(
    {
        "real_material",
        "angle",
        "angle_history",
        "verdicts",
        "feedback_history",
        "previous_objections",
        "taboo",
    }
)


class PromptError(ValueError):
    """prompt 写入被拒绝。"""


class UnknownPromptRole(PromptError):
    pass


class EmptyPrompt(PromptError):
    pass


class PromptTooLong(PromptError):
    pass


class PromptGuardError(PromptError):
    """读者的 prompt 里出现了隔离信息——写进去等于把 C3 交给运气。"""

    def __init__(self, token: str) -> None:
        super().__init__(f"读者 prompt 不得提及「{token}」：读者在结构上就不该看到它（§6/C3）")
        self.token = token


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def guard_reader_text(text: str) -> None:
    """拦「读者不该看到的字段名」。

    两侧只排除 ASCII 单词字符：中文直接贴着写（「看real_material打分」）也算命中，
    但 `angle` 不会把 `triangle` 一起毙掉；大小写变体一并拦下——模型不认大小写。
    """
    for token in sorted(READER_FORBIDDEN):
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])"
        if re.search(pattern, text, re.IGNORECASE):
            raise PromptGuardError(token)


class PromptStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else self.default_path()

    @classmethod
    def default_path(cls) -> Path:
        env = os.environ.get("XHS_PROMPT_STORE")
        return Path(env) if env else BACKEND_ROOT / "data" / "prompts.json"

    # --- 读 ---------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # 手改坏了文件不该让服务起不来：退回全默认，用户还能在界面上重存一次。
            return {}
        return payload if isinstance(payload, dict) else {}

    def read_overrides(self) -> dict[str, str]:
        raw = self._load().get("overrides")
        if not isinstance(raw, dict):
            return {}
        overrides: dict[str, str] = {}
        for role, item in raw.items():
            if role in DEFAULTS and isinstance(item, dict) and isinstance(item.get("text"), str):
                overrides[role] = item["text"]
        return overrides

    def snapshot(self) -> PromptSet:
        return PromptSet.from_overrides(self.read_overrides())

    def items(self) -> list[dict[str, Any]]:
        raw = self._load().get("overrides")
        raw = raw if isinstance(raw, dict) else {}
        snapshot = self.snapshot()
        rows: list[dict[str, Any]] = []
        for role in ROLES:
            entry = raw.get(role)
            updated = entry.get("updated_at") if isinstance(entry, dict) else None
            rows.append(
                {
                    "role": role,
                    "text": snapshot.text(role),
                    "default_text": DEFAULTS[role],
                    "source": snapshot.sources[role],
                    "sha8": snapshot.sha8(role),
                    "updated_at": updated if snapshot.sources[role] == "edited" else None,
                }
            )
        return rows

    # --- 写 ---------------------------------------------------------------

    def set(self, role: str, text: str) -> PromptSet:
        self._validate(role, text)
        overrides = self.read_overrides()
        overrides[role] = text
        self._write(overrides)
        return self.snapshot()

    def reset(self, role: str | None = None) -> PromptSet:
        if role is None:
            self._write({})
            return self.snapshot()
        if role not in DEFAULTS:
            raise UnknownPromptRole(f"未知角色：{role}")
        overrides = self.read_overrides()
        overrides.pop(role, None)
        self._write(overrides)
        return self.snapshot()

    def _validate(self, role: str, text: str) -> None:
        if role not in DEFAULTS:
            raise UnknownPromptRole(f"未知角色：{role}")
        if not text.strip():
            raise EmptyPrompt("prompt 不能是空白")
        if len(text) > MAX_PROMPT_CHARS:
            raise PromptTooLong(f"prompt 超过 {MAX_PROMPT_CHARS} 字符")
        if role == "reader":
            guard_reader_text(text)

    def _write(self, overrides: Mapping[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stamp = _now()
        payload = {
            "version": FILE_VERSION,
            "updated_at": stamp,
            "overrides": {
                role: {"text": text, "updated_at": stamp} for role, text in overrides.items()
            },
        }
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", delete=False, dir=self.path.parent, suffix=".tmp"
        )
        try:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, self.path)
