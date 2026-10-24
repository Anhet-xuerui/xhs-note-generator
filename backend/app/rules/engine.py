"""规则引擎：正则先筛，结构规则看长度（§9）。

模型不负责「记住违禁词」——它只判断命中项是不是误报，并给改写建议。
「最 / 第一」这类词误报极多（最后、第一次），这正是守门人值得存在的那一半工作。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from app.schemas import GateFinding

DEFAULT_RULES_PATH = Path(__file__).with_name("rules.yaml")


@dataclass(frozen=True)
class Rule:
    id: str
    patterns: tuple[str, ...]
    severity: Literal["blocking", "warning"]
    hint: str


@dataclass(frozen=True)
class StructureRule:
    id: str
    field: str
    severity: Literal["blocking", "warning"]
    min: int
    max: int
    hint: str


def _load_yaml(path: Path | None = None) -> dict:
    raw = (path or DEFAULT_RULES_PATH).read_text(encoding="utf-8")
    return yaml.safe_load(raw) or {}


def load_rules(path: Path | None = None) -> list[Rule]:
    data = _load_yaml(path)
    return [
        Rule(
            id=item["id"],
            patterns=tuple(item.get("patterns") or ()),
            severity=item.get("severity", "blocking"),
            hint=item.get("hint", ""),
        )
        for item in data.get("rules") or []
    ]


def load_structure_rules(path: Path | None = None) -> list[StructureRule]:
    data = _load_yaml(path)
    return [
        StructureRule(
            id=item["id"],
            field=item["field"],
            severity=item.get("severity", "warning"),
            min=int(item["min"]),
            max=int(item["max"]),
            hint=item.get("hint", ""),
        )
        for item in data.get("structure") or []
    ]


def match(text: str, rules: list[Rule] | None = None) -> list[GateFinding]:
    """纯正则命中；`false_positive` 一律先给 False，等模型判。"""
    findings: list[GateFinding] = []
    for rule in rules if rules is not None else load_rules():
        for pattern in rule.patterns:
            for found in re.finditer(re.escape(pattern), text):
                findings.append(
                    GateFinding(
                        rule_id=rule.id,
                        severity=rule.severity,
                        matched=found.group(0),
                        span=(found.start(), found.end()),
                        false_positive=False,
                        hint=rule.hint,
                    )
                )
    return findings


def match_structure(
    body: str,
    tags: list[str],
    rules: list[StructureRule] | None = None,
) -> list[GateFinding]:
    findings: list[GateFinding] = []
    for rule in rules if rules is not None else load_structure_rules():
        value = len(body) if rule.field == "body" else len(tags)
        if value < rule.min or value > rule.max:
            findings.append(
                GateFinding(
                    rule_id=rule.id,
                    severity=rule.severity,
                    matched=str(value),
                    span=(0, 0),
                    false_positive=False,
                    hint=f"{rule.hint}（当前 {value}）",
                )
            )
    return findings
