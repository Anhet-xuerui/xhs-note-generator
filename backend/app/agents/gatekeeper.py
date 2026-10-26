"""守门人：合规是二值的，没有「差不多」（§9/§10）。

顺序固定：正则先筛 → 模型只判两件事（是不是误报、该怎么改）→ 代码算结论。
模型调用失败时**不降级**：宁可 gate_blocked，也不能因为模型挂了就放行合规。

prompt 文本在 `app/prompts/defaults.py`，运行时从 `deps.prompts` 取（D10-1）。
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from app.llm.client import Deps, NodeCallFailed
from app.rules.engine import load_rules, match, match_structure
from app.schemas import GateFinding, GateResult, HumanizedDraft
from app.state import RunState, mark_degraded, merge_usage


class GateJudgement(BaseModel):
    findings: list[GateFinding] = Field(default_factory=list)


def _verdict(findings: list[GateFinding]) -> bool:
    return not any(f.severity == "blocking" and not f.false_positive for f in findings)


def reconcile(inputs: list[GateFinding], judged: list[GateFinding]) -> list[GateFinding]:
    """模型只被允许改 `false_positive` 和 `hint`。

    漏回一条命中（很常见的形状错误）不能等于放行；凭空多出来的命中也不能算数。
    按 (rule_id, span) 对账，缺失的保持 blocking。
    """
    # 键用 (rule_id, matched) 而不是 span：模型常常把句子下标抄错，但会把命中词原样抄回来。
    pending: dict[tuple[str, str], list[GateFinding]] = {}
    for item in judged:
        pending.setdefault((item.rule_id, item.matched), []).append(item)

    merged: list[GateFinding] = []
    for original in inputs:
        bucket = pending.get((original.rule_id, original.matched)) or []
        candidate = bucket.pop(0) if bucket else None
        if candidate is None:
            merged.append(original)
            continue
        merged.append(
            original.model_copy(
                update={
                    "false_positive": candidate.false_positive,
                    "hint": candidate.hint or original.hint,
                }
            )
        )
    return merged


async def run_gatekeeper(state: RunState, deps: Deps, draft: HumanizedDraft) -> GateResult:
    text = f"{draft.title}\n{draft.body}"
    findings = match(text, load_rules()) + match_structure(draft.body, draft.tags)

    if not findings:
        result = GateResult(passed=True, findings=[])
        state["gate"] = result
        return result

    payload = {"text": text, "findings": [f.model_dump() for f in findings]}
    try:
        call = await deps.llm.structured(
            role="gatekeeper",
            system=deps.prompts.text("gatekeeper"),
            model=deps.models.model("gatekeeper"),
            user=json.dumps(payload, ensure_ascii=False),
            schema=GateJudgement,
        )
    except NodeCallFailed:
        # 不降级：正则命中按「未判误报」处理，直接不放行。
        result = GateResult(passed=False, findings=findings)
        state["gate"] = result
        mark_degraded(state, "gatekeeper", "守门人调用失败，按不放行处理")
        return result

    merge_usage(state, call.usage)
    judged = reconcile(findings, call.value.findings)
    result = GateResult(passed=_verdict(judged), findings=judged)
    state["gate"] = result
    return result
