"""CLI 入口（Task 9）：`python -m app.cli run --persona ... --topic ...`。"""

from __future__ import annotations

import json
from pathlib import Path

import app.cli as cli
from app.schemas import PersonaInput, Verdict

from tests.helpers import deps_with, make_angles, make_card, make_writer_output

PERSONA = Path(__file__).resolve().parents[1] / "scripts" / "personas" / "p01.json"


def test_cli_writes_result_json(monkeypatch, capsys):
    persona = PersonaInput.model_validate_json(PERSONA.read_text(encoding="utf-8"))
    deps = deps_with(
        make_card(),
        make_angles(),
        make_writer_output(persona),
        Verdict(click=True, click_reason="标题具体", read_through=0.9, save=True, comment_intent=True),
    )
    monkeypatch.setattr(cli, "build_deps", lambda: deps)

    code = cli.main(["run", "--persona", str(PERSONA), "--topic", "租房第一年"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["status"] in {"passed", "exhausted"}
    assert payload["title"]
    assert payload["meta"]["rounds_used"] == 1
    assert payload["meta"]["usage"]["calls"] == 4


def test_cli_missing_persona_file_returns_1(capsys):
    assert cli.main(["run", "--persona", "nope.json", "--topic", "x"]) == 1
    assert "nope.json" in capsys.readouterr().err
