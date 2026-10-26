# 交接文档（2026-10-25）

给下一个会话用的。读完这一页，你应该能在 10 分钟内把项目跑起来、知道它现在是什么状态、以及下一步该做什么。

---

## 0. 一分钟状态

| 项 | 值 |
|---|---|
| 仓库 | 本仓库根目录（`XHS_Note_Generator`），分支 `main`（D10、D11 已 `--no-ff` 合入），工作区干净 |
| 测试 | **223 passed**，1 deselected（live 用例需真 API，默认跳过），离线约 4 秒 |
| 质量门 | `ruff` 0、`mypy` 0（46 个模块）、`xhs-invariants` 6/6、前端 `vue-tsc` 0 |
| 服务 | 用第 1 节的命令起；`/health` 返回 `{"ok":true}` |
| 前端 | `frontend/dist` 已构建；`backend/.env` 已配好（不入库） |

**注意**：服务是会话里的后台进程，应用重启就没了，用第 1 节的命令重开。

---

## 1. 怎么跑起来

```bash
cd backend
uv run uvicorn app.api.app:create_app --factory --host 127.0.0.1 --port 8000
# 浏览器打开 http://127.0.0.1:8000
```

改了前端再重建：

```bash
cd frontend && pnpm build          # 产物 dist 由后端托管
cd frontend && pnpm dev            # 或者分离开发：5173 代理到 8000
```

命令行跑一次（不经过界面）：

```bash
cd backend
uv run python -m app.cli run --persona scripts/personas/p01.json \
  --topic "租房第一年我终于搞清楚的事" --trace-out data/traces/r1.jsonl
uv run python -m app.cli report --trace data/traces/r1.jsonl --out data/report.html
uv run python -m app.cli run --persona scripts/personas/p01.json --topic "…" --engine graph   # LangGraph + checkpoint
```

全量验证（不花钱）：

```bash
cd backend && uv run pytest -q && uv run ruff check app tests && uv run mypy app
cd .. && python scripts/check_invariants.py --root .
cd frontend && pnpm typecheck
```

`uv` 的缓存在受限沙箱里会因目录不可写而失败；此时直接用 `backend/.venv/Scripts/python.exe -m pytest` 等价。

一次真实 run：**30–60 秒、0.03–0.06 元**（写作用 DeepSeek、读者用 GLM，走本机 8788 网关）。

---

## 2. 这是什么

七角色讨论循环产出小红书笔记：画像官 → 策划 → 主笔 → 读者 →（封面 / 人味校订 / 守门人）。
项目是给 AI-Agent 岗位的作品集，所以**设计决策与结论的诚实度**和代码同等重要。

规格（唯一真相源）：`docs/superpowers/specs/2026-10-23-xhs-multiagent-design.md`（627 行，中文）
读者入口：`README.md`、`docs/a4-decisions.md`（一页纸投屏用）

---

## 3. 代码地图

```
backend/app/
├── agents/         7 个角色：profile / planner / writer / reader / cover / humanize / gatekeeper
├── prompts/        defaults.py（七段默认文本）· set.py（run 快照）· store.py（覆盖层 + 读者守卫）
├── models/         set.py（七角色模型快照）· store.py（data/models.json 覆盖层）
├── context.py      信息隔离唯一实现处（按白名单裁剪，三条隔离有单测 + AST 二次检查）
├── graph/          loop.py（手写循环）· decisions.py（纯函数判定）· langgraph_pipeline.py（图编排）
├── humanize/       smell.py（六类 AI 味规则）· fidelity.py（数字/专名/锚点/长度四条）
├── rules/          rules.yaml（违禁词）+ engine.py（正则先筛）
├── evaluation/     stats（手写 τ/ρ/κ/bootstrap）· judge · corpus · runners · report
├── report/         trace.py（JSONL）· html.py（单文件报告）
├── api/            app.py（/runs、SSE、报告、改判）· bus.py（进程内事件总线）
└── llm/client.py   结构化调用：围栏剥离 / 校验失败重问 / 5xx 重试 / 逐调用计费
frontend/src/       Vue 3 + TS + Pinia + Element Plus：stores/run.ts 唯一状态源
eval/               data/topics.json（已入库）+ out/（产物，gitignore）
docs/decisions/     每个阶段的裁决与取舍（D1–D3 / D4 / D9 / API / LangGraph / Vue）
docs/samples/       真实运行报告 + 五次重复的评测报告与逐轮指标
```

---

## 4. 五条不能动的设计（改了就不成立）

1. **信息隔离**：读者看不到 `real_material`；策划看不到成稿；主笔看不到规则库全文。由 `context.py` 唯一实现，`xhs-invariants` C3 会静态再查一遍。
2. **读者换厂商**：`READER_*` 缺失或与主笔同 base_url+模型时启动即报错；client 缓存按 `(base_url, api_key)`。
3. **判定卡冻结**：`Verdict` 7 字段、`Objection` 4 字段，`xhs-invariants` C1/C2 锁死；通过条件硬编码在 `decisions.passed()`。
4. **规则先筛、模型后改**：AI 味与违禁词都是程序化规则，模型只判误报 + 给改写建议；守门人**不降级**（模型失败 = `gate_blocked`）。
5. **成本不许估算**：`NodeCallFailed` 带已花掉的 usage，缺 `usage` 直接报错，不按 0 计。

---

## 5. 评测：哪些数字能引用，哪些不能

五次重复（请求 10 主题，实际 7–8 个产出成稿）：

| 指标 | 均值 [95% CI] | 能不能当结论 |
|---|---|---|
| E1 绝对打分正确率 | 42% [34, 51] | ✅ 明确低于 80% |
| E1 **两两比较**正确率 | **96%** [95, 98] | ✅ 与绝对打分不重叠 |
| E2 click κ / save κ | 0.68 [0.52, 0.84] / 0.69 [0.58, 0.79] | ⚠️ 均值过线、下界擦线 |
| E2 score ρ | 0.80 [0.75, 0.85] | ✅ |
| E3 A vs B | A 胜 26% [13, 36] → **B 胜 74%** | ✅ |
| E3 B vs C / A vs C | 63% [43, 80] / 61% [46, 81] | ⚠️ 跨 50%，未达显著 |
| E3 B tokens / 成本 | 47.7k [38.4k, 54.5k] / 0.20 元 | ✅ |

**三条已确立**：判定卡该用两两比较（96% vs 42%）；讨论循环打赢裸模型（A 胜率上界 36%）；ρ 稳定。
**两条不能写**：C 组「更差」方向一致但未达显著；κ 换批样本可能掉到 0.6 以下。
**全部作废**：早期所有「通过率 X%→Y%」的数字——它们建立在只有 42% 排序能力的绝对判定卡上。README 里已移除。

报告：`docs/samples/eval-report-5repeats.md`、逐轮指标 `docs/samples/pairwise-repeat-*.json`。

---

## 6. 这一路踩过并修掉的坑（都带回归测试）

- **SSE 发不出事件**：FastAPI 0.140+ 的 `EventSourceResponse` 只是 marker class，必须 `response_class=` 声明 + 直接 `yield`；否则 `chunk.encode()` 炸掉，界面永远转圈。
- **run 结束后 SSE 挂死**：`RunBus.close()` 只推订阅队列、不写历史，晚连上来的订阅者看不到 `done`。
- **配置缺失卡死**：`deps_factory` 曾在 `try` 之外，缺 `.env` 时 run 永久 `running`；现在启动即校验 + 失败落 error 事件。
- **封面 5xx 丢稿**：封面失败会丢掉已通过读者的稿子并跳过守门人；现在回落标题前 12 字。
- **守门人漏判**：模型漏回命中项曾被当成放行；现在按 `(rule_id, matched)` 对账，漏回=保持 blocking。
- **LangGraph 状态不回写**：`ainvoke` 返回新 dict，API 快照曾是空的；现在 `state.update(result)`。
- **保真校验过严**：锚点要求全部出现在改写稿里，而主笔只用 2 条素材 → 必定回退；现在只约束「原文里出现过的锚点」。
- **敏感性检查是恒真式**：整体缩放不改变排序；现在逐维 ±30% 扰动。
- 其他：dry-run 覆盖真实报告、`pytest-of-*` 临时目录入库、`jieba.cache`（9MB）入库、`eval/` 数据被 `data/` 规则吞掉导致评测不可复现。

更细的裁决记录在 `docs/decisions/`。

---

## 7. 未完成

**A. D10 已完成（节点可见 + prompt 可改）**
规格：`docs/superpowers/specs/2026-10-25-node-inspector-and-editable-prompts-design.md`
裁决：`docs/decisions/2026-10-25-node-inspector-rulings.md`

- 七个节点的产物、耗时、花费、是否降级都随 `node_end` 事件下发；点节点开抽屉看「产物 / 本轮 prompt / 编辑下一版」。
- 中间栏底部常驻「角色 prompt」列表：**不用先跑**，点任一角色就能改它的 prompt；跑过之后同一列表按轮次补上产物。
- prompt 三层：默认（代码）→ 覆盖（`backend/data/prompts.json`）→ 每次 run 的快照（进报告与 `--trace-out`）。
- 整条重跑 + 顶部可切回历史 run；`cli eval` 永远用默认 prompt，存在覆盖时启动打印警告。
- **已知限制**：run 与节点产物只在进程内存，重启即丢（能留存的是报告 HTML 与 CLI JSONL）；`--engine graph` 不发节点事件（API 默认 loop，界面不受影响）。

**A2. D11 已完成（七个角色各配各的模型）**
规格：`docs/superpowers/specs/2026-10-26-per-role-models-design.md`
裁决：`docs/decisions/2026-10-26-model-selection-rulings.md`

- 「角色 · 模型 · prompt」一张表：每个角色一个下拉（`/models/available` 返回网关 19 个 + 价格表），即改即存；覆盖落在 `backend/data/models.json`，每次 run 快照进报告。
- **允许读者与主笔同模型**：不再启动拦截；`meta.reader_independent=false` 时界面与报告都标「非独立评审」。
- **允许未登记价格的模型**：token 照记，成本显示 `≥ ¥x（N 次未计价）`，绝不写 0。
- `cli eval` 仍固定 `.env` 默认模型，有覆盖时启动打印警告。

**B. 评审里没修的 Minor**
- 前端没有测试，`build` 只跑 `vite build`，没接 `vue-tsc`（`tsconfig.strict` 实际不生效）
- `reading_scene` 仍无调用方（读者拿不到「刷手机场景」）
- 读者 prompt 同时带 `body` 与 `sentences`，约多一倍 token
- `drop_at_sentence` / `sentence_index` 未对句子总数校验
- 报告没有跨 run 的评测对比页；E4 人工盲评未做
- κ/ρ 的区间仍宽，样本量需要再上一个量级

**C. 明确不做（用户已排除）**
docker 一键启动、5 分钟录屏。

---

## 8. 这个项目的工作方式（延续它，别另起一套）

- **每块一个分支**，合并回 `main` 用 `--no-ff`；提交信息写清「修了评审哪一条」。
- **TDD**：先写会失败的用例，再实现；测试全部离线（`httpx2.MockTransport` + `FakeLLM`），不花钱。
- **裁决要落盘**：任何偏离规格的决定写进 `docs/decisions/`，包括「为什么这样、代价是什么」。
- **每次改动后跑**：`pytest -q`、`ruff`、`mypy`、`check_invariants.py` 四件套。
- **结论要能自证**：不确定的数字不写进 README；写了的必须能在仓库里找到产物。

---

## 9. 环境事实（省得重新踩）

- Windows；路径含中文，`git`/`uv`/`pnpm` 都在 PATH；node 24、pnpm 11（`pnpm-workspace.yaml` 里 `allowBuilds: esbuild/vue-demi`，否则 vite 跑不起来）。
- Python 3.11 + `uv`；依赖：fastapi 0.162（原生 SSE）、langgraph 1.2 + `langgraph-checkpoint-sqlite` + `aiosqlite`、openai 3.x（传输层是 `httpx2` 不是 httpx）。
- 本机网关 `http://127.0.0.1:8788/v1`，19 个模型；`.env` 里读者配的是 `glm-5.3-flash`，写作 `deepseek-v4.1-flash`。
- `.env` 不入库；`PRICES` 里必须登记 reader 模型，否则启动报 `UnknownModelPrice`（GLM 的价格是保守估值，未核实）。
- 后台任务会随 DSH 应用重启消失；跑长评测用 `--resume`（每轮落 `repeat-N.json`）。

---

## 10. 新会话第一句话可以这样说

> 读 `docs/HANDOFF.md` 和 `docs/superpowers/specs/2026-10-23-xhs-multiagent-design.md`，然后继续做「节点 prompt 前端可见可改 + UI 美化」这件事。先跟我确认使用场景，再给方案。

如果只想先看看现状：`cd backend && uv run pytest -q`，再打开 `http://127.0.0.1:8000`（服务没起来就先跑第 1 节的命令）。
