"""进程内事件总线：一次 run 一个频道，历史可回放、可多订阅者。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any


class RunBus:
    def __init__(self) -> None:
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        self._history.setdefault(run_id, []).append(event)
        for queue in self._subscribers.get(run_id, []):
            queue.put_nowait(event)

    def history(self, run_id: str) -> list[dict[str, Any]]:
        return list(self._history.get(run_id, []))

    def close(self, run_id: str) -> None:
        for queue in self._subscribers.get(run_id, []):
            queue.put_nowait({"event": "done"})

    async def subscribe(self, run_id: str) -> AsyncIterator[dict[str, Any]]:
        """先补历史再收实时——断线重连也能看到完整过程。"""
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(run_id, []).append(queue)
        try:
            for event in self.history(run_id):
                yield event
                if event.get("event") == "done":
                    return
            while True:
                event = await queue.get()
                yield event
                if event.get("event") == "done":
                    return
        finally:
            self._subscribers.get(run_id, []).remove(queue)
