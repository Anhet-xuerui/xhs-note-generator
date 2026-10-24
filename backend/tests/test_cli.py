"""CLI 入口（Task 9）：`python -m app.cli run --persona ... --topic ...`。"""

from __future__ import annotations

import json
from pathlib import Path

import app.cli as cli
from app.schemas import PersonaInput, Verdict, WriterResponse

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

def test_cli_reports_failed_checks_when_exhausted(monkeypatch, capsys):
    """§7：失败也要给可解释的结果，不能只说「没通过」。"""
    persona = PersonaInput.model_validate_json(PERSONA.read_text(encoding="utf-8"))
    bad = Verdict(click=False, click_reason="太像广告", read_through=0.42, save=False, comment_intent=False)
    second_draft = make_writer_output(persona)
    second_draft.responses = [WriterResponse(objection_index=0, decision="accept", reason="改")] if bad.objections else []
    deps = deps_with(
        make_card(),
        make_angles(),
        make_writer_output(persona),
        bad,
        second_draft,
        bad.model_copy(deep=True),          # 两轮判定相同 → 一级卡死，循环终止
    )
    monkeypatch.setattr(cli, "build_deps", lambda: deps)

    code = cli.main(["run", "--persona", str(PERSONA), "--topic", "租房第一年"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["status"] == "exhausted"
    assert any(c["code"] == "read_through" for c in payload["meta"]["failed_checks"])
