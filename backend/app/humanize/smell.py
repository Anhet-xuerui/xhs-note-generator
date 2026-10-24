"""AI 味检测器：六类可程序化的特征（§8）。

设计原则与守门人同构：**规则先算出命中项，模型只按命中项改写**。这样「AI 味 62 → 28」
才是可复现的数字，而不是又一次模型自评。
"""

from __future__ import annotations

import re
import statistics
from typing import Literal

import jieba.posseg as pseg

from app.schemas import SmellHit, SmellReport

# 抽象名词：模型最爱拿来冒充洞见的词
ABSTRACT_NOUNS: tuple[str, ...] = (
    "焦虑",
    "成长",
    "治愈",
    "松弛感",
    "边界感",
    "内耗",
    "自洽",
    "情绪价值",
    "安全感",
    "底层逻辑",
    "认知",
    "能量",
)

# 典型 AI 句式
AI_PATTERNS: tuple[str, ...] = (
    r"不是[^。！？\n]{0,20}而是",
    r"不仅[^。！？\n]{0,20}更是",
    r"愿你",
    r"其实",
    r"本质上",
    r"某种程度上",
    r"如果你也",
    r"让我们",
)

CATEGORY_PENALTY: dict[str, float] = {
    "abstract_noun": 18,
    "idiom_density": 12,
    "ai_pattern": 20,
    "uniform_paragraph": 10,
    "no_anchor": 25,
    "emoji_rhythm": 8,
}

IDIOM_RATIO_MIN = 0.08
PARAGRAPH_CV_MAX = 0.18
EMOJI_RE = re.compile("[\U0001f300-\U0001faff\u2600-\u27bf]")
ANCHOR_RE = re.compile(r"\d|[一二三四五六七八九十百千万]+(?:年|月|号|天|岁|块|元|平)")


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _abstract_nouns(text: str) -> SmellHit | None:
    spans: list[tuple[int, int]] = []
    examples: list[str] = []
    for word in ABSTRACT_NOUNS:
        start = text.find(word)
        if start >= 0:
            spans.append((start, start + len(word)))
            examples.append(word)
    if not spans:
        return None
    return SmellHit(
        category="abstract_noun",
        spans=spans,
        examples=examples,
        penalty=CATEGORY_PENALTY["abstract_noun"],
    )


def _idiom_density(text: str) -> SmellHit | None:
    words = [(w, flag) for w, flag in pseg.cut(text) if w.strip()]
    if len(words) < 20:
        return None
    idioms = [w for w, flag in words if flag == "i"]
    if len(idioms) / len(words) < IDIOM_RATIO_MIN:
        return None
    return SmellHit(
        category="idiom_density",
        spans=[(text.find(w), text.find(w) + len(w)) for w in idioms[:5]],
        examples=idioms[:5],
        penalty=CATEGORY_PENALTY["idiom_density"],
    )


def _ai_patterns(text: str) -> SmellHit | None:
    spans: list[tuple[int, int]] = []
    examples: list[str] = []
    for pattern in AI_PATTERNS:
        for match in re.finditer(pattern, text):
            spans.append((match.start(), match.end()))
            examples.append(match.group(0))
    if not spans:
        return None
    return SmellHit(
        category="ai_pattern",
        spans=spans[:10],
        examples=examples[:10],
        penalty=CATEGORY_PENALTY["ai_pattern"],
    )


def _uniform_paragraph(text: str) -> SmellHit | None:
    paragraphs = _paragraphs(text)
    if len(paragraphs) < 3:
        return None
    lengths = [len(p) for p in paragraphs]
    mean = statistics.fmean(lengths)
    if mean == 0:
        return None
    cv = statistics.pstdev(lengths) / mean
    if cv >= PARAGRAPH_CV_MAX:
        return None
    return SmellHit(
        category="uniform_paragraph",
        spans=[],
        examples=[f"{len(paragraphs)} 段，长度变异系数 {cv:.2f}"],
        penalty=CATEGORY_PENALTY["uniform_paragraph"],
    )


def _no_anchor(text: str) -> SmellHit | None:
    if not text.strip() or ANCHOR_RE.search(text):
        return None
    return SmellHit(
        category="no_anchor",
        spans=[],
        examples=["全文没有数字、时间、地点或直接引语"],
        penalty=CATEGORY_PENALTY["no_anchor"],
    )


def _emoji_rhythm(text: str) -> SmellHit | None:
    paragraphs = _paragraphs(text)
    if len(paragraphs) < 3:
        return None
    if not all(paragraph and EMOJI_RE.match(paragraph[-1]) for paragraph in paragraphs):
        return None
    spans = [(len(p) - 1, len(p)) for p in paragraphs]
    return SmellHit(
        category="emoji_rhythm",
        spans=spans,
        examples=["每段结尾都是 emoji"],
        penalty=CATEGORY_PENALTY["emoji_rhythm"],
    )


def detect(text: str) -> SmellReport:
    """返回 0–100 的 AI 味分（越高越像 AI）与逐类命中。"""
    if not text.strip():
        return SmellReport(score=0, hits=[])

    detectors = (
        _abstract_nouns,
        _idiom_density,
        _ai_patterns,
        _uniform_paragraph,
        _no_anchor,
        _emoji_rhythm,
    )
    hits = [hit for detector in detectors if (hit := detector(text)) is not None]
    score = min(100, round(sum(hit.penalty for hit in hits)))
    return SmellReport(score=score, hits=hits)
