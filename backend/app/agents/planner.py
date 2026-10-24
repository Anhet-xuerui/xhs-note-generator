"""策划：一次出三个角度，自选其一，并强制写清为什么不选另外两个（§7）。

「顺序不该有语义」——取 `angle.chosen` 为真的那个，绝不取 `angles[0]`。
契约违反（0 个或多个 chosen、没写 why_not_others）由代码判定，不交给模型自我宣称；
违反时带错误重出一次（§7 的「重问」路径），再不行才抛出。
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.context import build_planner_context
from app.llm.client import Deps
from app.schemas import Angle
from app.state import RunState, merge_usage

PLANNER_SYSTEM = """你是小红书笔记的策划。

一次给三个**互不相同**的切入角度，然后自己选一个，并写清为什么不选另外两个。
- hook：一句话概括这个角度靠什么抓住人。
- target_emotion：读者被击中的那种情绪，只能取 焦虑/爽感/共鸣/好奇/实用 之一。
- title_candidates：每个角度给 2–3 个标题，标题要具体，不要抽象形容词。
- chosen：三个里**恰好一个**为 true。
- why_not_others：说清另外两个为什么不选（差异不够、太泛、太像广告……），不得留空。
- 三个角度必须真的不同：换的是切入方向，不是换个说法。

只输出 JSON。"""


class AngleSet(BaseModel):
    angles: list[Angle] = Field(min_length=3, max_length=3)


class PlannerContractError(RuntimeError):
    """策划产出违反 §7 的契约。"""


def _validate(payload: AngleSet) -> Angle:
    chosen = [a for a in payload.angles if a.chosen]
    if len(chosen) != 1:
        raise PlannerContractError(f"必须恰好一个角度 chosen=True，实际 {len(chosen)} 个")
    angle = chosen[0]
    if not angle.why_not_others.strip():
        raise PlannerContractError("chosen 的角度必须写清 why_not_others，不得留空")
    return angle


async def run_planner(state: RunState, deps: Deps) -> Angle:
    context = build_planner_context(state)
    base_user = json.dumps(context, ensure_ascii=False)
    user = base_user
    last_error: PlannerContractError | None = None

    for _ in range(2):
        result = await deps.llm.structured(
            role="planner",
            system=PLANNER_SYSTEM,
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
                + "请重出一条：三个角度里恰好一个 chosen=true，且该角度的 why_not_others 非空。"
            )
            continue
        state["angle"] = angle
        return angle

    raise last_error or PlannerContractError("策划未能产出合规角度")
