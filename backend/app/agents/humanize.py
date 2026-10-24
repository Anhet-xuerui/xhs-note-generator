"""人味校订：只做减法——删抽象词、拆长句、把形容词换成动作和数字（§8）。

三个不可让步的点：
1. 输入必须是**检测报告**而不是一句「写得更自然」；
2. 改完必须过保真校验，违反就整篇回退（不重试，重试只是烧钱）；
3. 回退时正文给改写前的版本，但 `changes` 保留——「想改但被拦下了什么」本身是证据。
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.humanize.fidelity import check
from app.humanize.smell import detect
from app.llm.client import Deps, NodeCallFailed
from app.schemas import ChangeLog, Draft, HumanizedDraft
from app.state import RunState, merge_usage

HUMANIZE_SYSTEM = """你是人味校订，负责给一篇已经成型的笔记做减法。

你拿到的是一份 AI 味检测报告——只按报告里的命中项改，不许自由发挥：
- 删抽象名词，换成具体的动作、数字、对话或场景。
- 拆掉长句和排比，让段落长短不齐。
- 把「其实/愿你/不是…而是…」这类句式改成正常说话。
- 补不出来的具体细节就不要编：宁可删掉那句。

硬约束（违反会被整篇回退）：
- 数字、专名、真实经历必须原样保留，一个都不能少。
- 全文长度变化控制在 ±15%。
- 只做删改与替换，不新增事实。

输出 JSON：{"title": "...", "body": "...", "tags": ["..."],
"changes": [{"before": "改前片段", "after": "改后片段", "category": "命中的类别", "reason": "为什么这么改"}]}"""


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
            system=HUMANIZE_SYSTEM,
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
        return skipped

    merge_usage(state, result.usage)
    out = result.value
    after_report = detect(out.body)
    verdict = check(before, out.body, profile)

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
