"""FastAPI 服务：提交 run、订阅 SSE、看快照、导出报告（§10/§11）。

前端只有一个静态页（无构建步骤）：这一版的目的是「过程可观察」，
渲染层用不着 Vue 的组件生态；换 Vue 是后续的事，不影响 API 契约。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel

from app.api.bus import RunBus
from app.cli import build_deps, new_state, result_payload
from app.graph.loop import finish_draft, run_loop
from app.llm.client import Deps
from app.report.html import render_report
from app.schemas import PersonaInput

STATIC_DIR = Path(__file__).with_name("static")


class RunRequest(BaseModel):
    persona: PersonaInput
    topic: str


class OverrideRequest(BaseModel):
    click: bool | None = None
    save: bool | None = None
    read_through: float | None = None


def create_app(
    *,
    deps_factory: Callable[[RunBus, str], Deps] = lambda bus, run_id: build_deps(),
) -> FastAPI:
    app = FastAPI(title="小红书多角色笔记生成")
    bus = RunBus()
    runs: dict[str, dict[str, Any]] = {}

    @app.post("/runs")
    async def create_run(payload: RunRequest) -> dict[str, str]:
        run_id = uuid.uuid4().hex[:12]
        state = new_state(payload.persona, payload.topic)
        state["run_id"] = run_id
        runs[run_id] = {"state": state, "status": "running", "events": bus}

        async def execute() -> None:
            deps = deps_factory(bus, run_id)
            bus.publish(run_id, {"event": "run_started", "run_id": run_id})
            try:
                await finish_draft(await run_loop(state, deps), deps)
            except Exception as exc:  # noqa: BLE001 - 任何异常都要变成可读事件
                state["status"] = "failed"
                bus.publish(run_id, {"event": "error", "message": str(exc)})
            finally:
                bus.publish(run_id, {"event": "result", "data": result_payload(state)})
                bus.close(run_id)

        asyncio.create_task(execute())
        return {"run_id": run_id}

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        record = runs.get(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="run 不存在")
        return result_payload(record["state"])

    @app.get("/runs/{run_id}/events")
    async def events(run_id: str) -> EventSourceResponse:
        if run_id not in runs:
            raise HTTPException(status_code=404, detail="run 不存在")

        async def stream():
            async for event in bus.subscribe(run_id):
                yield ServerSentEvent(data=event, event=event.get("event", "message"))

        return EventSourceResponse(stream())

    @app.post("/runs/{run_id}/override-verdict")
    async def override(run_id: str, payload: OverrideRequest) -> dict[str, Any]:
        record = runs.get(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="run 不存在")
        verdicts = record["state"].get("verdicts") or []
        if not verdicts:
            raise HTTPException(status_code=409, detail="还没有判定卡可改")
        verdict = verdicts[-1]
        for field, value in payload.model_dump(exclude_none=True).items():
            setattr(verdict, field, value)
        bus.publish(run_id, {"event": "verdict_overridden", "verdict": verdict.model_dump()})
        return {"ok": True, "verdict": verdict.model_dump()}

    @app.get("/runs/{run_id}/report", response_class=HTMLResponse)
    async def report(run_id: str) -> HTMLResponse:
        record = runs.get(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="run 不存在")
        page = render_report(bus.history(run_id), result_payload(record["state"]))
        return HTMLResponse(page)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    return app


def _dumps(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False)
