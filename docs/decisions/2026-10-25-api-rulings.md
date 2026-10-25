# FastAPI + SSE + 单页前端 — 执行裁决（2026-10-25）

- **前端用无构建单页，不是 Vue 3 + Element Plus（偏离 §13 选型）**：这一版要解决的是「过程可观察」，
  渲染层不需要组件生态；不引 Vite 就不需要 node 构建，`uv run uvicorn ...` 一条命令就能开。
  代价：与规格的技术选型不一致，换 Vue 时只需替换 `app/api/static/index.html`，API 契约不变。
- **事件粒度到节点级，没有 token 级流**：`_step()` 包住每个节点调用，推 `node_start` / `node_end`。
  token 流需要给 `LLMClient.structured` 加流式通道，与「结构化输出 + 校验重问」冲突，留给后续。
- **run 存在进程内存里**：`runs: dict` + `RunBus`。进程重启会丢 run（报告仍可通过 JSONL 复现）。
  规格里 `SqliteSaver` 属于 D5 编排那一层，等 LangGraph 化时一起补。
- **`override-verdict` 直接改内存里的最后一张判定卡并广播事件**：规格要求「写 state → 从 checkpoint 恢复」，
  当前没有 checkpoint，退回直接改；等 D5 有了 checkpointer 再切。
- **修掉一个真 bug**：`RunBus.subscribe` 在回放历史时遇到 `done` 不返回，导致已结束 run 的 SSE 连接挂死——
  由 `test_bus_replays_history_before_live_events` 抓出来。
