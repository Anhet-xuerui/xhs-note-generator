"""主笔：做加法——找观点、用素材、搭结构、控节奏（§6/§8）。

两条契约由代码守：

1. 上一轮每条 `Objection` 都要被逐条回应（`objection_index` 必须完整覆盖 0..n-1）；
2. `real_material` 至少要用上 2 条——它是反 AI 味的原料，一条不用就退化成套模板（§2）。
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from app.context import build_writer_context
from app.llm.client import Deps
from app.schemas import Draft, WriterResponse
from app.state import RunState, merge_usage

WRITER_SYSTEM = """你是小红书笔记的主笔。

按给定的约束卡、选定角度和上一轮读者意见写一版完整笔记，输出 title / body / tags。
- 用足 real_material：至少把两条真实经历写进正文，具体到动作、数字、地点或对话，
  不要抽象成「很崩溃」「学到了很多」。
- 语气照 tone；不能碰 cannot_say 里的任何一条。
- body 300–800 字，段落长短不齐，别写排比句，别写「愿你」「其实」这类句式。
- 上一轮每条反对意见都要回应：objection_index 用 0、1、2… 对齐其顺序，
  decision 取 accept（照改）或 reject（不改，但说清为什么读者多虑了）。
- 第一轮没有反对意见时，responses 必须是空数组。

只输出 JSON。"""


class WriterOutput(BaseModel):
    draft: Draft
    responses: list[WriterResponse]


class WriterContractError(RuntimeError):
    """主笔产出违反契约。"""


def material_hits(body: str, materials: list[str]) -> int:
    return sum(1 for m in materials if m[:6] in body)


def _validate_responses(responses: list[WriterResponse], expected: int) -> list[WriterResponse]:
    indexes = [r.objection_index for r in responses]
    if sorted(indexes) != list(range(expected)):
        raise WriterContractError(
            f"objection_index 必须完整覆盖 0..{expected - 1}，实际为 {indexes}"
        )
    return responses


async def run_writer(state: RunState, deps: Deps) -> tuple[Draft, list[WriterResponse]]:
    context = build_writer_context(state)
    base_user = json.dumps(context, ensure_ascii=False)
    user = base_user
    feedback = state.get("feedback_history") or []
    objections = feedback[-1] if feedback else []
    materials = list(state["input"].persona.real_material)

    draft: Draft | None = None
    responses: list[WriterResponse] = []

    for attempt in (1, 2):
        result = await deps.llm.structured(
            role="writer",
            system=WRITER_SYSTEM,
            user=user,
            schema=WriterOutput,
        )
        merge_usage(state, result.usage)

        out = result.value
        # 第一轮没有异议可回应：模型多给了也丢掉，别让它自己造靶子。
        responses = _validate_responses(out.responses, len(objections)) if objections else []

        hits = material_hits(out.draft.body, materials)
        if hits >= 2 or attempt == 2:
            draft = out.draft
            break
        user = (
            base_user
            + f"\n\n上一版正文只用到 {hits} 条 real_material。"
            + "请至少把 2 条真实经历原样写进正文，具体到动作、数字或对话。"
        )

    assert draft is not None  # 两次循环里必然赋值
    state["draft"] = draft
    state["writer_responses"] = responses
    return draft, responses
