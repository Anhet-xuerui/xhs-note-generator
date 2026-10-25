"""FastAPI 服务：提交 run、订阅 SSE、看快照、导出报告（§10/§11）。

前端是 Vue 3 + Vite 的构建产物（`frontend/dist`），由本服务直接托管——
§10 的「两个服务变一个」就是这里：省掉一个容器，也省掉跨域配置。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.api.bus import RunBus
from app.cli import _run_pipeline, build_deps, new_state, result_payload
from app.config import Settings
from app.graph.decisions import passed, pick_best_round
from app.llm.client import Deps
from app.prompts import (
    ROLES,
    EmptyPrompt,
    PromptError,
    PromptGuardError,
    PromptSet,
    PromptStore,
    PromptTooLong,
    UnknownPromptRole,
)
from app.report.html import render_report
from app.report.trace import build_trace
from app.schemas import PersonaInput

DIST_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"
INDEX = DIST_DIR / "index.html"


class RunRequest(BaseModel):
    persona: PersonaInput
    topic: str = Field(min_length=1)


class OverrideRequest(BaseModel):
    click: bool | None = None
    save: bool | None = None
    read_through: float | None = None


class PromptUpdate(BaseModel):
    text: str


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _prompt_http_error(exc: PromptError) -> HTTPException:
    """store 只懂「为什么拒绝」，HTTP 码在这里映射一次。"""
    if isinstance(exc, UnknownPromptRole):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PromptGuardError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, (EmptyPrompt, PromptTooLong)):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def create_app(
    *,
    deps_factory: Callable[[RunBus, str], Deps] | None = None,
    engine: str = "loop",
    prompt_store: PromptStore | None = None,
) -> FastAPI:
    if deps_factory is None:
        # 生产路径：配置错就启动失败，而不是等第一个 run 才炸（评审 C2）。
        Settings.load()
        deps_factory = lambda bus, run_id: build_deps()  # noqa: E731
    app = FastAPI(title="小红书多角色笔记生成")
    bus = RunBus()
    store = prompt_store or PromptStore()
    runs: dict[str, dict[str, Any]] = {}
    background: set[asyncio.Task] = set()

    @app.get("/prompts")
    async def list_prompts() -> dict[str, Any]:
        return {"roles": list(ROLES), "items": store.items()}

    @app.put("/prompts/{role}")
    async def update_prompt(role: str, payload: PromptUpdate) -> dict[str, Any]:
        try:
            snapshot = store.set(role, payload.text)
        except PromptError as exc:
            raise _prompt_http_error(exc) from exc
        return {
            "role": role,
            "text": snapshot.text(role),
            "sha8": snapshot.sha8(role),
            "source": snapshot.sources[role],
        }

    @app.delete("/prompts/{role}")
    async def reset_prompt(role: str) -> dict[str, Any]:
        try:
            snapshot = store.reset(role)
        except PromptError as exc:
            raise _prompt_http_error(exc) from exc
        return {
            "role": role,
            "text": snapshot.text(role),
            "sha8": snapshot.sha8(role),
            "source": snapshot.sources[role],
        }

    @app.delete("/prompts")
    async def reset_all_prompts() -> dict[str, Any]:
        store.reset()
        return {"roles": list(ROLES), "items": store.items()}

    @app.post("/runs")
    async def create_run(payload: RunRequest) -> dict[str, str]:
        run_id = uuid.uuid4().hex[:12]
        state = new_state(payload.persona, payload.topic)
        state["run_id"] = run_id
        # 快照只在创建时取一次：之后再有人改 prompt，不影响这个 run（D10-3）。
        snapshot = store.snapshot()
        state["prompts"] = snapshot.record()
        runs[run_id] = {"state": state, "prompts": snapshot, "created_at": _now()}
        # 只留最近 100 个 run：本地演示，无界增长没有意义（评审 M18）
        while len(runs) > 100:
            runs.pop(next(iter(runs)))

        async def execute() -> None:
            bus.publish(run_id, {"event": "run_started", "run_id": run_id})
            try:
                # 构造 deps 也要在 try 里：配置缺失必须变成一条 error 事件（评审 C2）。
                deps = deps_factory(bus, run_id)
                deps.event_sink = lambda event: bus.publish(run_id, event)
                # 工厂可能又读了一次 store：强制用创建时那一份，两处不能有两个答案。
                deps.prompts = snapshot
                await _run_pipeline(state, deps, engine)
            except Exception as exc:  # noqa: BLE001 - 任何异常都要变成可读事件
                state["status"] = "failed"
                bus.publish(run_id, {"event": "error", "message": str(exc)})
            finally:
                bus.publish(run_id, {"event": "result", "data": result_payload(state)})
                bus.close(run_id)

        task = asyncio.create_task(execute())
        # 持住引用，避免任务被 GC（asyncio 的经典坑，评审 M18）
        background.add(task)
        task.add_done_callback(background.discard)
        return {"run_id": run_id}

    @app.get("/runs")
    async def list_runs() -> dict[str, Any]:
        items = [
            {
                "run_id": run_id,
                "topic": record["state"]["input"].topic,
                "status": record["state"].get("status"),
                "created_at": record.get("created_at"),
                "prompts_edited": sorted(record["prompts"].edited_roles()),
            }
            for run_id, record in reversed(list(runs.items()))
        ]
        return {"items": items}

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        record = runs.get(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="run 不存在")
        return result_payload(record["state"])

    @app.get("/runs/{run_id}/prompts")
    async def get_run_prompts(run_id: str) -> dict[str, Any]:
        record = runs.get(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="run 不存在")
        snapshot: PromptSet = record["prompts"]
        return {
            "items": [
                {
                    "role": role,
                    "text": snapshot.text(role),
                    "sha8": snapshot.sha8(role),
                    "source": snapshot.sources[role],
                }
                for role in ROLES
            ]
        }

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

        # 改完判定要重算结论并换稿子，否则这个接口等于没做事（评审 I10）。
        state = record["state"]
        history = state.get("draft_history") or []
        if passed(verdict):
            state["status"] = "passed"
            state["best_round"] = None
            if history:
                state["draft"] = history[-1]
        else:
            best = pick_best_round(state["verdicts"])
            state["status"] = "exhausted"
            state["best_round"] = best
            if history:
                state["draft"] = history[best - 1]

        result = result_payload(state)
        bus.publish(run_id, {"event": "verdict_overridden", "verdict": verdict.model_dump()})
        bus.publish(run_id, {"event": "result", "data": result})
        return {
            "ok": True,
            "verdict": verdict.model_dump(),
            "status": state["status"],
            "best_round": state["best_round"],
        }

    @app.get("/runs/{run_id}/report", response_class=HTMLResponse)
    async def report(run_id: str) -> HTMLResponse:
        record = runs.get(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="run 不存在")
        payload = result_payload(record["state"])
        # 节点事件里没有每轮判定卡；用 state 重建一份，报告才是完整的（评审 I2）。
        page = render_report(build_trace(record["state"], payload), payload)
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
