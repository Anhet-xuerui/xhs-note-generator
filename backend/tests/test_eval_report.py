"""评测报告与 CLI（Task 5）。"""

from __future__ import annotations

import app.cli as cli
from app.evaluation.report import html, markdown, synthetic_bundle


def test_markdown_has_three_experiments_and_limitations():
    text = markdown(synthetic_bundle())

    assert "E1 判别力" in text
    assert "排序正确率" in text
    assert "Kendall" in text
    assert "Cohen κ" in text
    assert "E3 消融" in text
    assert "局限" in text


def test_html_is_self_contained():
    page = html(synthetic_bundle())

    assert page.startswith("<!doctype html>")
    assert "http://" not in page and "https://" not in page


def test_cli_eval_dry_run_writes_both_reports(tmp_path, capsys):
    code = cli.main(["eval", "--dry-run", "--out", str(tmp_path)])

    assert code == 0
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "report.html").read_text(encoding="utf-8").startswith("<!doctype html>")
    assert "dry-run" in (tmp_path / "report.md").read_text(encoding="utf-8")
