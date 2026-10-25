"""事实保真校验：人味校订只许做减法，不许改事实（§8）。

四条硬约束，任一违反即回退整篇改写。比「重问一次」便宜也更诚实——改写失败一次就收手。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas import PersonaInput, ProfileCard

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
PLACE_RE = re.compile(
    r"[\u4e00-\u9fa5]{2,6}(?:公园|广场|小区|大厦|公寓|花园|商场|超市|医院|学校|大学|路|街|弄|站)"
)
QUOTED_RE = re.compile(r"[“\"「『]([^”\"」』]{1,20})[”\"」』]")
LATIN_CAPS_RE = re.compile(r"\b[A-Z][A-Za-z0-9&.\-]{1,20}\b")

MIN_RATIO = 0.85
MAX_RATIO = 1.15


@dataclass(frozen=True)
class FidelityResult:
    ok: bool
    reason: str = ""


def numbers_of(text: str) -> list[str]:
    return sorted(NUMBER_RE.findall(text))


def proper_nouns_of(text: str) -> list[str]:
    """专名：地名后缀、引号内文本、全大写拉丁词。宁可少抓，不可乱抓。"""
    found = set(PLACE_RE.findall(text))
    found |= set(QUOTED_RE.findall(text))
    found |= set(LATIN_CAPS_RE.findall(text))
    return sorted(found)


def check(before: str, after: str, profile: ProfileCard | PersonaInput) -> FidelityResult:
    if not before.strip():
        return FidelityResult(True)

    if numbers_of(before) != numbers_of(after):
        return FidelityResult(False, "数字集合变了")

    if proper_nouns_of(before) != proper_nouns_of(after):
        return FidelityResult(False, "专名集合变了")

    # 没有画像卡时退化为「真实经历的前两条」，至少不放弃锚点这一条约束。
    anchors = getattr(profile, "anchors", None) or list(profile.real_material[:2])
    # 只约束「原文里真的用到了」的锚点：主笔只被要求用 2 条素材，剩下 8 条不在正文里，
    # 要求它们出现在改写结果里等于必定回退（评审 I8）。
    missing = [anchor for anchor in anchors if anchor in before and anchor not in after]
    if missing:
        return FidelityResult(False, f"素材锚点丢了：{missing[0]}")

    ratio = len(after) / len(before)
    if not (MIN_RATIO <= ratio <= MAX_RATIO):
        return FidelityResult(False, f"长度变化 {ratio:.0%}，超出 ±15%")

    return FidelityResult(True)
