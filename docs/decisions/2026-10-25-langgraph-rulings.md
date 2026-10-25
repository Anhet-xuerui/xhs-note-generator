# LangGraph 编排 — 执行裁决（2026-10-25）

- **图状态用运行时 dict，节点仍吃 `RunState`**：LangGraph 的 TypeVar 约束与我们的 TypedDict 对不上，
  强行对齐只会堆满 `cast`。因此 `langgraph_pipeline.py` 顶部关闭 mypy，其余 38 个模块仍然严格。
- **判定放在普通节点（`judge`）而不是条件边里**：条件边只用来选路，写回状态不保证生效——
  第一版把 `decide()` 写在 route 里，结果 `status` 永远是 `running`，被冒烟测试抓到。
- **`SqliteSaver` 换成 `AsyncSqliteSaver`**：异步图 + 同步 saver 会抛 `NotImplementedError`，需要 `aiosqlite`。
- **`--engine` 默认 loop**：手写 loop 更好调试、无第三方依赖；`graph` 用于演示「可回放」。
  两条路径共用同一批节点函数与 `decisions.py` 的纯函数，行为由 3 个一致性用例钉住。
