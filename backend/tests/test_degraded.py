"""降级必须留痕（D10-12）。

四个节点会在内部吞掉 `NodeCallFailed` 并给兜底产物；如果状态里不留痕，
界面就会把「读者挂了」显示成「完成」，产物还是一张写着「按未通过处理」的判定卡。
"""

from __future__ import annotations

from app.agents.cover import run_cover
from app.agents.gatekeeper import run_gatekeeper
from app.agents.humanize import run_humanize
from app.agents.reader import run_reader
from app.llm.client import NodeCallFailed
from app.schemas import Draft, HumanizedDraft, Usage
from tests.helpers import deps_with, make_state


def _failure(role: str) -> NodeCallFailed:
    return NodeCallFailed(role, 2, RuntimeError("上游 500"), Usage(cost_cny=0.01))


async def test_reader_failure_is_marked_degraded() -> None:
    state = make_state()
    state["round"] = 1
    state["draft"] = Draft(title="标题", body="正文。", tags=[])

    verdict = await run_reader(state, deps_with(_failure("reader")))

    assert verdict.click is False
    assert state["degraded_nodes"] == [
        {"node": "reader", "round": 1, "reason": "读者调用失败，按未通过处理"}
    ]


async def test_cover_failure_falls_back_and_is_marked_degraded() -> None:
    state = make_state()
    state["round"] = 1
    state["draft"] = Draft(title="中介不会告诉你的三件事", body="第一句。", tags=[])

    text = await run_cover(state, deps_with(_failure("cover")))

    assert text == "中介不会告诉你的三件事"[:12]
    assert state["degraded_nodes"][0]["node"] == "cover"


async def test_humanize_failure_is_marked_degraded() -> None:
    state = make_state()
    state["round"] = 1
    state["draft"] = Draft(title="标题", body="这是一段正文。", tags=[])

    # hints 非空会跳过「没有命中就不改」的早退，直接走模型调用 → 失败 → 兜底
    humanized = await run_humanize(state, deps_with(_failure("humanizer")), hints=[{"rule_id": "x"}])

    assert humanized.fidelity == "skipped"
    assert state["degraded_nodes"][0]["node"] == "humanizer"


async def test_gatekeeper_failure_is_marked_degraded_and_blocks() -> None:
    state = make_state()
    state["round"] = 1
    draft = HumanizedDraft(
        title="标题",
        body="最后我发现押金根本要不回来。",
        tags=["租房"],
        smell_before=40,
        smell_after=20,
        fidelity="passed",
    )

    result = await run_gatekeeper(state, deps_with(_failure("gatekeeper")), draft)

    assert result.passed is False
    assert state["degraded_nodes"][0]["node"] == "gatekeeper"
