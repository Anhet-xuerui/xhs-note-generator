"""封面：只看标题与首句，牺牲信息量换点击（§6）。

它是独立角色，因为「三秒抓眼」和写正文是两种手艺：看到全篇会下意识去概括，写出来的就不是封面了。

prompt 文本在 `app/prompts/defaults.py`，运行时从 `deps.prompts` 取（D10-1）。
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from app.context import build_cover_context
from app.llm.client import Deps, NodeCallFailed
from app.state import RunState, mark_degraded, merge_usage

MAX_COVER_CHARS = 12


class CoverText(BaseModel):
    cover_text: str


async def run_cover(state: RunState, deps: Deps) -> str:
    context = build_cover_context(state)
    draft = state.get("draft")
    try:
        result = await deps.llm.structured(
            role="cover",
            system=deps.prompts.text("cover"),
            user=json.dumps(context, ensure_ascii=False),
            schema=CoverText,
        )
    except NodeCallFailed:
        # §10：封面失败用兜底值，绝不能因此丢掉已经通过读者的稿子。
        fallback = (draft.title if draft is not None else "")[:MAX_COVER_CHARS]
        if draft is not None:
            draft.cover_text = fallback
        mark_degraded(state, "cover", "封面调用失败，回落标题前 12 字")
        return fallback

    merge_usage(state, result.usage)
    text = result.value.cover_text.strip()[:MAX_COVER_CHARS]
    if not text:
        # §10 的兜底：封面失败/空值就取标题前 12 字，别让界面空着一块。
        text = (draft.title if draft is not None else "")[:MAX_COVER_CHARS]
    if draft is not None:
        draft.cover_text = text
    return text
