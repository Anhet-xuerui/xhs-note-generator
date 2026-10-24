"""CLI 入口（Task 9）：`python -m app.cli run --persona ... --topic ...`。"""

from __future__ import annotations

import json
from pathlib import Path

import app.cli as cli
from app.agents.cover import CoverText
from app.agents.gatekeeper import GateJudgement
from app.agents.humanize import HumanizeOutput
from app.schemas import GateFinding, PersonaInput, Verdict, WriterResponse
from tests.helpers import deps_with, make_angles, make_card, make_writer_output

PERSONA = Path(__file__).resolve().parents[1] / "scripts" / "personas" / "p01.json"

# 正文里有「最后」，正则必然命中；模型判成误报后应放行（§9 的误报判定）
OK_JUDGEMENT = GateJudgement(
    findings=[
        GateFinding(
            rule_id="absolute-claim",
            severity="blocking",
            matched="最",
            span=(0, 1),
            false_positive=True,
            hint="「最后」不是极限词",
        )
    ]
)


def test_cli_writes_result_json(monkeypatch, capsys):
    persona = PersonaInput.model_validate_json(PERSONA.read_text(encoding="utf-8"))
    body = make_writer_output(persona).draft.body
    deps = deps_with(
        make_card(),
        make_angles(),
        make_writer_output(persona),
        Verdict(click=True, click_reason="标题具体", read_through=0.9, save=True, comment_intent=True),
        CoverText(cover_text="押金差点没要回来"),
        HumanizeOutput(title="租房第三年", body=body, tags=["租房", "沪漂", "避坑"], changes=[]),
        OK_JUDGEMENT,
    )
    monkeypatch.setattr(cli, "build_deps", lambda: deps)

    code = cli.main(["run", "--persona", str(PERSONA), "--topic", "租房第一年"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["status"] in {"passed", "exhausted"}
    assert payload["title"]
    assert payload["meta"]["rounds_used"] == 1
    # 画像官 + 策划 + 主笔 + 读者 + 封面 + 人味校订 + 守门人
    assert payload["meta"]["usage"]["calls"] == 7


def test_cli_missing_persona_file_returns_1(capsys):
    assert cli.main(["run", "--persona", "nope.json", "--topic", "x"]) == 1
    assert "nope.json" in capsys.readouterr().err

def test_cli_reports_failed_checks_when_exhausted(monkeypatch, capsys):
    """§7：失败也要给可解释的结果，不能只说「没通过」。"""
    persona = PersonaInput.model_validate_json(PERSONA.read_text(encoding="utf-8"))
    bad = Verdict(click=False, click_reason="太像广告", read_through=0.42, save=False, comment_intent=False)
    second_draft = make_writer_output(persona)
    second_draft.responses = [WriterResponse(objection_index=0, decision="accept", reason="改")] if bad.objections else []
    body = make_writer_output(persona).draft.body
    deps = deps_with(
        make_card(),
        make_angles(),
        make_writer_output(persona),
        bad,
        second_draft,
        bad.model_copy(deep=True),          # 两轮判定相同 → 一级卡死，循环终止
        CoverText(cover_text="押金差点没要回来"),
        HumanizeOutput(title="租房第三年", body=body, tags=["租房", "沪漂", "避坑"], changes=[]),
        OK_JUDGEMENT,
    )
    monkeypatch.setattr(cli, "build_deps", lambda: deps)

    code = cli.main(["run", "--persona", str(PERSONA), "--topic", "租房第一年"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["status"] == "exhausted"
    assert any(c["code"] == "read_through" for c in payload["meta"]["failed_checks"])
