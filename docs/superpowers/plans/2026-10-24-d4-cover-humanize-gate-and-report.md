# D4（封面 / 人味校订 / 守门人）+ 报告导出 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让一次 run 产出「标题 + 封面文案 + 正文 + 标签」，经过 AI 味清理与合规兜底后落盘，并导出一份可离线打开的单文件 HTML 报告。

**Architecture:** 在现有手写 loop 尾部追加两段：`封面 → 人味校订（检测→改写→保真校验）→ 守门人（正则先筛→模型判误报）→ 需则再修一次 → 复核`。AI 味检测与违禁词匹配**全部是规则**，模型只负责按命中项改写与判定误报（§8/§9 同构）。事件落 JSONL，报告由 JSONL 渲染为自包含 HTML。

**Tech Stack:** 沿用 D1–D3（Python 3.11 / pydantic v2 / openai / pytest）。新增 `jieba`（成语密度需要中文分词）。

**Spec:** `docs/superpowers/specs/2026-10-23-xhs-multiagent-design.md`

## Global Constraints

- §8：人味校订**只做减法**，输入必须含画像卡全文与 AI 味检测报告；模型只按 `hits` 改写，不许自由发挥。
- §8 保真四条：数字集合不变、专名集合不变、画像 `anchors` 不丢、长度 ±15%。违反即**回退**，不重试。
- §9：规则库先筛，模型只做两件事——判误报、给改写建议。`blocking` 命中 → 人味校订带命中项再修一次（不计轮次）→ 复核；仍 blocking → `status="gate_blocked"`。
- 守门人**不降级**：模型调用失败直接 `gate_blocked`，不能因为模型挂了就放行合规（§10）。
- `Verdict` / `Objection` 冻结不变；`MAX_ROUNDS = 3`；不采集平台数据；`xhs-invariants` 六条必须仍全绿。
- 封面文案 ≤ 12 字，只看标题与正文首句 + `tone`，看不到正文全篇（§6）。
- 报告必须是**单文件、无外部依赖**（JS/CSS 内联），双击即可看。

## Review Focus

1. **空稿 / 单句稿**走完整链路：检测器不能因段落为空除零，保真校验不能因 `len(before)==0` 崩。
2. **emoji 与中文标点**混排时 `spans` 必须落在字符下标上（Python 字符串下标，不是字节）。
3. **规则误报**：「最后」「第一次」「唯一一次」不能被判成极限词；模型判误报失败时按命中处理（保守）。
4. **改写把数字写丢**（`5200` → `五千多`）：保真必须拦住并回退，报告里要能看到「被拦下了」。
5. **gate_blocked 的稿子**也要能导出报告，不能让 CLI 崩或静默丢结果。

---

## 文件结构

```
backend/
├── app/
│   ├── agents/cover.py            # 封面角色
│   ├── agents/humanize.py         # 人味校订（改写者）
│   ├── agents/gatekeeper.py       # 守门人（判误报 + 改写建议）
│   ├── humanize/smell.py          # AI 味检测器（纯规则）
│   ├── humanize/fidelity.py       # 事实保真校验（纯规则）
│   ├── rules/rules.yaml           # 违禁词/极限词规则库
│   ├── rules/engine.py            # 正则引擎（先筛）
│   ├── report/html.py             # 单文件 HTML 渲染
│   └── report/trace.py            # JSONL 事件读写
└── tests/
    ├── test_smell.py
    ├── test_fidelity.py
    ├── test_agents_cover.py
    ├── test_agents_humanize.py
    ├── test_rules_engine.py
    ├── test_agents_gatekeeper.py
    ├── test_report.py
    └── test_loop.py               # 追加：D4 链路与 gate_blocked
```

---

### Task 1: 封面角色

**Files:**
- Create: `backend/app/agents/cover.py`
- Test: `backend/tests/test_agents_cover.py`

**Interfaces:**
- Produces: `async def run_cover(state: RunState, deps: Deps) -> str`；`COVER_SYSTEM: str`；内部模型 `CoverText(BaseModel): cover_text: str`。
- 写入 `state["draft"].cover_text` 并返回。超 12 字时按代码截断并记 `degraded`（不重问）。
- `build_cover_context(state) -> dict`：**只有** `title`、首句、`tone`，不含正文全篇（§6）。

- [ ] **Step 1: 写失败的测试**

```python
async def test_cover_sees_only_title_and_first_sentence():
    deps = deps_with(CoverText(cover_text="中介没说的三件事"))
    await run_cover(make_state(), deps)
    sent = deps.llm.users[0]
    assert "标题" in sent and "首句" in sent
    assert "第二句之后" not in sent            # 正文其余部分不出现
    assert deps.llm.roles == ["cover"]

async def test_cover_truncates_to_twelve_chars():
    deps = deps_with(CoverText(cover_text="这是一句明显超过十二个字的封面文案"))
    assert len(await run_cover(make_state(), deps)) == 12
```

- [ ] **Step 2: 跑测试确认失败** → `ImportError: run_cover`
- [ ] **Step 3: 实现** `run_cover` + `COVER_SYSTEM`（三秒抓眼、可牺牲信息量、≤12 字）+ `build_cover_context`（放 `context.py`，与其它 builder 同处）。
- [ ] **Step 4: 跑测试确认通过**（2 passed）
- [ ] **Step 5: 提交** `feat(agents): 封面角色（≤12 字，只看标题与首句）`

---

### Task 2: AI 味检测器（纯规则）

**Files:**
- Create: `backend/app/humanize/smell.py`
- Test: `backend/tests/test_smell.py`

**Interfaces:**
- Produces: `detect(text: str) -> SmellReport`；常量 `ABSTRACT_NOUNS`、`AI_PATTERNS`、`IDIOM_CAP`、`PARAGRAPH_STDDEV_MIN`。
- 六类命中与分值（写死，测试逐条钉住）：`abstract_noun 18`、`idiom_density 12`、`ai_pattern 20`、`uniform_paragraph 10`、`no_anchor 25`、`emoji_rhythm 8`；`score = min(100, 命中的类别分值之和)`，命中同类多次只计一次。
- `spans` 用 Python 字符下标（`str.index`），`examples` 取原词。

- [ ] **Step 1: 写失败的测试**

```python
def test_abstract_nouns_are_flagged_with_spans():
    r = detect("这件事让我成长了很多，也治愈了我。")
    hit = next(h for h in r.hits if h.category == "abstract_noun")
    assert "成长" in hit.examples and "治愈" in hit.examples
    assert hit.spans[0][0] == "这件事让我".__len__()

def test_ai_patterns_match_not_x_but_y():
    r = detect("这不是租房，而是成年人的第一课。这不仅是一次搬家，更是告别。")
    assert any(h.category == "ai_pattern" for h in r.hits)

def test_uniform_paragraphs_flagged():
    r = detect("第一段长度差不多。" * 1 + "\n\n" + "第二段长度也差不多。" + "\n\n" + "第三段仍然差不多。")
    assert any(h.category == "uniform_paragraph" for h in r.hits)

def test_concrete_text_scores_low():
    r = detect("2023年3月，我在上海中山公园附近租了个38平的一居室，月租5200。签合同那天中介说：“这楼隔音差。”")
    assert r.score <= 20 and not any(h.category == "no_anchor" for h in r.hits)

def test_empty_text_scores_zero_and_does_not_crash():
    assert detect("").score == 0
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**：分词用 `jieba.posseg` 统计 `i`（成语）词频占比；段落按 `\n\n` 切；emoji 检测用字符区间。
- [ ] **Step 4: 跑测试确认通过**（5 passed）
- [ ] **Step 5: 提交** `feat(humanize): AI 味检测器（六类规则）`

---

### Task 3: 事实保真校验（纯规则）

**Files:**
- Create: `backend/app/humanize/fidelity.py`
- Test: `backend/tests/test_fidelity.py`

**Interfaces:**
- Produces: `check(before: str, after: str, profile: ProfileCard) -> FidelityResult`，`@dataclass(frozen=True) FidelityResult: ok: bool, reason: str = ""`。
- 四条（§8）：数字集合相等、专名集合相等、`anchors` 全在 `after` 里、`0.85 <= len(after)/len(before) <= 1.15`。
- `before` 为空时直接 `ok=True`（空稿无从比较，不误报）。

- [ ] **Step 1: 写失败的测试**

```python
def test_ok_when_numbers_and_anchors_survive(): ...
def test_rejected_when_number_changes():          # 5200 → 五千多
    assert not check("月租5200元", "月租五千多元", card).ok
def test_rejected_when_anchor_dropped(): ...
def test_rejected_when_too_short():               # 砍掉 30%
def test_empty_before_is_ok(): ...
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**：数字用 `\d+(?:\.\d+)?`；专名 = 引号内文本 + `《》` 内文本 + 连续 2+ 大写的拉丁词；`reason` 里写明违反的是哪一条。
- [ ] **Step 4: 跑测试确认通过**（5 passed）
- [ ] **Step 5: 提交** `feat(humanize): 事实保真四条校验`

---

### Task 4: 人味校订节点

**Files:**
- Create: `backend/app/agents/humanize.py`
- Modify: `backend/app/schemas.py`（新增 `SmellHit/SmellReport/ChangeLog/HumanizedDraft`）
- Test: `backend/tests/test_agents_humanize.py`

**Interfaces:**
- Produces: `async def run_humanize(state: RunState, deps: Deps, *, hints: list[GateFinding] | None = None) -> HumanizedDraft`；`HUMANIZE_SYSTEM: str`；内部模型 `HumanizeOutput(BaseModel): title, body, tags: list[str], changes: list[ChangeLog]`。
- 流程：`detect(定稿)` → 调模型（user 消息 = 全文 + 画像卡 + `hits` 摘要，有 hints 时附上）→ `smell_after = detect(新稿)` → `check(before, after, profile)`。
- 保真失败 → **回退**：返回原稿，`changes` 保留，`fidelity="reverted"`，`smell_after == smell_before`；不重试。
- 模型调用失败 → `fidelity="skipped"`，返回原稿。

- [ ] **Step 1: 写失败的测试**

```python
async def test_only_rewrites_what_hits_point_at():
    deps = deps_with(HumanizeOutput(title="t", body="2023年我在上海租了个38平的房子，月租5200。", tags=["租房"], changes=[]))
    out = await run_humanize(make_state(body="这个过程中我成长了很多，也治愈了自己。"), deps)
    assert "abstract_noun" in deps.llm.users[0]          # 命中项进了 prompt
    assert out.smell_after <= out.smell_before

async def test_reverts_when_number_lost():
    # 模型把 5200 改写掉 → 回退原文
    assert out.fidelity == "reverted"
    assert out.body == original_body
    assert out.smell_after == out.smell_before
    assert out.changes                                  # 被拦下的改动仍保留

async def test_skips_on_llm_failure():
    assert out.fidelity == "skipped" and out.body == original_body
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**（注意 `smell_after` 必须对新稿重新 `detect`，不能沿用 before）
- [ ] **Step 4: 跑测试确认通过**（3 passed）
- [ ] **Step 5: 提交** `feat(agents): 人味校订（按命中项做减法 + 保真回退）`

---

### Task 5: 规则库与守门人

**Files:**
- Create: `backend/app/rules/rules.yaml`、`backend/app/rules/engine.py`、`backend/app/agents/gatekeeper.py`
- Test: `backend/tests/test_rules_engine.py`、`backend/tests/test_agents_gatekeeper.py`

**Interfaces:**
- Produces: `load_rules(path: Path | None = None) -> list[Rule]`；`match(text: str, rules: list[Rule]) -> list[GateFinding]`（纯正则，`false_positive=False`）。
- `Rule`: `id: str`、`patterns: list[str]`、`severity: Literal["blocking","warning"]`、`hint: str`；另有 `rule: str` 型规则（`body-length` 300–800、`tag-count` 3–8）由 `engine.match_structure(body, tags)` 处理。
- Produces: `async def run_gatekeeper(state, deps, draft: HumanizedDraft) -> GateResult`；模型只收到命中列表，返回 `GateJudgement(BaseModel): findings: list[GateFinding]`（逐条填 `false_positive` 与 `hint`）。
- `GateResult.passed = not any(f.severity == "blocking" and not f.false_positive)`。
- 模型失败 → `passed=False`，`findings` 保留正则结果（保守，§10 不降级）。

- [ ] **Step 1: 写失败的测试**

```python
def test_rule_library_has_three_blocking_categories():
    ids = {r.id for r in load_rules()}
    assert {"absolute-claim", "medical-efficacy", "diversion"} <= ids

def test_matches_absolute_words_with_spans():
    findings = match("这是最好的选择，100%有效", load_rules())
    assert {f.rule_id for f in findings} == {"absolute-claim"}
    assert findings[0].matched in {"最", "100%"}

def test_structure_rules_warn_on_short_body_and_few_tags(): ...

async def test_model_marks_false_positive_for_last_and_first():
    # 「最后」「第一次」被判误报后，passed 仍为 True
    result = await run_gatekeeper(state, deps, draft_with("最后我还是搬走了，第一次租房就这样结束"))
    assert result.passed

async def test_blocking_hit_without_false_positive_fails():
    assert not result.passed

async def test_model_failure_keeps_regex_findings_and_fails():
    assert not result.passed and result.findings
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**：YAML 用 `pyyaml`（新增依赖）或手写极简解析——**优先 `pyyaml`**；`match` 用 `re.finditer`，`spans` 为 `(start, end)`。
- [ ] **Step 4: 跑测试确认通过**（6 passed）
- [ ] **Step 5: 提交** `feat(rules): 违禁词规则库 + 守门人（正则先筛，模型判误报）`

---

### Task 6: 接入主链路与 CLI

**Files:**
- Modify: `backend/app/graph/loop.py`、`backend/app/cli.py`、`backend/app/state.py`、`backend/app/schemas.py`（`RunState` 加 `humanized/smell/gate`）
- Test: `backend/tests/test_loop.py`（追加）

**Interfaces:**
- `run_loop` 尾部：`cover → humanize → gate`；`gate` 有 blocking 且非误报 → `run_humanize(hints=[...])` 再修一次（不计轮次）→ `run_gatekeeper` 复核；仍 blocking → `state["status"]="gate_blocked"`。
- `CLI meta` 追加：`cover_text`、`smell{before,after,fidelity}`、`gate_findings`、`changes` 条数。
- 不变式（测试钉住）：`status=="passed"` 时 `gate.passed` 必须为真；`gate_blocked` 时仍输出 `title/body/tags`（稿子照给，标注未过合规）。

- [ ] **Step 1: 写失败的测试**

```python
async def test_full_pipeline_adds_cover_smell_and_gate():
    out = await run_loop(state, deps_full())
    assert out["humanized"] and out["smell"] and out["gate"] is not None
    assert out["draft"].cover_text

async def test_blocking_gate_marks_gate_blocked_and_retries_humanize_once():
    assert calls_for("humanize") == 2
    assert out["status"] == "gate_blocked"

async def test_gate_blocked_still_reports_draft():
    assert out["draft"].body and out["status"] == "gate_blocked"
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**（顺序：cover 在 humanize 之前，因为封面文案会被校订一起改；gate 在最后兜底）
- [ ] **Step 4: 跑测试确认通过** + 全量回归
- [ ] **Step 5: 提交** `feat(loop): 接入封面/人味校订/守门人`

---

### Task 7: 事件落盘与单文件 HTML 报告

**Files:**
- Create: `backend/app/report/trace.py`、`backend/app/report/html.py`、`backend/app/cli.py`（加 `report` 子命令）
- Test: `backend/tests/test_report.py`

**Interfaces:**
- `append_event(path: Path, event: dict) -> None`（JSONL，一行一条，UTF-8）；`read_events(path) -> list[dict]`。
- `render_report(events: list[dict], result: dict) -> str`：返回**完整 HTML 字符串**，CSS/JS 内联，无外链；必须含：标题、封面文案、正文、标签、每轮判定卡（click/save/read_through）、AI 味前后对比、被删词清单、守门人命中项、用量与成本。
- CLI：`python -m app.cli report --trace <path.jsonl> --out <path.html>`。

- [ ] **Step 1: 写失败的测试**

```python
def test_trace_roundtrip(tmp_path): ...
def test_report_is_self_contained():
    html = render_report(EVENTS, RESULT)
    assert html.startswith("<!doctype html>")
    assert "http://" not in html and "https://" not in html   # 无外链
    assert "AI 味" in html and "62" in html

def test_cli_report_writes_file(tmp_path, capsys): ...
```

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**：HTML 用 f-string 模板，正文按 `\n` 转 `<p>`，命中项用 `<mark>` 标红。
- [ ] **Step 4: 跑测试确认通过**（3 passed）
- [ ] **Step 5: 提交** `feat(report): JSONL trace 与单文件 HTML 报告`

---

## 交付验收（初版）

1. `uv run python -m app.cli run --persona scripts/personas/p01.json --topic "…"` 输出含 `cover_text`、`smell`、`gate_findings` 的 JSON。
2. `uv run python -m app.cli report --trace data/traces/<run>.jsonl --out data/report.html` 生成可双击打开的单文件报告。
3. `uv run pytest -q` 全绿；`ruff` / `mypy` 0 error；`xhs-invariants` 6/6。
4. 一次真实 run：`cost_cny < 1.0`、`elapsed_s < 180`。
