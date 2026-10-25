# D10 节点可见 + prompt 可改：裁决记录

日期：2026-10-25
对应设计：`docs/superpowers/specs/2026-10-25-node-inspector-and-editable-prompts-design.md`
对应计划：`docs/superpowers/plans/2026-10-25-d10-node-inspector-and-editable-prompts.md`

只记**改变了既有行为**的四条。其余（UI 排布、事件字段命名）是实现细节，看代码即可。

---

## 1. prompt 从常量变成「默认 + 覆盖 + 快照」三层

**怎么定的**：默认文本搬进 `backend/app/prompts/defaults.py`（仍是 Python 常量，可 grep、可 review）；运行时覆盖落在 `backend/data/prompts.json`（`data/` 已 ignored）；每次 run 把七段全文与 sha8 抄进 `state["prompts"]`。

**为什么**：界面要能改，但「改过之后还叫同一组数据吗」必须答得出来。只存指纹不可逆，只存当前值会被后续编辑覆盖。

**代价**：agent 不再直接 import 文本，多一层 `Deps.prompts` 间接；每个 run 多约 7KB 快照。API 的 run 本来就只在内存（见 `2026-10-25-api-rulings.md`），所以重启后连快照一起没——能留存的只有报告 HTML 与 CLI `--trace-out`。

---

## 2. 评测（`cli eval`）永远用默认 prompt

**怎么定的**：`build_deps()` 读覆盖层；评测路径（`_evaluate`、`_swapped_reader`）显式传 `PromptSet.defaults()`，存在覆盖时启动打印一行警告。`judge.reader_prompt_sha256()` 继续对默认读者 prompt 取指纹。

**为什么**：量具不能跟着被测对象一起变。否则谁在界面上调了两句措辞，`docs/samples/` 里那批数字就悄悄失真，而报告上的指纹还显示「没变」。

**代价**：`build_deps` 多一个参数；评测与界面用不同 prompt 时，行为差异要靠那行警告让人看见。

---

## 3. 降级不复用「完成」：`ok` 与 `degraded` 分开

**怎么定的**：读者、封面、人味校订、守门人在内部 catch 失败并给兜底产物时，调 `mark_degraded()` 登记；`_step` 比较调用前后 `state["degraded_nodes"]` 的长度，把 `degraded` 与 `degraded_reason` 挂到 `node_end` 上。`ok:false` 仍只表示「调用抛了异常、没有产物」。

**为什么**：改之前，读者挂掉在时间线上显示「完成」，产物是一张写着「读者调用失败，按未通过处理」的判定卡——那是最容易被当成真判定的一处谎。

**代价**：四个 agent 各多一行；`RunState` 多一个键。

---

## 4. 多一个 `GET /runs`，让「切回上一版」真的能做

**怎么定的**：服务端返回最近 100 个 run 的摘要（不含正文），前端顶部一个选择器；切到旧 run 时拉 `GET /runs/{id}` + `GET /runs/{id}/prompts`，再订阅 `/events` 靠 `RunBus` 回放历史补齐节点产物。

**为什么**：设计里说「改完重跑，前后两版能对照」，可原来的界面一次只有一个 run，`start()` 会 `reset()` 清空——没有切回去的入口，那句话就是空话。

**代价**：多一个接口与一份前端「当前查看的 run」状态；节点产物只在进程内，重启即丢（与 run 快照同一限制）。
