# D10 设计：节点可见 + 节点 prompt 可改

状态：草案（等你过目；批准前不动代码）
日期：2026-10-25
前置：`docs/superpowers/specs/2026-10-23-xhs-multiagent-design.md`（唯一真相源，本文件不重述它已定的规则）

---

## 1. 这是什么

把七个角色各自的「**吃了哪一版 prompt、产出了什么**」摆到前端；在界面上就地改 prompt，然后**整条从头重跑**。

用户原话（本次需求的唯一来源）：

> 把每个节点渲染到前端，生成的文章不满意，可以直接在前端修改 prompt

界面美化限定为：**沿用 Element Plus，只优化排版、留白、信息层级**，不换组件库、不做视觉重设计。

---

## 2. 为什么现在做

两个理由，一个是功能的，一个是诚实度的。

**功能上的缺口**：现在前端只有一串节点名。

- 过程只剩 `node_start` / `node_end` 两个事件（`backend/app/graph/loop.py:21-29`），`TimelinePanel.vue` 渲染出来的就是「profile 开始 / profile 完成 / 第 1 轮」。
- 七个角色各自产出的约束卡、三个角度、判定卡、人味校订报告、合规命中，全都只在最后落成一屏稿子（`DraftPanel.vue`），中间过程不可见。
- 想调 prompt 只能改 Python 源码再重启进程（`agents/*.py` 里的 7 个模块级常量）。

**诚实度上的缺口**：原设计 §11 承诺的中栏是「每个角色一张卡片，卡片内容是结构化产物」，实际一个都没落地。这不是审美问题，是**作品集里承诺过的东西没做到**。

---

## 3. 目标 / 非目标 / 反目标

### 目标

- **G1** 七个节点的产物在界面上可见：点一个节点，能看到它这一步的产物、耗时、花费、用的哪版 prompt，以及**可跳到上游节点**看它吃的是什么（上游产物就是它的输入，见 N7）。
- **G2** 七个节点的 system prompt 可在界面上改、保存、恢复默认；保存后立刻用于下一次 run。
- **G3** 每次 run 自带 prompt 快照：事后查这个 run，看到的一定是它**当时**用的文本，不受后续编辑影响。
- **G4** 改完 prompt 一键整条重跑，前后两版稿子/判定能对照着看（不要求自动 diff，同一页面能来回切即可）。
- **G5** 界面整洁度达到「能拿去投屏」：信息分层清楚、留白一致、主次分明。

### 非目标

- **N1** 不做运行中热改、不做「从某个节点往下重跑」。用户已确认：整条从头重跑。原因是重跑语义会牵动轮次上限（C4）与判定卡（C1），收益不抵成本。
- **N2** 不做多套 prompt 预设的管理、版本历史、A/B 对比页。一次只维护「当前这一版」+「默认版」。
- **N3** 不允许编辑 user 消息（即 `context.py` 产出的那份 JSON）。
- **N4** 不做 token 流式输出（现在是等节点整块返回）。
- **N5** 不改判 `Verdict` 结构、不动轮次上限、不动通过条件。
- **N6** 不重跑 D9 评测来验证 prompt 编辑功能（prompt 一改，D9 的结论本来就不再适用于那次 run，见 §12 风险 1）。
- **N7** 不展示每个节点**收到的输入原文**。抽屉里给的是产物 + 本轮 prompt + 上游节点跳转；输入是什么，由上游产物和 `context.py` 的 builder 能推出来。真要加，最省的做法是让 agent 把 context 塞进同一条 `node_end`（每个 agent 多一行），留到下一步。
- **N8** `--engine graph`（LangGraph 编排）**不发**节点事件：`langgraph_pipeline.py` 直接调 `run_*`，绕过 `_step`。API 的默认引擎是 `loop`（`create_app(engine="loop")`），界面不受影响；CLI 用 graph 时没有时间线，只有最终结果照旧。要支持再单开一轮。
- **N9** 不做 run 落盘 / 历史持久化。API 的 run 存在进程内存（`docs/decisions/2026-10-25-api-rulings.md` 已定），重启即丢；可留存的是**报告 HTML**（浏览器另存）与 CLI `--trace-out` 的 JSONL。

### 反目标（做成了也算失败）

- **A1** 让「改 prompt」变成刷分工具：界面诱导用户为了让判定卡通过而反复微调措辞。→ 对策：报告里明确标注哪些 run 用了非默认 prompt，README 不引用这类 run 的数字。
- **A2** 把信息隔离降级成「靠 prompt 自觉」：读者拿不到 `real_material` 这件事必须仍由 `context.py` 在代码里保证，prompt 只是提示词。
- **A3** 为了好看牺牲可读性：加大字号、堆卡片阴影、动效花哨——这个项目的界面是给人看**证据**的，不是给人看设计感的。

---

## 4. 约束

### 继承（一条都不能松）

原文档 §17 与 `.dsh/skills/xhs-invariants` 的五条：信息隔离、读者换厂商、判定卡冻结、规则先筛模型后改、成本不许估算。本设计逐条对照见 §11。

### 新增

- **S1 自证**：任何一个 run，只要它的**报告 HTML** 或 **CLI `--trace-out` 的 JSONL** 还在，就能看出七个 prompt 的全文与来源（default / edited）。运行中的进程内存不算载体（见 N9）。
- **S2 守卫**：读者的 prompt 覆盖层在**写入时**就拒绝含隔离关键词的文本（`real_material`、`angle`、`verdicts`、`feedback_history`、`previous_objections`、`taboo`）。这是 C3 的运行时补丁，不替代 C3 的静态检查。
- **S3 默认值仍是代码**：七段默认 prompt 依旧以 Python 常量形式留在仓库里（只是搬了个文件），保证「prompt 是冻结物」这件事可 grep、可 diff、可 review。

---

## 5. 一次完整使用（把设计演一遍）

1. 打开 `http://127.0.0.1:8000`，左栏画像已带默认值，点「生成」。
2. 中栏出现七个节点：`画像官 → 策划 → 主笔 → 读者 → 封面 → 人味校订 → 守门人`，逐个从「等待」变「运行中」再变「完成」，每行右侧显示耗时与花费（第 2、3 轮会在主笔/读者下再出现一轮）。
3. 稿子不满意。点「主笔」那一行 → 右侧抽屉打开，两个页签：
   - **产物**：这轮写出来的标题/正文/标签 + 它对上一轮反对意见的逐条回应；
   - **本轮 prompt**：这个 run 实际用的全文，只读，顶部标 `default` 或 `edited ab12cd34`。
4. 抽屉里点「编辑下一版」→ prompt 变成可编辑文本域，下方并排显示「与默认版的差异」。
5. 保存 → 顶部出现 `已修改 1 个 prompt` 徽标，抽屉里的页签变成「下一版 prompt（未运行）」。
6. 点顶部「用当前 prompt 重跑」→ 新 run 从画像官开始整条重跑；旧 run 的快照保持只读，顶部选择器里能切回上一版，看到的仍是旧文本与旧稿子。
7. 想回去：每个角色旁边一个「恢复默认」，顶部一个「全部恢复默认」。

---

## 6. 设计决策

每条都写：选了什么、替代方案、代价。带「**我的判断**」的是我替你定的，你有权推翻。

### D10-1 prompt 变成数据，但默认值仍在代码里（三层）

- **默认层**：`backend/app/prompts/defaults.py`，七个常量（从各 agent 模块原样搬过去）。
- **覆盖层**：`backend/data/prompts.json`（`data/` 已在 `.gitignore`），只存被改过的角色。
- **快照层**：`PromptSet`——某次 run 解析完的不可变集合（七个角色的全文 + sha8 + 来源）。

替代方案：(a) 全部改成 YAML 文件，代码里不再有 prompt → 失去 S3，grep 不到「冻结物」的痕迹；(b) 直接进 SQLite → 单人本地没必要，还会把 SQLite 的使用面从 LangGraph checkpoint 扩大到配置。

代价：多一层间接，agent 里从 `PROFILE_SYSTEM` 变成 `deps.prompts.text("profile")`；写测试时要显式给 `Deps.prompts`（给个默认值即可，见 §10）。搬动时别漏 `app/evaluation/judge.py:12` 对 `READER_PROMPT` 的导入。

### D10-2 只有 system prompt 可改，user 消息不给改

user 消息是 `context.py` 里七个 builder 切出来的数据（`backend/app/context.py:38-119`），隔离就发生在那里。允许改它等于允许把 `real_material` 拼进读者上下文，而且没法做行级校验。

代价：想加「请更毒舌」这类要求只能写进 system——这本来也是唯一正当的位置。

### D10-3 每次 run 自带 prompt 快照

写入 `state["prompts"] = {role: {text, sha8, source}}`，跟着 `result_payload` 一起返回、跟着报告一起落盘。

替代方案：只存 sha8（省空间）→ sha 不可逆，事后无法复现；只存「当前生效值」→ 被后续编辑覆盖，等于说谎。

代价：每个 run 多约 7KB 内存；API 的快照响应变大。当前 run 上限 100（`app.py:66`），最坏 ~700KB，可接受。

### D10-4 编辑器改的是「下一版」，历史 run 的 prompt 只读

这是最容易糊弄、也最容易被面试官戳的地方：改完 prompt 回去看旧 run，如果界面上显示的是新文本，就会得出「我上轮就是这么写的」的错觉。

所以读法分两种：**run 快照**（只读，历史）与 **active store**（可写，下一版）。UI 上必须标注清楚，抽屉里两个页签就是干这个的。

代价：前端多一份状态（`prompts.active` 与 `run.prompts` 并存），要防串味。

### D10-5 节点产物走 `node_end` 事件；同一节点可有多条

现在 `_step()` 只推节点名，异常时连 `node_end` 都不发——时间线会永远停在「开始」，这是既有的小谎。事件契约改成：

```
node_end = {
  event: "node_end", node, round, attempt, seq,
  ok: true|false,            // 调用是否抛出了异常
  degraded: true|false,      // 是否走了兜底（见 D10-12）
  error?: "...", degraded_reason?: "...",
  elapsed_ms, usage: {input_tokens, output_tokens, cost_cny, calls},
  prompt_sha8, product?
}
```

- `product` 是该节点的产物（pydantic `model_dump()`；主笔是 `{draft, responses}`）；
- `attempt`：同一 `(node, round)` 的第几次调用，1 起。**守门人不通过时 `finish_draft` 会再跑一次 humanizer + gatekeeper**（`loop.py:146-158`），所以一轮最多 9 条 `node_end`（7 个节点 + 2 次复核）。UI 按 `attempt` 标「复核」，抽屉默认显示最后一条，可切；
- `seq`：本次 run 内单调递增，用来排序（`round` 会重复、`attempt` 只在本节点内有序）；
- 失败时 `ok:false` + `error`，不带 product，异常照旧向上抛；
- `usage` 用节点前后的差值算——这是**实测差**，不是估算，符合「成本不许估算」。

替代方案：事后由前端拉 `GET /runs/{id}` 拼装 → 就看不到「过程」了，且拿不到每节点耗时。

代价：单条 SSE 事件变大（正文 ~800 字，最多 3 轮）；不传 prompt 全文，只传 sha8，前端拿 `GET /runs/{id}/prompts` 对表。

### D10-6 读者覆盖层的 C3 守卫：写入即拒

关键词集合直接对齐 checker 的 `READER_HIDDEN`（`.dsh/skills/xhs-invariants/scripts/check_invariants.py:38-46`）。

**局限要说清**：这是字面守卫。用户完全可以写「猜猜作者的真实经历然后据此打分」，绕过关键词却绕不过意图。这条残留风险不靠代码解决，靠报告标注 + 本文档承认（§12 风险 2）。

### D10-7 契约提醒：警告，不拦截

默认 prompt 里有几句是**被代码强校验**的：

| 角色 | prompt 里的要求 | 代码在哪校验 |
|---|---|---|
| 策划 | 三个角度里恰好一个 `chosen`、每条都要写 `why_not_others` | `agents/planner.py:41-50` |
| 主笔 | `objection_index` 完整覆盖、至少用两条 `real_material` | `agents/writer.py:61-67`、`:97-105` |
| 守门人 | 不得新增命中项、findings 与输入一一对应 | `agents/gatekeeper.py:37-63` |
| 全部 | 只输出 JSON | `llm/client.py` 的 `extract_json` |

编辑后的文本若丢了这些关键词，界面上出黄条：「这几条由代码校验，删掉会被重问或直接失败」，但**允许保存**。理由：用户可能有意实验；真正该拦住的是代码，而代码已经拦了。

### D10-8 UI：三栏保留，加抽屉；只用 Element Plus

- **左 300px**：画像表单（折叠分组）+ 主题 + 「生成」主按钮 + prompt 状态条。
- **中 1fr**：节点时间线，按轮分组，每节点一行：状态点 / 中文名 / 角色代号 / 耗时 / 花费 / 是否用了编辑过的 prompt。
- **右 380px**：定稿（封面 / 标题 / 正文 / 标签）+ 判定摘要 + 未达标项 + 报告链接。
- **抽屉 560px**：点节点打开，三页签「产物 / 本轮 prompt / 编辑下一版」。
- **间距** 4/8/12/16/24；卡片圆角 10、边框 `#e5e7eb`、页底 `#f7f8fa`；强调色 `#be123c`（只用于主按钮与关键徽标）；标题 15/13/12 三级，正文 14/1.75，元信息 12 `#6b7280`，等宽只用于 prompt 与 JSON。
- 响应式：<1100px 三栏改单栏堆叠，抽屉改全屏。

**我的判断**：不引入图表库、不引 diff 库（prompt 差异用简单的行级对比，几十行文本够用）。

### D10-9 评测（`cli eval`）永远用默认 prompt，不读覆盖层

覆盖层是给「写稿」调用的；评测是**测量工具**，量具不能跟着被测量对象一起变。

- `build_deps()` 读 active store（界面与 `cli run` 都走它）；
- 评测路径改用 `build_deps(prompts=PromptSet.defaults())`，并保留 `judge.reader_prompt_sha256()` 基于默认读者的行为（`backend/app/evaluation/judge.py:25-27`）；
- 有覆盖时，评测启动打印一行：「当前有 N 个 prompt 被改过，本次评测仍用默认版」。

代价：`build_deps` 多一个参数、评测路径多一处显式传参；换来的是 `docs/samples/` 里那批数字不会因为谁在界面上调了措辞就悄悄失真。

### D10-10 运行历史：`GET /runs` + 顶部切换

G4 说「前后两版能对照着看」，但现在**没有切回去的入口**：前端一次只有一个 run，`start()` 会 `reset()` 清空；服务端 `runs` 字典也没有列表接口。

- 新增 `GET /runs`：返回最近 100 个 run 的摘要（`run_id / topic / status / 创建时间 / 是否用了编辑过的 prompt`），按创建时间倒序；
- 前端顶部一个运行选择器；切到旧 run 时：拉 `GET /runs/{id}` 快照 + `GET /runs/{id}/prompts` + 订阅事件（`RunBus` 会先回放历史再推实时，`bus.py:27-42`，已完成的 run 回放到 `done` 就结束）；
- 不改 `runs` 的 100 上限与淘汰逻辑。

代价：多一个接口、前端 store 多一份「当前查看的 run」状态（`viewing` 与 `live` 分离）。好处是「改完重跑再回头看上一版」这件事真的能做，而不是嘴上说能。

### D10-11 顶栏的「未保存」状态

编辑 prompt 是显式保存；有未保存内容时，「用当前 prompt 重跑」要二次确认（`el-popconfirm`），避免「以为改生效了，其实没存」。

### D10-12 降级必须可见：`ok` 只表示「没抛异常」，兜底另标

**问题**：reader / humanizer / gatekeeper / cover 都在节点**内部** catch 了 `NodeCallFailed` 并返回兜底产物（`agents/reader.py:99-107`、`humanize.py:92-106`、`gatekeeper.py:83-87`、`cover.py:41-46`）。异常到不了 `_step`，于是「读者调用失败」在时间线上显示成「完成」，产物是一张写着「按未通过处理」的判定卡——正是 D10-4 要防的那种假。

**做法**（不动七个 agent 的签名）：

- `state.py` 加 `degraded_nodes: list[dict]`（元素 `{node, round, reason}`）与 `mark_degraded(state, node, reason)`；
- 四个会兜底的 agent 各加一行 `mark_degraded(...)`；
- `_step` 在调用前后比较这个 list 的长度，把新增项挂到 `node_end` 的 `degraded` / `degraded_reason`。

**UI**：节点行加「降级」黄标；抽屉顶部一条 `el-alert`：「这一步走了兜底：<reason>」。

**为什么不直接把 `ok` 设成 false**：`ok:false` 表示「调用炸了、没有产物」；兜底是**有产物**的。混在一起，时间线就分不清「失败」与「失败但降级继续」，测试也没法分别断言。

代价：四个 agent 各一行；`RunState` 多一个可选键。

---

## 7. 接口

### 7.1 新增：prompt 管理

| 方法 | 路径 | 语义 |
|---|---|---|
| `GET` | `/prompts` | 七个角色的当前生效文本 + 来源 + sha8 + 默认文本 |
| `PUT` | `/prompts/{role}` | 覆盖某角色；body `{"text": "..."}` |
| `DELETE` | `/prompts/{role}` | 该角色恢复默认 |
| `DELETE` | `/prompts` | 全部恢复默认 |
| `GET` | `/runs/{run_id}/prompts` | 该 run 的 prompt 快照（只读） |
| `GET` | `/runs` | 最近 100 个 run 的摘要，倒序（D10-10） |

`GET /runs` 响应（每条摘要，不含正文）：

```json
{"items": [
  {"run_id":"a1b2c3d4e5f6","topic":"租房第一年","status":"passed",
   "created_at":"2026-10-25T17:42:03+08:00","prompts_edited":["writer"]}
]}
```

`created_at` 需要 `create_run` 时补一个时间戳字段（现在 `runs[run_id]` 里只有 `state`）。

`GET /prompts` 响应：

```json
{
  "roles": ["profile","planner","writer","reader","cover","humanizer","gatekeeper"],
  "items": [
    {"role":"writer","text":"…","default_text":"…","source":"edited",
     "sha8":"3f2a91cd","updated_at":"2026-10-25T17:40:12+08:00"}
  ]
}
```

`PUT` 的错误码：`404` 角色不存在；`422` 文本为空 / 超过 20000 字符；`409` 读者的文本里出现隔离关键词（响应带 `detail` 指出是哪个词）。

### 7.2 改动：`POST /runs`

请求体不变（`persona`, `topic`）。行为变化只有一条：run 启动时读一次 active store，**快照后**注入 `deps.prompts` 与 `state["prompts"]`。之后再有人改 prompt，不影响这个 run。

### 7.3 改动：`node_start` / `node_end` 事件

- `node_end` 见 D10-5（含 `product` / `attempt` / `seq` / `degraded`）；
- `node_start` 只加一个 `attempt`，其余不变；
- **节点产物不另开读接口**：切到旧 run 时靠 `GET /runs/{id}/events` 回放历史（`bus.py:27-42`），产物就在回放里。前提是进程还活着（N9）；超过 100 个 run 被淘汰后只剩 `GET /runs/{id}` 的结果快照。
- 前端现有的时间线过滤（`stores/run.ts:32-34`）仍然成立——它只读 `event`/`node`/`round`。

### 7.4 改动：`result_payload`

`meta` 增加两项：

```json
"prompts_edited": ["writer"],
"prompts_sha8": {"profile":"a1b2c3d4","writer":"3f2a91cd", "...":"..."}
```

---

## 8. 存储

`backend/data/prompts.json`（运行时状态，不入库）：

```json
{
  "version": 1,
  "updated_at": "2026-10-25T17:40:12+08:00",
  "overrides": {
    "writer": {"text": "……", "updated_at": "2026-10-25T17:40:12+08:00"}
  }
}
```

- 文件不存在 = 全默认；
- 写了非法内容（角色名不认识）→ 忽略该条并记一条 warning，不让服务起不来；
- 并发写：单人本地，用「读-改-写 + 临时文件替换」即可，不引锁。

---

## 9. 数据流

```
前端                API                     PromptStore          Deps/agents
 |  GET /prompts     |                          |                     |
 |------------------>|  read active             |                     |
 |<------------------|                          |                     |
 |  PUT /prompts/writer                         |                     |
 |------------------>|  guard + write           |                     |
 |  POST /runs       |                          |                     |
 |------------------>|  snapshot()  ----------->|                     |
 |                   |  state["prompts"] = …    |                     |
 |                   |  deps.prompts = snapshot ---------------------> | 每次调用取 text(role)
 |  GET /runs/{id}/events (SSE)                 |                     |
 |<------------------|  node_start / node_end(product, sha8, usage)   |
 |<------------------|  result                                  |
```

---

## 10. 测试计划（TDD，全离线，不花钱）

先写会失败的用例，再实现。全部用 `tests/helpers.py` 的 `FakeLLM` 与 `httpx2.MockTransport`，不碰真 API。

**`tests/test_prompts.py`（新）**

1. 默认集合：七个角色齐全、文本非空、`sha8` 稳定（同文本两次相同）、`source == "default"`。
2. 存储往返：`set` 后新建 store 读回仍是编辑后的文本；`reset(role)` 只清一个；`reset()` 清全部；文件不存在时全默认。
3. 未知角色：`set("nobody", ...)` 抛错；API 层 404。
4. 读者守卫：文本含 `real_material` / `angle` / `verdicts` / `feedback_history` / `previous_objections` / `taboo` 任一 → 拒绝；同一段文本写给 `writer` → 放行。
5. 快照不可变：先 `snapshot()`，再 `set()`，快照里的文本不变（D10-4 的机械保证）。
6. 评测不读覆盖：store 里改了 writer，`build_deps(prompts=PromptSet.defaults())` 仍是默认文本；`reader_prompt_sha256()` 与默认读者文本的 sha 一致（D10-9）。

**`tests/test_loop_events.py`（新）**

1. 一次完整 run（守门人一次过）收到 7 个 `node_end`：节点集合恰好是那七个，每个带 `product`、`prompt_sha8`、`elapsed_ms`、非负 `usage`；两轮时主笔/读者各两条，`attempt` 都是 1。
2. 守门人不通过的那条路径：一轮 9 条 `node_end`——humanizer / gatekeeper 各两条，第二条 `attempt == 2`，且 `seq` 严格递增。
3. `NodeCallFailed` 且节点不兜底（如主笔）：`node_end` 为 `ok:false` 带 `error`，`product` 缺席。
4. 降级路径（读者失败）：`ok` 仍为 `true`，但 `degraded` 为 `true` 且 `degraded_reason` 非空；产物是兜底判定卡（`click == false`）。
5. `usage` 是节点前后差值：各节点 `cost_cny` 之和等于 `state["usage"].cost_cny`。

**`tests/test_api.py`（追加）**

1. `GET /prompts`：7 项、`source` 全 `default`。
2. `PUT` 后变 `edited`；`DELETE` 后回 `default`；`DELETE /prompts` 全清。
3. `422`：空串、纯空白、20001 字符；`404`：未知角色；`409`：读者文本含隔离关键词。
4. `POST /runs` 真的用了覆盖文本：断言 `FakeLLM` 收到的 `system` 等于编辑后的文本（跑通一遍 pipeline）。
5. `GET /runs/{id}/prompts` 返回快照；之后编辑 store，快照不变。
6. 报告页包含 prompt 全文与 `edited` 标记。
7. `GET /runs`：按创建时间倒序、含 `prompts_edited`、不含正文；空列表返回 `{"items": []}`。

**前端**

- `pnpm build` 必须过；新增 `pnpm typecheck`（`vue-tsc --noEmit`）也必须过。
- 不做前端单测（沿用现有空白，不在这次扩）。

## 11. 与不变式的关系

| # | 不变式 | 本设计是否触碰 | 说明 |
|---|---|---|---|
| C1 | `Verdict` 七字段冻结 | 否 | 不加字段。读者 prompt 里写的输出格式只是提示，真正的结构由 pydantic 定 |
| C2 | `Objection` 四字段冻结 | 否 | 同上 |
| C3 | 读者看不到 `real_material`/`angle`/历史判定 | **加强** | `context.py` 一行不改；额外加写入时关键词守卫（S2）。**注意**：语义层绕过拦不住（见 §12-2） |
| C4 | 轮次上限 3 | 否 | 重跑是「新 run」，不是「续跑」，不碰上限 |
| C5 | 不采集平台数据 | 否 | 无新增外部请求 |
| C6 | 通过条件只有一处 | 否 | 不碰 `passed()` |

`check_invariants.py` 的 6 条检查必须保持全绿；C3 的检查目标仍是 `build_reader_context`，本设计不改变它。

---

## 12. 风险

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 1. 改过 prompt 的 run 与 D9 的评测结论不可比 | 高 | 中 | 报告与快照里标 `edited`；README 不引用这类 run；不重跑评测（N6） |
| 2. 读者 prompt 语义上绕过隔离 | 中 | **高** | 写入时关键词守卫 + 报告打标 + 本文档明写「拦不住意图」。这是接受的残留风险 |
| 3. 用户把契约性句子删了，run 反复重问、烧钱 | 中 | 中 | D10-7 黄条提示；成本逐节点可见；一键恢复默认 |
| 4. 快照让 API 响应/内存变大 | 低 | 低 | 只存七段文本；100 run 上限内 ~700KB |
| 5. 前端「当前版 / 本轮版」串味，看成假的 | 中 | 中 | 两个页签物理分开，标签写死「本轮 prompt（只读）」/「下一版（未运行）」 |
| 6. 编辑后忘记保存就重跑 | 中 | 低 | 保存是显式按钮；有未保存改动时「重跑」按钮二次确认 |
| 7. 重启后旧 run 的节点产物与 prompt 快照全没了（只在内存） | 高 | 中 | 这是既有事实（N9）；报告 HTML 与 `--trace-out` 是唯一可留存的证据，README 与交接文档要写明 |
| 8. `--engine graph` 下时间线是空的 | 低 | 低 | N8 明确不做；API 默认 loop。若有人在 CLI 用 graph，只有最终结果，不会崩 |

---

## 13. 实现注意（容易漏的）

| 位置 | 坑 |
|---|---|
| `backend/app/llm/client.py:61-67` | `Deps` 是 `@dataclass(slots=True)`，新字段必须带默认值，否则所有 `Deps(llm=…, settings=…)` 调用点当场炸 |
| `backend/app/evaluation/judge.py:12` | 导入 `READER_PROMPT` 的地方要跟着搬到 `prompts/defaults.py`，否则评测指纹算不出来 |
| `backend/app/graph/loop.py:21-29` | `_step` 现在异常时不发 `node_end`；改的时候注意降级路径（读/封面/人味校订）仍要照旧吞异常 |
| `backend/app/api/app.py:59-87` | run 的 prompt 快照必须在创建任务时取一次，不能等 `execute()` 里再读——否则两次读之间被改会串味 |
| `backend/app/report/trace.py:22-39` | `build_trace` 是报告的唯一数据源，prompt 快照要走它，别在 `html.py` 里另开一路读 state |
| `frontend/src/api.ts:33` | 事件名是写死的白名单；本次不新增事件类型就不用动，新增则必须同步 |
| `frontend/vite.config.ts:11-14` | dev 代理只写了 `/runs` 与 `/health`，要加 `/prompts`，否则分离开发时 404 |
| `frontend/src/stores/run.ts` | 时间线过滤只认 `node_start`/`node_end`；带 `product` 的事件体积变大，别在 watch 里做深拷贝 |
| `backend/app/api/app.py:66` + `bus.py:12` | run 超过 100 个会从 `runs` 淘汰，但 `bus._history` 没人清——载荷变大后这个既有泄漏更明显。顺手在淘汰处清掉该 run 的历史（可选，别为它单开一轮） |
| `backend/app/graph/langgraph_pipeline.py` | 直接调 `run_*`，绕过 `_step`：**不会**发节点事件（N8）。改的时候别顺手给它加事件，那是另一轮的事 |
| `backend/app/cli.py:138-147`、`:208-212` | `_swapped_reader()` 与 `_evaluate()` 自己 new `Deps`；评测两条路径都必须显式传 `PromptSet.defaults()`，否则 D10-9 形同虚设 |
| `backend/app/graph/loop.py:21` | `_step` 要改成能拿 `state`（算耗时/用量差、读 `degraded_nodes`）并维护 `seq`/`attempt` 计数器；它现在是纯包装函数，改动会触及所有调用点 |

## 14. 给 builder 的自由度

- 组件怎么拆（抽屉里三个页签是否拆组件、时间线是否用 `el-timeline`）；
- CSS 具体数值（在 §6 D10-8 的约束内）；
- prompt 差异对比的呈现方式（行级高亮 or 并排）；
- `node_end` 里 `product` 是否要裁剪字段、要不要加 `context_size` 之类的辅助信息；
- 测试文件怎么组织（按 `test_prompts.py` / `test_api.py` 追加 / 新建 `test_loop_events.py`）。

## 15. 我的判断（你可以挑错的部分）

1. **一次只维护一版覆盖**，不做预设库（N2）——你说的是「改完重跑」，没说「攒几套方案」。
2. **失败也发 `node_end`**——顺带修掉「时间线永远转圈」这个既有的小谎。
3. **prompt 快照进 report**——报告是证据，比界面活得久。
4. **不引 diff 库**——prompt 是几十行文本，行级对比够了。
5. **`vue-tsc` 接进 build**——交接文档的 Minor 里提过 `tsconfig.strict` 实际不生效；这次要动前端，顺手接上（若现有代码过不了，先修类型再启用，不搞 `any` 掩盖）。

---

## 16. 验收（怎么算做完了）

- 离线四件套全绿：`pytest -q`、`ruff check`、`mypy`、`check_invariants.py`；
- 七个节点在前端各自可点开、有产物、有耗时花费、有本轮 prompt；
- 改一个 prompt → 重跑 → 报告里能看到那次用的是 `edited`，旧 run 仍显示旧文本；
- 恢复默认后，`GET /prompts` 的 `source` 全为 `default`；
- `pnpm build` 通过且 `vue-tsc --noEmit` 无错；
- `README.md` 的「界面」小节（第 121–130 行）同步更新：现在写的是「中间滚动节点起止」，改完要写清「节点可点开、prompt 可改、整条重跑」。
