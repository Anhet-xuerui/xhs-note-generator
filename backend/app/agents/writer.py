"""主笔：做加法——找观点、用素材、搭结构、控节奏（§6/§8）。

两条契约由代码守：

1. 上一轮每条 `Objection` 都要被逐条回应（`objection_index` 必须完整覆盖 0..n-1）；
2. `real_material` 至少要用上 2 条——它是反 AI 味的原料，一条不用就退化成套模板（§2）。

prompt 文本在 `app/prompts/defaults.py`，运行时从 `deps.prompts` 取（D10-1）。
"""

from __future__ import annotations

import json

from pydantic import BaseModel, model_validator

from app.context import build_writer_context
from app.llm.client import Deps
from app.schemas import Draft, WriterResponse
from app.state import RunState, merge_usage


class WriterOutput(BaseModel):
    draft: Draft
    responses: list[WriterResponse]

    @model_validator(mode="before")
    @classmethod
    def _accept_flat_draft(cls, data):
        """真实模型常把 title/body/tags 平铺在顶层；prompt 已要求嵌套，但这里也接住。"""
        if isinstance(data, dict) and "draft" not in data and "title" in data:
            nested = {k: data[k] for k in ("title", "body", "tags", "cover_text") if k in data}
            return {"draft": nested, "responses": data.get("responses", [])}
        return data


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
    # 画像允许只有 1 条素材：目标是「尽量用满」，不能定成达不到的 2 条（评审 I5）。
    target = min(2, len(materials))

    draft: Draft | None = None
    responses: list[WriterResponse] = []

    for attempt in (1, 2):
        result = await deps.llm.structured(
            role="writer",
            system=deps.prompts.text("writer"),
            user=user,
            schema=WriterOutput,
            max_attempts=1,  # 节点层已经重出一次，不再叠加 client 的两次预算（评审 I7）
        )
        merge_usage(state, result.usage)

        out = result.value
        # 第一轮没有异议可回应：模型多给了也丢掉，别让它自己造靶子。
        responses = _validate_responses(out.responses, len(objections)) if objections else []

        hits = material_hits(out.draft.body, materials)
        if hits >= target or attempt == 2:
            draft = out.draft
            break
        user = (
            base_user
            + f"\n\n上一版正文只用到 {hits} 条 real_material。"
            + f"请至少把 {target} 条真实经历原样写进正文，具体到动作、数字或对话。"
        )

    assert draft is not None  # 两次循环里必然赋值
    state["draft"] = draft
    state["writer_responses"] = responses
    return draft, responses
