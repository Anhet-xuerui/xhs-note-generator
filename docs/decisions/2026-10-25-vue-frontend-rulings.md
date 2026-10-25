# 前端迁移到 Vue 3 — 执行裁决（2026-10-25）

- **Vue 3 + TS + Vite + Pinia + Element Plus**（对齐 §13），替换掉上一版无构建单页。
  后端 `create_app` 改为托管 `frontend/dist`，`/assets` 用 `StaticFiles` 挂载；未构建时 `/` 返回 503 并提示命令。
- **状态收敛到 `src/stores/run.ts`**：组件只读 Pinia store，SSE 连接由 store 持有并在结束时关闭。
- **没有引 ECharts / jsdiff / markdown-it**（§13 列了）：当前页面不需要图表与内联 diff，
  正文按段落渲染即可。这三样留到「稿子 diff / 评测图表」那一版再加，避免为不存在的需求装依赖。
- **构建产物不入库**：`frontend/dist` 与 `node_modules` 已 gitignore；`pnpm-lock.yaml` 入库。
  代价：新克隆要先 `pnpm build`，README 已写进命令里。
- **pnpm 11 的构建脚本许可**：`esbuild` 需要 postinstall，否则 vite 跑不起来；配置写在 `pnpm-workspace.yaml`
  的 `allowBuilds`（pnpm 11 的新位置，`package.json` 的 `pnpm` 字段已不再读取）。
- **修一个兜底**：真实模型偶尔返回空封面，`run_cover` 现在回落到标题前 12 字（§10 的封面兜底）。
