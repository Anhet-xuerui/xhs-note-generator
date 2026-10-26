"""人味校订：只做减法——删抽象词、拆长句、把形容词换成动作和数字（§8）。

三个不可让步的点：
1. 输入必须是**检测报告**而不是一句「写得更自然」；
2. 改完必须过保真校验，违反就整篇回退（不重试，重试只是烧钱）；
3. 回退时正文给改写前的版本，但 `changes` 保留——「想改但被拦下了什么」本身是证据。

prompt 文本在 `app/prompts/defaults.py`，运行时从 `deps.prompts` 取（D10-1）。
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.humanize.fidelity import FidelityResult, check, numbers_of, proper_nouns_of
from app.humanize.smell import detect
from app.llm.client import Deps, NodeCallFailed
from app.schemas import ChangeLog, Draft, HumanizedDraft
from app.state import RunState, mark_degraded, merge_usage


class HumanizeOutput(BaseModel):
    title: str
    body: str
    tags: list[str] = Field(default_factory=list)
    changes: list[ChangeLog] = Field(default_factory=list)


async def run_humanize(
    state: RunState,
    deps: Deps,
    *,
    hints: list[dict] | None = None,
) -> HumanizedDraft:
    draft = state.get("draft")
    before = draft.body if draft else ""
    title = draft.title if draft else ""
    tags = list(draft.tags) if draft else []
    cover_text = draft.cover_text if draft else None

    profile = state.get("profile") or state["input"].persona
    report = detect(before)

    if report.score == 0 and not hints:
        # 没有命中项 = 没有可减的东西。改也只会改坏，还白烧一次调用（联调发现）。
        clean = HumanizedDraft(
            title=title,
            cover_text=cover_text,
            body=before,
            tags=tags,
            smell_before=0,
            smell_after=0,
            changes=[],
            fidelity="skipped",
        )
        state["humanized"] = clean
        state["smell"] = report
        return clean

    context = {
        "title": title,
        "body": before,
        "tags": tags,
        "profile": profile.model_dump(),
        "smell_report": report.model_dump(),
        "gate_hints": hints or [],
    }

    try:
        result = await deps.llm.structured(
            role="humanizer",
            system=deps.prompts.text("humanizer"),
            model=deps.models.model("humanizer"),
            user=json.dumps(context, ensure_ascii=False),
            schema=HumanizeOutput,
        )
    except NodeCallFailed:
        # §10：人味校订失败 → 跳过，输出改写前版本。
        skipped = HumanizedDraft(
            title=title,
            cover_text=cover_text,
            body=before,
            tags=tags,
            smell_before=report.score,
            smell_after=report.score,
            changes=[],
            fidelity="skipped",
        )
        state["humanized"] = skipped
        state["smell"] = report
        mark_degraded(state, "humanizer", "校订调用失败，输出改前版本")
        return skipped

    merge_usage(state, result.usage)
    out = result.value
    after_report = detect(out.body)
    verdict = check(before, out.body, profile)
    # 标题也可能被改写，数字/专名一样不能丢（评审 M14）
    if verdict.ok and (
        numbers_of(title) != numbers_of(out.title or title)
        or proper_nouns_of(title) != proper_nouns_of(out.title or title)
    ):
        verdict = FidelityResult(False, "标题里的数字或专名变了")

    if not verdict.ok:
        # 回退：正文用改写前的，气味分不变，改动记录留着给人看。
        reverted = HumanizedDraft(
            title=title,
            cover_text=cover_text,
            body=before,
            tags=tags,
            smell_before=report.score,
            smell_after=report.score,
            changes=out.changes,
            fidelity="reverted",
            reverted_reason=verdict.reason,
        )
        state["humanized"] = reverted
        state["smell"] = report
        return reverted

    passed = HumanizedDraft(
        title=out.title or title,
        cover_text=cover_text,
        body=out.body,
        tags=list(out.tags) or tags,
        smell_before=report.score,
        smell_after=after_report.score,
        changes=out.changes,
        fidelity="passed",
    )
    state["humanized"] = passed
    state["smell"] = after_report
    # 后续守门人看的是校订后的定稿。
    state["draft"] = Draft(title=passed.title, cover_text=cover_text, body=passed.body, tags=passed.tags)
    return passed
