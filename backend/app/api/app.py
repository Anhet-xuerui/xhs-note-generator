"""FastAPI 服务：提交 run、订阅 SSE、看快照、导出报告（§10/§11）。

前端是 Vue 3 + Vite 的构建产物（`frontend/dist`），由本服务直接托管——
§10 的「两个服务变一个」就是这里：省掉一个容器，也省掉跨域配置。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.api.bus import RunBus
from app.cli import _run_pipeline, build_deps, new_state, result_payload
from app.config import Settings
from app.llm.client import Deps
from app.report.html import render_report
from app.schemas import PersonaInput

DIST_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"
INDEX = DIST_DIR / "index.html"


class RunRequest(BaseModel):
    persona: PersonaInput
    topic: str


class OverrideRequest(BaseModel):
    click: bool | None = None
    save: bool | None = None
    read_through: float | None = None


def create_app(
    *,
    deps_factory: Callable[[RunBus, str], Deps] | None = None,
    engine: str = "loop",
) -> FastAPI:
    if deps_factory is None:
        # 生产路径：配置错就启动失败，而不是等第一个 run 才炸（评审 C2）。
        Settings.load()
        deps_factory = lambda bus, run_id: build_deps()  # noqa: E731
    app = FastAPI(title="小红书多角色笔记生成")
    bus = RunBus()
    runs: dict[str, dict[str, Any]] = {}

    @app.post("/runs")
    async def create_run(payload: RunRequest) -> dict[str, str]:
        run_id = uuid.uuid4().hex[:12]
        state = new_state(payload.persona, payload.topic)
        state["run_id"] = run_id
        runs[run_id] = {"state": state}

        async def execute() -> None:
            bus.publish(run_id, {"event": "run_started", "run_id": run_id})
            try:
                # 构造 deps 也要在 try 里：配置缺失必须变成一条 error 事件（评审 C2）。
                deps = deps_factory(bus, run_id)
                deps.event_sink = lambda event: bus.publish(run_id, event)
                await _run_pipeline(state, deps, engine)
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

    def require_run(run_id: str) -> None:
        if run_id not in runs:
            raise HTTPException(status_code=404, detail="run 不存在")

    # FastAPI 0.140+ 的 SSE 编码发生在路由层：必须用 response_class 声明 + 直接 yield，
    # 把 EventSourceResponse(...) 当返回值会交给 StreamingResponse，然后 chunk.encode() 炸掉（评审 C1）。
    @app.get(
        "/runs/{run_id}/events",
        response_class=EventSourceResponse,
        dependencies=[Depends(require_run)],
    )
    async def events(run_id: str):
        async for event in bus.subscribe(run_id):
            yield ServerSentEvent(data=event, event=event.get("event", "message"))

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

    if (DIST_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/")
    async def index():
        if not INDEX.exists():
            return JSONResponse(
                status_code=503,
                content={"detail": "前端还没构建：cd frontend && pnpm install && pnpm build"},
            )
        return FileResponse(INDEX)

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    return app
