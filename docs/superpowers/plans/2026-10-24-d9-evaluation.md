# D9 评测（E1/E2/E3）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 E1/E2/E3 三个实验回答「判定卡有没有判别力、是不是可复现、七角色到底值不值」，产出可复现的 markdown + 单文件 HTML 报告。

**Architecture:** 评测逻辑放在 `backend/app/evaluation/`（可 import、可单测），数据与产物放仓库根的 `eval/`（`eval/data/` 输入、`eval/out/` 结果）。所有实验共用一个「独立评审器」：给定一篇稿子与读者侧画像，调**指定 provider** 出 `Verdict`。统计全部手写（Kendall τ-b、Spearman ρ、Cohen κ），不引 scipy——三个公式各十行，能测、无重依赖。

**Tech Stack:** 沿用 D1–D4；新增无。

**Spec:** `docs/superpowers/specs/2026-10-23-xhs-multiagent-design.md` §12

## Global Constraints

- **评分口径统一**（§12 E3）：所有组的成稿都由同一个读者实例事后打分；A 组本身没有 `Verdict`，它的成本要额外计入这次评分调用。
- E1 判据：排序正确率 ≥ 80% 视为有判别力，< 60% 无效；并做权重 ±30% 敏感性检查，结论反转过就如实写「对权重敏感」。
- E2 判据：`click` / `save` 的 Cohen κ ≥ 0.6 视为一致性可接受；`score` 另报 Spearman ρ。
- 每次跑评测必须记录**读者 prompt 的 sha256** 与模型名，否则「你改过 prompt 之后还叫同一组数据吗」答不上来。
- 三档稿的 `bad` 档用反向 prompt 构造，**不做爬虫、不用真实笔记**（§3 N2）。
- 规模可配：`--topics` 默认 10、`--pairs` 默认 20；缩小规模时报告里必须写明实际 N。
- 评测不写 `Verdict` / `Objection` 字段，不改 `MAX_ROUNDS`；`xhs-invariants` 必须仍全绿。

## Review Focus

1. **`good` 档必须是 `status == "passed"`**；凑不够时降级用 `best_round` 并记 `good_fallback`，不能拿未通过稿冒充好稿。
2. **同分怎么排**：三档排序遇到并列（τ 与正确率都要定义），实现必须显式处理，不能靠 `>` 偶然正确。
3. **κ 的分母**：两家厂商全判同一类（例如都全 `click=False`）时 `pe=1`，κ 无定义——此时返回 `None` 并在报告里标注，不能除以零。
4. **成本口径**：三组的 token/成本必须来自各自 `Usage` 累计，A 组的评分调用单独列出。
5. **可复现**：同一 seed、同一批稿、同一 prompt hash 下重跑，E1 的排序正确率必须一致（模型温度会带噪声，报告里写清）。

---

## 文件结构

```
backend/app/evaluation/
├── __init__.py
├── stats.py          # kendall_tau_b / spearman_rho / cohens_kappa / ordering_accuracy
├── judge.py          # 独立评审器：任意 provider 对单篇稿打分
├── corpus.py         # 三档稿：good（passed run）/ mid（首轮稿）/ bad（反向 prompt）
├── runners.py        # run_e1 / run_e2 / run_e3
└── report.py         # markdown + 单文件 HTML
eval/
├── data/topics.json  # 10 个主题
├── data/personas/    # 3 个画像（p01 已在 scripts/personas）
└── out/              # 结果（gitignore）
```

---

### Task 1: 统计函数（纯函数）

**Files:** Create `backend/app/evaluation/stats.py`；Test `backend/tests/test_eval_stats.py`

**Interfaces:**
- `kendall_tau_b(x: list[float], y: list[float]) -> float`（含并列修正）
- `spearman_rho(x: list[float], y: list[float]) -> float`（平均秩）
- `cohens_kappa(a: list[bool], b: list[bool]) -> float | None`（`pe == 1` 时返回 `None`）
- `ordering_accuracy(groups: list[tuple[float, float, float]]) -> float`（每组 `(good, mid, bad)` 的分数，返回 `good > mid > bad` 的比例）

- [ ] Step 1 失败的测试：τ 完全一致 = 1、完全相反 = -1、并列用 tau-b；ρ 与秩一致；κ 手算样例（`a=[T,T,F,F]`, `b=[T,T,F,T]` → 0.5）；`pe==1` 返回 `None`；排序正确率 2/3。
- [ ] Step 2 跑测试确认失败
- [ ] Step 3 实现（Kendall 用 O(n²) 计数；Spearman = 秩的 Pearson）
- [ ] Step 4 跑测试确认通过
- [ ] Step 5 提交 `feat(eval): 手写 Kendall τ-b / Spearman ρ / Cohen κ`

---

### Task 2: 独立评审器

**Files:** Create `backend/app/evaluation/judge.py`；Test `backend/tests/test_eval_judge.py`

**Interfaces:**
- `async def judge_draft(draft: Draft, persona: PersonaInput, deps: Deps, *, role_provider: str = "reader") -> Verdict`
  用 `build_reader_context` 同款的上下文（含编号句子），走 `deps.llm.structured(role=role_provider, schema=Verdict)`；`quote not in body` 的异议丢弃（与 reader 节点同规则）。
- `reader_prompt_sha256() -> str`：`hashlib.sha256(READER_PROMPT.encode())` 前 12 位，报告里用。
- `def set_provider(settings, *, base_url, model, api_key) -> Settings`：复制一份 Settings 供 E2 的第二厂商用。

- [ ] Step 1 失败的测试：给定 FakeLLM 返回 `Verdict`，`judge_draft` 返回同值且 role 正确；幻觉 quote 被丢弃；`reader_prompt_sha256()` 稳定且长度 12。
- [ ] Step 2 跑测试确认失败 → Step 3 实现 → Step 4 通过 → Step 5 提交 `feat(eval): 独立评审器与 prompt 指纹`

---

### Task 3: 三档稿语料

**Files:** Create `backend/app/evaluation/corpus.py`；Test `backend/tests/test_eval_corpus.py`

**Interfaces:**
- `async def build_corpus(topics: list[str], personas: list[PersonaInput], deps: Deps, *, per_topic: int = 1) -> Corpus`
  `Corpus`：`items: list[CorpusItem]`，每项 `topic`、`good: Draft`、`mid: Draft`、`bad: Draft`、`good_fallback: bool`。
- `good` 取一次完整 `run_loop + finish_draft` 的交付稿，且 `status == "passed"`；不通过则用 `best_round` 稿并置 `good_fallback=True`。
- `mid` 取同一 run 的 `draft_history[0]`。
- `bad` 用 `BAD_PROMPT` 反向生成：明确要求抽象形容词、排比、无具体数字与场所、结尾升华。

- [ ] Step 1 失败的测试：FakeLLM 按顺序给 2 次 run 的响应，断言 `good/mid/bad` 三点取自正确位置、`bad` 的 prompt 里含「抽象」与「不要出现任何具体数字」、`good_fallback` 在未通过时为 True。
- [ ] Step 2 失败 → Step 3 实现 → Step 4 通过 → Step 5 提交 `feat(eval): 三档稿语料构造`

---

### Task 4: 三个 runner

**Files:** Create `backend/app/evaluation/runners.py`；Test `backend/tests/test_eval_runners.py`

**Interfaces:**
- `async def run_e1(corpus, judge_deps, *, weights_variants=(1.0, 1.3, 0.7)) -> E1Result`
  返回 `ordering_accuracy`、`kendall_tau`、每个权重变体下的正确率、`sensitive: bool`。
- `async def run_e2(corpus, judge_deps_a, judge_deps_b) -> E2Result`
  返回 `kappa_click`、`kappa_save`、`spearman_rho`、两家的 `score` 列表。
- `async def run_e3(topics, personas, deps, judge_deps, *, mode: Literal["A","B","C"]) -> E3Row`
  A：单次裸模型成稿；B：完整链路；C：完整链路但读者用 writer 的 provider。每行含 `pass_rate`、`mean_score`、`tokens`、`cost_cny`、`elapsed_s`、`smell_before/after`。
  三组**都**由 `judge_deps` 同一实例打分（§12 口径统一），A 的评分成本单列。

- [ ] Step 1 失败的测试：用 FakeLLM 构造「good>mid>bad」的分数 → `ordering_accuracy==1.0`；把 bad 的分抬到最高 → 正确率下降、`sensitive` 为真；E2 两家一致的样例 κ=1；E3 的 A 组只有 1 次生成调用 + 1 次评分调用。
- [ ] Step 2 失败 → Step 3 实现 → Step 4 通过 → Step 5 提交 `feat(eval): E1/E2/E3 runner`

---

### Task 5: 报告与 CLI

**Files:** Create `backend/app/evaluation/report.py`；Modify `backend/app/cli.py`；Test `backend/tests/test_eval_report.py`

**Interfaces:**
- `render_markdown(result: EvalBundle) -> str`；`render_html(result: EvalBundle) -> str`（单文件、无外链）。
- 报告必须含：实际 N、prompt 指纹、模型名与 provider 的 base_url 主机名、E1/E2/E3 三张表、判据是否达成、**局限**一节（无人工信号、bad 档是构造的、标签级未验证）。
- CLI：`python -m app.cli eval --topics 10 --pairs 20 --out eval/out/`，内部串联 corpus → E1 → E2 → E3 → 报告；`--dry-run` 用 FakeLLM 跑通全流程不花钱。

- [ ] Step 1 失败的测试：`render_markdown` 含「排序正确率」「Kendall」「κ」「局限」；`render_html` 以 `<!doctype html>` 开头且无 `http`；CLI `eval --dry-run` 返回 0 并写出两个文件。
- [ ] Step 2 失败 → Step 3 实现 → Step 4 通过 → Step 5 提交 `feat(eval): 评测报告与 CLI`

---

## 交付验收

1. `uv run python -m app.cli eval --dry-run --out eval/out/` 不花钱跑通全链路。
2. 真实小规模（`--topics 3 --pairs 3`）跑一次，产出 `eval/out/report.md` 与 `report.html`。
3. `uv run pytest -q` 全绿；`ruff` / `mypy` 0；`xhs-invariants` 6/6。
4. 报告里能直接读到：排序正确率、τ、κ、ρ、三组 pass 率与成本。
