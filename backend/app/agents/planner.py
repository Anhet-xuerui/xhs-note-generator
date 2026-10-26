"""策划：一次出三个角度，自选其一，并强制写清为什么不选另外两个（§7）。

「顺序不该有语义」——取 `angle.chosen` 为真的那个，绝不取 `angles[0]`。
契约违反（0 个或多个 chosen、没写 why_not_others）由代码判定，不交给模型自我宣称；
违反时带错误重出一次（§7 的「重问」路径），再不行才抛出。

prompt 文本在 `app/prompts/defaults.py`，运行时从 `deps.prompts` 取（D10-1）。
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.context import build_planner_context
from app.llm.client import Deps
from app.schemas import Angle
from app.state import RunState, merge_usage


class AngleSet(BaseModel):
    angles: list[Angle] = Field(min_length=3, max_length=3)


class PlannerContractError(RuntimeError):
    """策划产出违反 §7 的契约。"""


def _validate(payload: AngleSet) -> Angle:
    chosen = [a for a in payload.angles if a.chosen]
    if len(chosen) != 1:
        raise PlannerContractError(f"必须恰好一个角度 chosen=True，实际 {len(chosen)} 个")
    # 真实模型把「为什么不选另外两个」写在**落选**的角度上（各自说明落选理由），
    # 这只是一种更自然的写法，不该判违约；契约只要求每条都写了理由。
    for index, angle in enumerate(payload.angles):
        if not angle.why_not_others.strip():
            raise PlannerContractError(f"第 {index} 个角度没有写 why_not_others")
    return chosen[0]


async def run_planner(state: RunState, deps: Deps) -> Angle:
    context = build_planner_context(state)
    base_user = json.dumps(context, ensure_ascii=False)
    user = base_user
    last_error: PlannerContractError | None = None

    for _ in range(2):
        result = await deps.llm.structured(
            role="planner",
            system=deps.prompts.text("planner"),
            model=deps.models.model("planner"),
            user=user,
            schema=AngleSet,
            max_attempts=1,  # 节点层已重出一次（评审 I7）
        )
        merge_usage(state, result.usage)
        try:
            angle = _validate(result.value)
        except PlannerContractError as exc:
            last_error = exc
            user = (
                base_user
                + f"\n\n上一次的输出违反了契约：{exc}。"
                + "请重出一条：三个角度里恰好一个 chosen=true，且每个角度的 why_not_others 都非空。"
            )
            continue
        state["angle"] = angle
        return angle

    raise last_error or PlannerContractError("策划未能产出合规角度")
