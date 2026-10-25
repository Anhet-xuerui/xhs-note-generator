"""封面：只看标题与首句，牺牲信息量换点击（§6）。

它是独立角色，因为「三秒抓眼」和写正文是两种手艺：看到全篇会下意识去概括，写出来的就不是封面了。
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from app.context import build_cover_context
from app.llm.client import Deps
from app.state import RunState, merge_usage

MAX_COVER_CHARS = 12

COVER_SYSTEM = """你是小红书笔记的封面文案写手。

你只看到标题和正文的第一句——这是故意的：封面要的是三秒抓眼，不是概括全文。
- 12 个字以内（含标点），越短越好。
- 可以牺牲信息量换取好奇心、冲突感或具体数字。
- 口语，像人随手写的，不要广告腔、不要惊叹号堆砌。
- 只输出 JSON：{"cover_text": "..."}"""


class CoverText(BaseModel):
    cover_text: str


async def run_cover(state: RunState, deps: Deps) -> str:
    context = build_cover_context(state)
    result = await deps.llm.structured(
        role="cover",
        system=COVER_SYSTEM,
        user=json.dumps(context, ensure_ascii=False),
        schema=CoverText,
    )
    merge_usage(state, result.usage)

    draft = state.get("draft")
    text = result.value.cover_text.strip()[:MAX_COVER_CHARS]
    if not text:
        # §10 的兜底：封面失败/空值就取标题前 12 字，别让界面空着一块。
        text = (draft.title if draft is not None else "")[:MAX_COVER_CHARS]
    if draft is not None:
        draft.cover_text = text
    return text
