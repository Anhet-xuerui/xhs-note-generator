"""`data/models.json`：七个角色各自的模型覆盖。

只有「改过的角色」才落盘；其余跟着 .env 的默认值。
写文件同样是临时文件 + `os.replace`，单人本地够用。
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from app.models.set import ModelSet
from app.prompts.defaults import ROLES

MAX_MODEL_CHARS = 120
FILE_VERSION = 1
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class ModelError(ValueError):
    """模型配置被拒绝。"""


class UnknownModelRole(ModelError):
    pass


class EmptyModelName(ModelError):
    pass


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class ModelStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else self.default_path()

    @classmethod
    def default_path(cls) -> Path:
        env = os.environ.get("XHS_MODEL_STORE")
        return Path(env) if env else BACKEND_ROOT / "data" / "models.json"

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def read_overrides(self) -> dict[str, str]:
        raw = self._load().get("overrides")
        if not isinstance(raw, dict):
            return {}
        overrides: dict[str, str] = {}
        for role, item in raw.items():
            if role in ROLES and isinstance(item, dict) and isinstance(item.get("model"), str):
                overrides[role] = item["model"]
        return overrides

    def snapshot(self, defaults: Mapping[str, str]) -> ModelSet:
        return ModelSet.from_overrides(self.read_overrides(), defaults)

    def items(self, defaults: Mapping[str, str]) -> list[dict[str, Any]]:
        raw = self._load().get("overrides")
        raw = raw if isinstance(raw, dict) else {}
        snapshot = self.snapshot(defaults)
        rows: list[dict[str, Any]] = []
        for role in ROLES:
            entry = raw.get(role)
            rows.append(
                {
                    "role": role,
                    "model": snapshot.model(role),
                    "default_model": defaults.get(role, ""),
                    "source": snapshot.sources[role],
                    "updated_at": (
                        entry.get("updated_at")
                        if isinstance(entry, dict) and snapshot.sources[role] == "edited"
                        else None
                    ),
                }
            )
        return rows

    def set(self, role: str, model: str, defaults: Mapping[str, str]) -> ModelSet:
        self._validate(role, model)
        overrides = self.read_overrides()
        overrides[role] = model
        self._write(overrides)
        return self.snapshot(defaults)

    def reset(self, role: str | None, defaults: Mapping[str, str]) -> ModelSet:
        if role is None:
            self._write({})
            return self.snapshot(defaults)
        if role not in ROLES:
            raise UnknownModelRole(f"未知角色：{role}")
        overrides = self.read_overrides()
        overrides.pop(role, None)
        self._write(overrides)
        return self.snapshot(defaults)

    def _validate(self, role: str, model: str) -> None:
        if role not in ROLES:
            raise UnknownModelRole(f"未知角色：{role}")
        if not model.strip():
            raise EmptyModelName("模型名不能为空")
        if len(model) > MAX_MODEL_CHARS:
            raise EmptyModelName(f"模型名超过 {MAX_MODEL_CHARS} 字符")

    def _write(self, overrides: Mapping[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stamp = _now()
        payload = {
            "version": FILE_VERSION,
            "updated_at": stamp,
            "overrides": {
                role: {"model": model, "updated_at": stamp} for role, model in overrides.items()
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
