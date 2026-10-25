"""事件落盘与单文件 HTML 报告（Task 7）。"""

from __future__ import annotations

import app.cli as cli
from app.prompts import DEFAULTS, PromptSet
from app.report.html import render_report
from app.report.trace import append_event, build_trace, read_events

RESULT = {
    "title": "租房第三年，我才知道中介不会告诉你的三件事",
    "cover_text": "中介没说的三件事",
    "body": "被二房东坑过一个月押金，最后靠报警要回一半。\n\n搬家那天电梯坏了。",
    "tags": ["租房", "沪漂", "避坑"],
    "status": "exhausted",
    "meta": {
        "rounds_used": 2,
        "best_round": 1,
        "smell": {"before": 62, "after": 28, "fidelity": "passed"},
        "changes": 3,
        "gate_findings": [
            {"rule_id": "absolute-claim", "severity": "blocking", "matched": "最", "span": [0, 1], "false_positive": True, "hint": "「最后」不是极限词"}
        ],
        "usage": {"input_tokens": 8060, "output_tokens": 2823, "cost_cny": 0.0456, "calls": 7, "elapsed_s": 37.16},
        "failed_checks": [{"code": "read_through", "label": "没读完", "detail": "只读完 42%"}],
    },
}

EVENTS = [
    {"event": "round", "round": 1, "verdict": {"click": False, "save": False, "read_through": 0.42}},
    {"event": "round", "round": 2, "verdict": {"click": True, "save": False, "read_through": 0.7}},
]


def test_trace_roundtrip(tmp_path):
    path = tmp_path / "trace.jsonl"

    append_event(path, {"event": "a", "n": 1})
    append_event(path, {"event": "b", "n": 2})

    assert read_events(path) == [{"event": "a", "n": 1}, {"event": "b", "n": 2}]


def test_report_is_self_contained():
    html = render_report(EVENTS, RESULT)

    assert html.startswith("<!doctype html>")
    assert "http://" not in html and "https://" not in html
    assert "AI 味" in html
    assert "62" in html and "28" in html
    assert "被二房东坑过一个月押金" in html              # 正文在里面
    assert "第 1 轮" in html and "第 2 轮" in html
    assert "0.0456" in html


def test_report_survives_missing_sections():
    html = render_report([], {"title": None, "body": None, "status": "failed", "meta": {}})

    assert "<!doctype html>" in html
    assert "failed" in html


def test_cli_report_writes_file(tmp_path, capsys):
    trace = tmp_path / "t.jsonl"
    append_event(trace, {"event": "result", "data": RESULT})
    out = tmp_path / "report.html"

    code = cli.main(["report", "--trace", str(trace), "--out", str(out)])

    assert code == 0
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_cli_report_missing_trace_returns_1(tmp_path, capsys):
    assert cli.main(["report", "--trace", str(tmp_path / "nope.jsonl"), "--out", str(tmp_path / "x.html")]) == 1
    assert "nope.jsonl" in capsys.readouterr().err


def test_report_includes_prompt_texts_and_edited_badge():
    """报告是唯一活得过进程重启的证据（S1）：七个 prompt 的全文得在里面。"""
    snapshot = PromptSet.defaults().with_text("writer", "改过的主笔 prompt")
    state = {"prompts": snapshot.record()}
    payload = {"title": "t", "body": "b", "status": "passed", "meta": {}}

    page = render_report(build_trace(state, payload), payload)

    assert "改过的主笔 prompt" in page
    assert "已改动" in page
    assert DEFAULTS["reader"][:12] in page


def test_report_without_prompt_snapshot_still_renders():
    payload = {"title": "t", "body": "b", "status": "passed", "meta": {}}

    page = render_report(build_trace({}, payload), payload)

    assert "<!doctype html>" in page
    assert "没有记录 prompt 快照" in page
