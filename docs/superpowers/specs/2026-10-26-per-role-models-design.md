# D11：七个角色各配各的模型（可含未计价、可与读者同模型）

状态：已实现
日期：2026-10-26
前置：`2026-10-23-xhs-multiagent-design.md`（§13/§17 的 D11 修订）、`2026-10-25-node-inspector-and-editable-prompts-design.md`（同一套「默认→覆盖→快照」做法）

---

## 1. 要解决的问题

换模型要改 `.env` 再重启。用户希望在界面上直接换，而且不是一个全局开关，是**七个角色各配各的**。

## 2. 用户定下的两条边界（改变了旧约束）

1. **19 个模型都能选，不要求有价格。** 没价格时 token 照记，钱显示成「≥」。
2. **读者和主笔可以同模型，自由选择。**

第二条与旧设计冲突：§17 原写「读者用另一家厂商——这是机制，不是偏好」，`Settings.load()` 会拒绝同模型。现在的处理不是二选一，而是**保留自由、同时保留证据**：

> 同模型的 run 会带 `reader_independent: false`，界面挂「读者=主笔：非独立评审」黄标，报告同款说明。E2 的 κ、E3 的胜率仍只在「读者≠主笔」的 run 上成立。

（这是我在「允许但打标」与「直接禁止」之间替你选的：你要自由，项目要能自证，打标同时满足两边。）

## 3. 做法

三层，与 prompt 完全同构：

- **默认**：`.env` 的 `WRITER_MODEL`（六个角色）与 `READER_MODEL`（读者）。
- **覆盖**：`backend/data/models.json`，只存改过的角色。
- **快照**：每次 run 把七个角色的 `{model, source, priced}` 写进 `state["models"]`，进报告与 `--trace-out`。

调用链：`Deps.models` → 七个 agent 调 `deps.models.model("<role>")` → `LLMClient.structured(model=…)`。
provider（base_url / api_key）仍按读者/写作侧两组取，换模型不换通道。

## 4. 接口

| 方法 | 路径 | 语义 |
|---|---|---|
| `GET` | `/models` | 七个角色当前模型 + 默认值 + 来源 |
| `GET` | `/models/available` | 下拉候选：价格表 ∪ 默认值 ∪ 网关 `/v1/models`（网关不可达就退化） |
| `PUT` | `/models/{role}` | `{"model": "..."}`，即改即存 |
| `DELETE` | `/models/{role}` / `/models` | 恢复默认 |

`node_end` 增加 `model`；`meta` 增加 `models`、`models_edited`、`reader_independent`；`usage` 增加 `unpriced_calls`。

## 5. 计费

`LLMClient._apply_cost`：价格表命中就照旧算；没命中 → `cost_cny` 不动、`unpriced_calls += 1`。
界面与报告显示 `≥ 0.0441 元（1 次未计价）`，不写 0。

## 6. 评测

`cli eval` 仍用 `.env` 默认模型（量具不跟着被测对象变）；有覆盖时启动打印警告。

## 7. 非目标

- 不做价格编辑界面（用不到那 15 个模型的成本数字时，token 足够回答「跑了多少」）。
- 不做 per-provider 的 key 管理，`base_url` / key 仍只在 `.env`。
- 不改 `PRICES` 的取值（仍是高峰价、美元/百万 token）。

## 8. 已知的坑

- 同模型的 run 不能与 `docs/samples/` 里的评测数字对照；报告已标。
- 网关模型清单依赖 `WRITER_BASE_URL` 可达；不可达时下拉只剩价格表里的四个，不影响手改 JSON。
