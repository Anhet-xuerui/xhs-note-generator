"""独立评审器：把任意一篇稿子交给指定 provider 当读者打分（§12 评分口径统一）。

E1/E2 要比「同一批稿在不同判定器下的排序」，E3 要让三组成稿都由**同一个**读者实例评分——
所以这里不复用 `run_reader`（它绑定 state 与 provider 选择），而是只做「稿子 + 画像 → Verdict」。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.agents.reader import render_reader_prompt
from app.context import build_reader_context
from app.llm.client import Deps
from app.prompts.defaults import READER_PROMPT
from app.schemas import Draft, PersonaInput, RunInput, Usage, Verdict
from app.state import RunState


@dataclass(frozen=True)
class Judgement:
    verdict: Verdict
    usage: Usage


def reader_prompt_sha256() -> str:
    """读者 prompt 的指纹：写进报告，回答「你改过 prompt 之后还叫同一组数据吗」（§12）。"""
    return hashlib.sha256(READER_PROMPT.encode("utf-8")).hexdigest()[:12]


async def judge_draft(
    draft: Draft,
    persona: PersonaInput,
    deps: Deps,
    *,
    role_provider: str = "reader",
) -> Judgement:
    state: RunState = {
        "input": RunInput(persona=persona, topic="评测"),
        "draft": draft,
        "round": 1,
    }
    context = build_reader_context(state)
    result = await deps.llm.structured(
        role=role_provider,
        system=READER_PROMPT,
        user=render_reader_prompt(context),
        schema=Verdict,
    )

    verdict = result.value
    # 与 reader 节点同规则：引文不在正文里的异议一律丢弃（模型会编句子）。
    verdict.objections = [o for o in verdict.objections if o.quote and o.quote in draft.body]
    return Judgement(verdict=verdict, usage=result.usage)
