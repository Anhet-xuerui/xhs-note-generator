"""真实 API 冒烟（默认不跑）。

    uv run pytest -m live

需要 .env 里同时配好 WRITER_* 与 READER_*；缺任何一个就跳过，不 FAIL。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.cli import build_deps, new_state
from app.graph.loop import run_loop
from app.schemas import PersonaInput

PERSONA = Path(__file__).resolve().parents[1] / "scripts" / "personas" / "p01.json"

pytestmark = pytest.mark.live

requires_keys = pytest.mark.skipif(
    not (os.getenv("WRITER_API_KEY") and os.getenv("READER_API_KEY")),
    reason="需要真实 API：配好 .env 后跑 `uv run pytest -m live`",
)


@requires_keys
async def test_real_run_produces_valid_note():
    persona = PersonaInput.model_validate_json(PERSONA.read_text(encoding="utf-8"))

    out = await run_loop(new_state(persona, "租房第一年我终于搞清楚的事"), build_deps())

    assert out["status"] in {"passed", "exhausted"}
    assert out["draft"] is not None
    assert 100 <= len(out["draft"].body) <= 1200
    assert out["usage"].cost_cny < 1.0      # §4：单次 run 预算 1 元
