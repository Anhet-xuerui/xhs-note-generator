---
name: xhs-invariants
description: Use when editing context builders, role prompt templates, the Verdict or Objection schema, pass conditions, score(), the round cap, or eval scripts in this repo.
---

# 小红书多角色系统：冻结不变式

## 概览

这个仓库的差异化不在功能，在五条一旦让步就无法自证的约束。**唯一真相源是设计文档** `docs/superpowers/specs/2026-10-23-xhs-multiagent-design.md`（§3 非目标、§6 信息食谱、§7 判定卡与轮次、§12 评测口径、§17 已定取舍）。本 skill 不重述规则，只做两件事：指出该看哪一节，以及给一条可执行的校验命令。

## 什么时候用

- 改 `context.py` 或任何 `build_*_context`、角色 prompt 模板
- 改 `Verdict` / `Objection` 字段
- 改通过条件、`score()`、权重、轮次上限
- 写 `eval/` 下的脚本、报告、图表

## 五条与对应的机械校验

| # | 不变式 | 真相源 | checker 规则 |
|---|---|---|---|
| C1 | `Verdict` 八字段冻结 | §7、§17 | 字段集必须完全相等 |
| C2 | `Objection` 四字段冻结 | §7 | 字段集必须完全相等 |
| C3 | 读者看不到 `real_material`/`angle`/历史判定 | §6 | `build_reader_context` 内不得出现这些标识符 |
| C4 | 轮次上限 = 3，硬编码 | §7、§17 | 必须字面量 `3`，不得来自配置 |
| C5 | 不采集、不发布平台数据 | §3 N1/N2 | 不得 import playwright/selenium/scrapy，不得出现小红书域名 |
| C6 | 通过条件只有一处定义 | §12 | 全仓至多一个 `passed()` |

## 怎么跑

```bash
python .dsh/skills/xhs-invariants/scripts/check_invariants.py --root .
```

`exit 0` 才算没破坏契约；`exit 1` 会指明文件、行号和规则号。改代码前后各跑一次。尚无 `backend/app` 时输出「跳过」并返回 0，属正常。

## 被文档否决过的提案（评审会问）

- 「让读者知道 `real_material`，判断才准」→ §6：它会替作者打同情分。
- 「前端要展示为什么没过，给 `Verdict` 加字段」→ §7 冻结；结论放在独立模型（如 `VerdictEvaluation`）。
- 「上限做成配置，方便调参」→ §7/§17：3 是拍的，但不对外开放调高。

## 要改冻结值

顺序不能反：先改设计文档 → 再改本目录 `scripts/check_invariants.py` 里的常量 → 再改代码与测试。只改代码不改文档，等于让评测结果与说明对不上。
