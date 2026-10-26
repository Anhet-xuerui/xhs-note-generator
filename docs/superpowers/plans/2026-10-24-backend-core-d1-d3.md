# 后端核心（D1–D3）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 CLI 跑通「画像官 → 策划 → 主笔 → 读者」的单轮闭环与三轮循环，产出可读的笔记 JSON 与 process trace，退出条件全部由代码判定。

**Architecture:** 纯 Python 异步函数式节点，节点之间只通过 `RunState`（TypedDict）交换数据；每个节点的 prompt 由 `app/context.py` 的单角色构造函数生成，该模块是信息隔离的唯一实现处。LangGraph 编排留到 D5，本阶段用手写 `for` 循环 + `decisions.py` 的纯函数，保证每个退出条件都能被单测直接命中。

**Tech Stack:** Python 3.11、pydantic v2、pydantic-settings、openai SDK（兼容协议）、tenacity、pytest + pytest-asyncio、ruff、mypy、uv。

**Spec:** `docs/superpowers/specs/2026-10-23-xhs-multiagent-design.md`

## Global Constraints

- Python `>=3.11,<3.12`；包管理用 `uv`，不用 pip 直接 `install`。
- 不引入 Java/Spring、不做 RAG、不采集任何平台数据、不写爬虫（§3 N1/N2、§17）。
- `Verdict` 与 `Objection` 字段冻结（§7）；`MAX_ROUNDS = 3` 硬编码，不对外开放调高（§7/§17）。
- 读者必须走**独立的 provider 配置**（`READER_*`），不得回落到主模型配置——`READER_*` 缺失时启动即报错（§13「换厂商是机制，不是偏好」）。
- 每个节点失败处理按 §10 的表执行：超时重试 1 次 → schema 不符带错误重问 1 次 → 仍失败则 `degraded`。主笔不降级（run `failed`），守门人不降级（本阶段未实现，D4 接）。
- 单次 run 成本目标 < 1 元人民币（§4）；`Usage` 必须逐调用累计，不得估算。
- `python scripts/check_invariants.py --root .` 必须 `exit 0`（C1–C6）。
- FastAPI 未来引入时必须 `>=0.140`（原生 `fastapi.sse` 提供 `EventSourceResponse`/`ServerSentEvent`，见 D6 计划；本阶段不装）。
- 所有中文 prompt 与字段说明用中文书写；代码标识符与注释语言一致（英文标识符、中文 docstring）。

## Review Focus

1. **模型输出被 JSON 代码围栏（三个反引号 + `json`）包裹，或前后夹解释文字** —— 这是最高频失败。任务 2 的测试必须覆盖：剥围栏后能解析；剥不掉时按「schema 不符」重问一次，而不是抛原始异常。
2. **字段类型漂移**（`read_through: "0.8"`、`click: "true"`、`objections: "{}"`）—— 必须被 pydantic 拒绝并触发重问，禁止 `model_config` 静默强转。任务 2、3 各测一次。
3. **`body` 为空或只有一句** —— 读者拿到的 `sentence_index` 会指向不存在的句子。任务 4 的 `split_sentences("")` 必须返回 `[]`；任务 8 必须断言空稿不崩且 `objections` 为空。
4. **`persona` 边界** —— `taboo` 缺失、`real_material` 只有 1 条、超过 10 条，都必须按约束卡处理而不崩。任务 3、5 覆盖。
5. **三轮全不过** —— 必须交 `score` 最高那轮且 `status="exhausted"`，不能交最后一轮。任务 10 的测试用「第 1 轮分高、第 3 轮分低」的构造数据断言。

---

## 文件结构

```
backend/
├── pyproject.toml                     # uv 工程、依赖、ruff/mypy/pytest 配置
├── .env.example                       # 所有 *_API_KEY 与 provider 变量的占位
├── app/
│   ├── __init__.py
│   ├── config.py                      # Settings + ProviderConfig + 价格表
│   ├── schemas.py                     # 全部 pydantic 契约
│   ├── state.py                       # RunState / RunInput / Usage 累积
│   ├── context.py                     # 单角色上下文构造（隔离唯一实现处）
│   ├── llm/
│   │   ├── __init__.py
│   │   └── client.py                  # structured() 调用 + 重试 + JSON 修复 + 计费
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── profile.py                 # 画像官
│   │   ├── planner.py                 # 策划
│   │   ├── writer.py                  # 主笔
│   │   └── reader.py                  # 读者（含 prompt 模板）
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── decisions.py               # 纯函数：passed/score/needs_new_angle/卡死/上限
│   │   └── loop.py                    # 手写编排：单轮 run 与三轮循环
│   └── cli.py                         # python -m app.cli run --persona ... --topic ...
└── tests/
    ├── conftest.py                    # sys.path + fake LLM 夹具
    ├── test_config.py
    ├── test_llm_client.py
    ├── test_schemas.py
    ├── test_context.py
    ├── test_agents_profile.py
    ├── test_agents_planner.py
    ├── test_agents_writer.py
    ├── test_agents_reader.py
    ├── test_decisions.py
    ├── test_loop.py
    └── test_cli.py
```

**已存在的雏形**（`%TEMP%\xhs-baseline`，由两个基线 subagent 产出）：`context.py`、`schemas.py`（仅 Verdict/Objection）、`agents/reader.py`、`graph/decisions.py`、`tests/test_reader_context.py`、`tests/test_decisions.py`。任务 3、4、8、10 以**移植 + 审查 + 补齐**的方式进行，不重写；移植时必须先读雏形原文，再按本计划的接口对齐。

---

### Task 1: 工程骨架与配置

**Files:**
- Create: `backend/pyproject.toml`, `backend/.env.example`, `backend/app/__init__.py`, `backend/app/config.py`
- Test: `backend/tests/conftest.py`, `backend/tests/test_config.py`

**Interfaces:**
- Produces: `app.config.Settings`（pydantic-settings，`env_file=".env"`），字段
  `writer_base_url: str`、`writer_model: str`、`writer_api_key: str`、`reader_base_url: str`、
  `reader_model: str`、`reader_api_key: str`、`request_timeout_s: float = 60.0`、
  `max_retries: int = 1`，以及 `Settings.load() -> Settings`（读环境变量，缺失 `READER_*` 时抛
  `ReaderNotConfigured`）。
- Produces: `app.config.PRICES: dict[str, tuple[float, float]]`，键为 model 名，值为
  `(输入价, 输出价)`，单位「元 / 百万 token」。填价时必须在注释里写下抓取日期与出处；测试只断言结构，
  不断言具体数值（价格会变，断言数值等于让测试明天就红）。

- [ ] **Step 1: 写失败的测试**

```python
def test_reader_provider_must_be_explicit(monkeypatch):
    monkeypatch.delenv("READER_API_KEY", raising=False)
    with pytest.raises(ReaderNotConfigured, match="READER_"):
        Settings.load()

def test_price_table_is_structured():
    assert "deepseek-chat" in PRICES
    assert all(isinstance(v, tuple) and len(v) == 2 for v in PRICES.values())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 3: 写 `pyproject.toml` 与 `config.py`**

依赖只装本阶段用到的：`pydantic>=2.7`、`pydantic-settings>=2.2`、`openai>=1.40`、`tenacity>=8.3`；
dev 组：`pytest`、`pytest-asyncio`、`ruff`、`mypy`。`[tool.pytest.ini_options] asyncio_mode = "auto"`。
`config.py` 用 `pydantic_settings.BaseSettings` 实现 `Settings`，`READER_API_KEY` 无默认值——
不给「回落到 writer key」的余地；`ReaderNotConfigured(RuntimeError)` 的错误信息里必须写明缺的是哪个变量。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/pyproject.toml backend/.env.example backend/app backend/tests
git commit -m "feat(backend): 工程骨架与 provider 配置"
```

---

### Task 2: LLM 客户端（结构化输出 + 重试 + JSON 修复 + 计费）

**Files:**
- Create: `backend/app/llm/__init__.py`, `backend/app/llm/client.py`
- Test: `backend/tests/test_llm_client.py`

**Interfaces:**
- Produces: `class LLMClient:` 构造签名 `LLMClient(settings: Settings, *, http_client: httpx.AsyncClient | None = None)`；
  方法 `async def structured(self, *, role: str, system: str, user: str, schema: type[TModel]) -> CallResult[TModel]`。
- Produces: `@dataclass CallResult:` 字段 `value: TModel`、`usage: Usage`、`degraded: bool`、`attempts: int`。
- Produces: `@dataclass Deps:` 字段 `llm: LLMClient`、`settings: Settings`。**所有节点只依赖 `Deps`**，
  不自己去读环境变量或构造 SDK 客户端——任务 5–10 的夹具全靠这一条。
- Produces: `tests/conftest.py` 追加夹具：`settings`（假 key 的 `Settings`）、`FakeLLM`
  （`queue: list[BaseModel | Exception]`，`async def structured(...)` 依次弹出、记录 `last_role` 与调用次数）、
  `deps_fake`（`Deps(FakeLLM(...), settings)`），以及各任务专用的 `deps_*` 变体。
- Consumes: `app.schemas.Usage`（Task 3）——本任务先以 `NamedTuple(input_tokens, output_tokens, cost_cny, calls)` 占位，
  任务 3 落地后改为直接引用 `Usage`，这一步在任务 3 的 Step 里完成。
- 行为：`role` 决定用哪组 provider（`"reader"` → `reader_*`，其余 → `writer_*`）；实现 `_extract_json(text)`
  （剥掉 JSON 代码围栏、截取首个 `{` 到末个 `}`）；pydantic 校验失败 → 把 `ValidationError` 原文追加进
  user 消息重问 1 次；超时/连接错误 → tenacity 重试 1 次；两次都失败 → 抛 `NodeCallFailed(role, attempts)`。

- [ ] **Step 1: 写失败的测试**（用 `httpx.MockTransport` 伪造 OpenAI 兼容响应，不打网络）

```python
async def test_strips_code_fence_and_parses(settings, mock_transport):
    FENCE = chr(96) * 3                      # 三个反引号，写成 chr 避免本文件的围栏冲突
    body = f'{FENCE}json\n{{"click": true, "read_through": 0.8}}\n{FENCE}'
    client = LLMClient(settings, http_client=httpx.AsyncClient(transport=mock_transport(body)))
    result = await client.structured(role="reader", system="s", user="u", schema=Verdict)
    assert result.value.click is True and result.attempts == 1

async def test_retries_once_with_validation_error(settings, mock_transport):
    # 第一次 returning {"read_through": "0.8"}（字符串），第二次合法
    result = await client.structured(role="reader", system="s", user="u", schema=Verdict)
    assert result.attempts == 2 and result.usage.calls == 2

async def test_raises_after_two_failures(settings, mock_transport_always_bad):
    with pytest.raises(NodeCallFailed):
        await client.structured(role="reader", system="s", user="u", schema=Verdict)

async def test_cost_is_summed_from_price_table(settings, mock_transport):
    # 假响应声明 input=1000 / output=500 tokens；按 PRICES[model] 算，不写死金额
    result = await client.structured(role="reader", system="s", user="u", schema=Verdict)
    pin, pout = PRICES[settings.reader_model]
    assert result.usage.cost_cny == pytest.approx((1000 * pin + 500 * pout) / 1_000_000)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_llm_client.py -v`
Expected: FAIL — `ImportError: cannot import name 'LLMClient'`

- [ ] **Step 3: 实现 `LLMClient`**

用 `openai.AsyncOpenAI(base_url=..., api_key=..., timeout=..., max_retries=0, http_client=...)`，自己管重试
（SDK 内建重试会掩盖 attempts 计数）。请求带 `response_format={"type": "json_object"}` 与
`messages=[{"role":"system",...},{"role":"user",...}]`；从 `response.usage` 取 token 数，按 `PRICES[model]` 计费，
未登记模型时抛 `UnknownModelPrice`（不要静默按 0 计，否则成本数字是假的）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_llm_client.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/llm backend/tests/test_llm_client.py
git commit -m "feat(llm): 结构化调用客户端（围栏剥离/重问/重试/计费）"
```

---

### Task 3: 数据契约 `schemas.py`

**Files:**
- Create: `backend/app/schemas.py`（移植雏形 + 补齐）
- Test: `backend/tests/test_schemas.py`

**Interfaces:**
- `PersonaInput`：`nickname, age_range, city, occupation, goal: str`；`tone: list[str]`（1–3）；
  `real_material: list[str]`（1–10）；`taboo: list[str] = []`（0–10）。
- `ProfileCard`：`PersonaInput` 全部字段 + `anchors: list[str]`（从 `real_material` 抽取的可复用事实锚点，§8 的
  `fidelity_ok` 依赖它）+ `can_say: list[str]`、`cannot_say: list[str]`。
- `Angle`：`hook, why_not_others: str`；`target_emotion: Literal["焦虑","爽感","共鸣","好奇","实用"]`；
  `title_candidates: list[str]`（2–3）；`chosen: bool`。
- `Draft`：`title, body: str`；`tags: list[str]`；`cover_text: str | None = None`（D4 封面角色写入，本阶段恒为 None）。
- `WriterResponse`：`objection_index: int`、`decision: Literal["accept","reject"]`、`reason: str`。
- `Verdict` / `Objection`：**逐字沿用雏形**（8 字段 / 4 字段，`problem_type` 六值 Literal），不改动。
- `Usage`：`input_tokens, output_tokens: int`、`cost_cny: float`、`calls: int`、`elapsed_s: float`；方法
  `Usage.merge(self, other: "Usage") -> "Usage"`。
- `RunInput`：`persona: PersonaInput`、`topic: str`。

- [ ] **Step 1: 写失败的测试**

```python
def test_real_material_bounds():
    with pytest.raises(ValidationError):
        PersonaInput(nickname="x", age_range="25-30", city="上海", occupation="市场",
                     goal="涨粉", tone=["直给"], real_material=[])

def test_taboo_defaults_to_empty_list():
    p = PersonaInput(nickname="x", age_range="25-30", city="上海", occupation="市场",
                     goal="涨粉", tone=["直给"], real_material=["被二房东坑过押金"])
    assert p.taboo == []

def test_verdict_schema_is_frozen():
    assert set(Verdict.model_fields) == {"click","click_reason","drop_at_sentence",
        "read_through","save","comment_intent","objections"}

def test_usage_merge_sums_all_fields():
    a, b = Usage(10, 5, 0.1, 1, 1.0), Usage(20, 7, 0.2, 2, 2.0)
    assert a.merge(b) == Usage(30, 12, 0.3, 3, 3.0)

def test_angle_requires_exactly_two_to_three_titles():
    with pytest.raises(ValidationError):
        Angle(hook="h", target_emotion="实用", title_candidates=["只有一个"], chosen=True, why_not_others="x")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.schemas'`（或字段缺失）

- [ ] **Step 3: 移植雏形的 `Verdict`/`Objection`，补齐其余契约**

从 `%TEMP%\xhs-baseline\backend\app\schemas.py` 复制这两个类，逐字不改。其余类按上面 Interfaces 写；
`real_material` 用 `Field(min_length=1, max_length=10)`，`tone` 用 `Field(min_length=1, max_length=3)`，
`title_candidates` 用 `Field(min_length=2, max_length=3)`。然后把任务 2 的 `CallResult.usage` 类型改为 `Usage`，
并跑任务 2 的测试回归。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_schemas.py tests/test_llm_client.py -v`
Expected: PASS（5 + 4 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/schemas.py backend/tests/test_schemas.py backend/app/llm/client.py
git commit -m "feat(schemas): 用户画像/角度/稿子/判定卡/用量契约"
```

---

### Task 4: `state.py` 与 `context.py`（信息隔离的唯一实现处）

**Files:**
- Create: `backend/app/state.py`, `backend/app/context.py`（移植雏形 + 修正）
- Test: `backend/tests/test_context.py`（移植 `test_reader_context.py` 并改名）

**Interfaces:**
- `RunState`（TypedDict，键与 §10 一致）：`run_id: str`、`input: RunInput`、`profile: ProfileCard | None`、
  `angle: Angle | None`、`angle_history: list[Angle]`、`round: int`、`draft: Draft | None`、
  `draft_history: list[Draft]`、`verdicts: list[Verdict]`、`feedback_history: list[list[Objection]]`、
  `writer_responses: list[WriterResponse]`、`best_round: int | None`、`status: Literal["running","passed","exhausted","failed"]`、
  `usage: Usage`。
- `build_reader_context(state: RunState) -> dict`、`build_writer_context(state: RunState) -> dict`、
  `build_planner_context(state: RunState) -> dict`、`build_profile_context(state: RunState) -> dict`。
- `split_sentences(text: str) -> list[dict]`，元素形如 `{"index": 1, "text": "…"}`，**1-based**。

- [ ] **Step 1: 写失败的测试**（三条隔离 + 三条边界）

```python
def test_reader_context_hides_real_material_angle_and_history(state): ...   # 移植自雏形
def test_planner_context_has_no_draft(state):          # §6：策划看不到成稿
    ctx = build_planner_context(state)
    assert "body" not in json.dumps(ctx, ensure_ascii=False)
def test_writer_context_has_no_rule_library(state):    # §6：主笔只看到命中项
    assert set(build_writer_context(state)) == {"round","topic","persona","angle",
        "previous_objections","previous_draft","gate_findings"}
def test_split_sentences_of_empty_body_is_empty():
    assert split_sentences("") == []
def test_reader_context_tolerates_single_sentence_body(state):
    state["draft"]["body"] = "就一句话。"
    assert build_reader_context(state)["note"]["sentences"] == [{"index": 1, "text": "就一句话。"}]
def test_context_does_not_require_optional_state_keys(state):  # 缺 angle/profile 时不 KeyError
    minimal = {"input": state["input"], "round": 1}
    assert build_reader_context(minimal)["note"]["body"] == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_context.py -v`
Expected: FAIL — 缺 `build_planner_context` / `build_writer_context`

- [ ] **Step 3: 移植 `context.py` 并按本计划接口修正三处**

修正点（这是与雏形的**有意差异**，不是重写）：
1. 删掉雏形的 `state["previous_objections"]` 兼容分支——§10 的 `feedback_history` 是唯一来源，两份真相会导致漂移；
   取 `feedback_history[-1]`，空则为 `[]`。
2. 读者上下文的 `scene` 不再用硬编码常量兜底：`PersonaInput` 没有该字段，改为在 `build_reader_context`
   里从 `state["input"]` 读取可选 `reading_scene`，缺失则不传该键（不要给模型编造一个场景）。
3. 四个 builder 统一签名 `(state: RunState)`，只吃 state，不再接受 dict/model 双形态（雏形的 `_get`/`_plain`
   双兼容层删除，state 已是唯一数据源）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_context.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/state.py backend/app/context.py backend/tests/test_context.py
git commit -m "feat(context): 四个角色的上下文白名单与三条隔离"
```

---

### Task 5: 画像官节点

**Files:**
- Create: `backend/app/agents/profile.py`, `backend/app/agents/__init__.py`
- Test: `backend/tests/test_agents_profile.py`

**Interfaces:**
- Produces: `async def run_profile(state: RunState, deps: Deps) -> ProfileCard`；`PROFILE_SYSTEM: str`。
- Consumes: `build_profile_context(state)`（Task 4）、`LLMClient.structured`（Task 2）、`ProfileCard`（Task 3）。
- 规则（写进 system prompt，测试只断言结构）：`anchors` 必须逐条来自 `real_material`，不得新增事实；
  `cannot_say` 必须覆盖 `taboo` 的每一条；`can_say` 2–5 条。

- [ ] **Step 1: 写失败的测试**

```python
async def test_profile_card_keeps_every_real_material_item(state, deps_fake):
    card = await run_profile(state, deps_fake)
    assert card.real_material == state["input"].persona.real_material

async def test_anchors_come_from_real_material(state, deps_fake):
    card = await run_profile(state, deps_fake)
    assert card.anchors and set(card.anchors) <= set(state["input"].persona.real_material)

async def test_taboo_is_carried_into_cannot_say(state_with_taboo, deps_fake):
    card = await run_profile(state_with_taboo, deps_fake)
    assert set(state_with_taboo["input"].persona.taboo) <= set(card.cannot_say)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_agents_profile.py -v`
Expected: FAIL — `ImportError: run_profile`

- [ ] **Step 3: 实现 `run_profile`**

`PROFILE_SYSTEM` 三句话：你是画像官；把画像原文压成结构化约束卡，`anchors` 只能从 `real_material` 里逐条摘取、
不得新增或改写事实；`taboo` 要展开成 `cannot_say`。函数体三步：取 context → `structured(schema=ProfileCard)`
→ 用 `real_material` 覆盖模型回填的同名字段（防它改写原料），再校验 `anchors ⊆ real_material`，不满足则重问一次。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_agents_profile.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/agents backend/tests/test_agents_profile.py
git commit -m "feat(agents): 画像官节点"
```

---

### Task 6: 策划节点（3 个角度 + 自选 + 必须写清为什么不选）

**Files:**
- Create: `backend/app/agents/planner.py`
- Test: `backend/tests/test_agents_planner.py`

**Interfaces:**
- Produces: `async def run_planner(state: RunState, deps: Deps) -> Angle`；`PLANNER_SYSTEM: str`；
  内部模型 `AngleSet(BaseModel)`：`angles: list[Angle]`（`min_length=3, max_length=3`）。
- 返回 `Angle` 的取法：`next(a for a in set.angles if a.chosen)`；**不得取 `angles[0]`**（§7「顺序不该有语义」）。

- [ ] **Step 1: 写失败的测试**

```python
async def test_picks_chosen_not_first(state, deps_planner_shuffled):
    angle = await run_planner(state, deps_planner_shuffled)   # 假模型把 chosen 放在第 3 个
    assert angle.hook == "第三个角度"

async def test_rejects_zero_or_two_chosen(state, deps_planner_two_chosen):
    with pytest.raises(PlannerContractError, match="chosen"):
        await run_planner(state, deps_planner_two_chosen)

async def test_planner_context_has_no_draft(state):
    # 与 Task 4 的 context 测试呼应，这里断言节点实际喂给模型的内容
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_agents_planner.py -v`
Expected: FAIL — `ImportError: run_planner`

- [ ] **Step 3: 实现 `run_planner`**

验证 `sum(a.chosen for a in angles) == 1`，否则抛 `PlannerContractError`（重问一次仍不满足则抛）。
`why_not_others` 为空字符串也视为违约——§7 要求「强制写出为什么不选另外两个」。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_agents_planner.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/agents/planner.py backend/tests/test_agents_planner.py
git commit -m "feat(agents): 策划节点（三角度自选）"
```

---

### Task 7: 主笔节点

**Files:**
- Create: `backend/app/agents/writer.py`
- Test: `backend/tests/test_agents_writer.py`

**Interfaces:**
- Produces: `async def run_writer(state: RunState, deps: Deps) -> tuple[Draft, list[WriterResponse]]`；
  `WRITER_SYSTEM: str`；内部模型 `WriterOutput(BaseModel)`：`draft: Draft`、`responses: list[WriterResponse]`。
- 规则：首轮 `responses` 必须为空列表；后续轮 `responses` 覆盖上一轮**每一条** `Objection`，
  按 `feedback_history[-1]` 的顺序以 `objection_index` 对应；缺项即违约。

- [ ] **Step 1: 写失败的测试**

```python
async def test_first_round_has_no_responses(state_round1, deps_writer):
    draft, responses = await run_writer(state_round1, deps_writer)
    assert responses == [] and draft.body

async def test_every_objection_gets_a_response(state_round2, deps_writer):
    _, responses = await run_writer(state_round2, deps_writer)
    assert [r.objection_index for r in responses] == [0, 1, 2]      # 顺序与上一轮 objections 一致

async def test_missing_response_is_rejected(state_round2, deps_writer_partial):
    with pytest.raises(WriterContractError, match="objection_index"):
        await run_writer(state_round2, deps_writer_partial)

async def test_body_uses_at_least_two_real_material_items(state_round2, deps_writer):
    draft, _ = await run_writer(state_round2, deps_writer)
    hits = sum(1 for m in state_round2["input"].persona.real_material if m[:6] in draft.body)
    assert hits >= 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_agents_writer.py -v`
Expected: FAIL — `ImportError: run_writer`

- [ ] **Step 3: 实现 `run_writer`**

校验 `responses` 的 `objection_index` 集合等于 `{0..n-1}`（n = 上一轮 objections 数），缺项/多项抛
`WriterContractError`。第一轮强制 `responses=[]`，若模型仍给了回应，直接丢弃并记 `degraded`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_agents_writer.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/agents/writer.py backend/tests/test_agents_writer.py
git commit -m "feat(agents): 主笔节点（逐条回应上一轮异议）"
```

---

### Task 8: 读者节点（prompt 移植 + 降级）

**Files:**
- Create: `backend/app/agents/reader.py`（移植雏形）
- Test: `backend/tests/test_agents_reader.py`

**Interfaces:**
- Produces: `async def run_reader(state: RunState, deps: Deps) -> Verdict`；`READER_PROMPT: str`（雏形原文）。
- 行为：`role="reader"`（走 `READER_*` provider）；`NodeCallFailed` 时，若 `state["verdicts"]` 非空则返回
  `state["verdicts"][-1]` 并标 `degraded`；为空则返回一个 `save=False, click=False, read_through=0.0` 的
  兜底 `Verdict`（§10「第 1 轮就失败则直接走未通过路径」）。
- 校验：`Objection.quote` 必须能在正文里找到（`quote in body`），否则丢弃该条 objection 并记 `degraded`
  ——模型会编句子号，这层必须在代码里挡。

- [ ] **Step 1: 写失败的测试**

```python
async def test_reader_uses_reader_provider(state, deps_capture): 
    await run_reader(state, deps_capture)
    assert deps_capture.last_role == "reader"

async def test_degrades_to_previous_verdict(state_with_two_verdicts, deps_failing):
    verdict = await run_reader(state_with_two_verdicts, deps_failing)
    assert verdict is state_with_two_verdicts["verdicts"][-1]

async def test_degrades_to_failing_verdict_on_round_one(state_round1, deps_failing):
    verdict = await run_reader(state_round1, deps_failing)
    assert (verdict.click, verdict.save, verdict.read_through) == (False, False, 0.0)

async def test_drops_objections_whose_quote_is_not_in_body(state, deps_hallucinated_quote):
    verdict = await run_reader(state, deps_hallucinated_quote)
    assert verdict.objections == []

async def test_empty_body_does_not_crash(state_empty_draft, deps_reader):
    verdict = await run_reader(state_empty_draft, deps_reader)
    assert verdict.objections == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_agents_reader.py -v`
Expected: FAIL — `ImportError: run_reader`

- [ ] **Step 3: 移植并加降级与引文校验**

从 `%TEMP%\xhs-baseline\backend\app\agents\reader.py` 复制 `READER_PROMPT` 与 `render_reader_prompt`，逐字不改
（prompt 一旦跑过评测就属于冻结物，§12）。在外面包一层 `run_reader` 做 provider 选择、降级与 `quote in body` 过滤。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_agents_reader.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/agents/reader.py backend/tests/test_agents_reader.py
git commit -m "feat(agents): 读者节点（独立 provider + 降级 + 引文校验）"
```

---

### Task 9: 单轮编排与 CLI

**Files:**
- Create: `backend/app/graph/loop.py`, `backend/app/cli.py`, `backend/scripts/personas/p01.json`（1 个示例画像）
- Test: `backend/tests/test_loop.py`（单轮部分）、`backend/tests/test_cli.py`

**Interfaces:**
- Produces: `@dataclass Deps:` 字段 `llm: LLMClient`、`settings: Settings`。
- Produces: `async def run_once(state: RunState, deps: Deps) -> RunState`——画像官 → 策划 → 主笔 → 读者，
  更新 `state` 的 `profile/angle/draft/verdicts/feedback_history/round/usage` 并返回。
  **主笔抛 `NodeCallFailed` 时置 `status="failed"` 并直接返回，`draft` 保持 `None`**（§10：没有稿子就没有意义）。
- Produces: `async def run_loop(state: RunState, deps: Deps) -> RunState`（本任务先实现「一轮后停」，
  循环在任务 10 补全；函数签名不变）。
- Produces: `app.cli.main(argv=None) -> int`；子命令 `run --persona <path> --topic <str>`，
  stdout 输出结果 JSON（`title/body/tags/status/meta`），失败时 `exit 1`。
  `meta` 由 state 计算：`rounds_used=len(state["verdicts"])`、`best_round`、`usage`，
  外加 `failed_checks`（从 `decisions.evaluate(last_verdict)` 取）。

- [ ] **Step 1: 写失败的测试**

```python
async def test_run_once_fills_every_state_field(state, deps_full_fake):
    out = await run_once(state, deps_full_fake)
    assert out["profile"] and out["angle"] and out["draft"]
    assert len(out["verdicts"]) == 1 and out["round"] == 1
    assert out["usage"].calls == 4                     # 画像官/策划/主笔/读者各一次

async def test_writer_failure_marks_run_failed(state, deps_writer_failing):
    out = await run_once(state, deps_writer_failing)     # 主笔抛 NodeCallFailed
    assert out["status"] == "failed" and out["draft"] is None

async def test_cli_writes_result_json(tmp_path, monkeypatch, capsys, deps_full_fake):
    monkeypatch.setattr(cli, "build_deps", lambda: deps_full_fake)
    code = cli.main(["run", "--persona", str(PERSONA), "--topic", "租房第一年"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] in {"passed", "exhausted", "failed"}

def test_cli_missing_persona_file_returns_1(capsys):
    assert cli.main(["run", "--persona", "nope.json", "--topic", "x"]) == 1
    assert "nope.json" in capsys.readouterr().err
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_loop.py tests/test_cli.py -v`
Expected: FAIL — `ImportError: run_once`

- [ ] **Step 3: 实现 `run_once` 与 CLI**

CLI 用 `argparse`（本阶段不引 typer/click）。结果 JSON 用 `json.dumps(..., ensure_ascii=False, indent=2)`。
`build_deps()` 是唯一构造 `Settings.load()` + `LLMClient` 的地方，测试通过 monkeypatch 替换它，避免打网络。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_loop.py tests/test_cli.py -v`
Expected: PASS（3 + 3 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/loop.py backend/app/cli.py backend/scripts backend/tests
git commit -m "feat(loop): 单轮编排与 CLI 入口"
```

---

### Task 10: 三轮循环、退出条件与卡死检测

**Files:**
- Modify: `backend/app/graph/loop.py`（补全 `run_loop`）
- Create: `backend/app/graph/decisions.py`（移植雏形 + 审查）
- Test: `backend/tests/test_decisions.py`（移植，65 → 保留全部）、`backend/tests/test_loop.py`（追加）

**Interfaces:**
- Consumes: 雏形的 `passed`、`score`、`needs_new_angle`、`detect_stuck`、`round_cap_reached`、
  `pick_best_round`、`decide(verdicts, angle_history) -> LoopDecision`。**保留其公开签名**，只在必要时改。
- Produces: `run_loop` 保证的不变式（测试逐条断言）：
  1. `len(state["verdicts"]) <= 3`
  2. `status == "passed"` ⟺ 最后一轮 `passed(verdict)` 为真
  3. 未通过时 `best_round == pick_best_round(verdicts)`，且输出稿子是那一轮
  4. `status == "exhausted"` 时 `meta` 里必须能读到未达标项

- [ ] **Step 1: 写失败的测试**

```python
async def test_stops_on_pass(deps_pass_at_round_two):
    out = await run_loop(state, deps_pass_at_round_two)
    assert out["status"] == "passed" and len(out["verdicts"]) == 2

async def test_returns_best_round_not_last(deps_scores_high_then_low):
    out = await run_loop(state, deps_scores_high_then_low)   # 第1轮分高、第3轮分低
    assert out["status"] == "exhausted" and out["best_round"] == 1
    assert out["draft"] is out["draft_history"][0]

async def test_stuck_on_two_identical_verdicts(deps_identical_verdicts):
    out = await run_loop(state, deps_identical_verdicts)
    assert len(out["verdicts"]) == 2 and out["status"] == "exhausted"

async def test_new_angle_at_most_once(deps_hook_weak_twice):
    out = await run_loop(state, deps_hook_weak_twice)
    assert len(out["angle_history"]) == 2

async def test_never_exceeds_three_rounds(deps_always_fails):
    out = await run_loop(state, deps_always_fails)
    assert len(out["verdicts"]) == 3
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_loop.py -v`
Expected: FAIL — 循环只跑一轮，`len(verdicts) == 1`

- [ ] **Step 3: 移植 `decisions.py` 并补全 `run_loop`**

从 `%TEMP%\xhs-baseline\backend\app\graph\decisions.py` 整体移植；审查重点：`decide()` 的判定顺序必须是
通过 → 一级卡死 → 二级卡死 → 轮次上限 → `needs_new_angle` → `continue`。`run_loop` 用 `while` + `decide()`，
每轮把 `draft` 追加进 `draft_history`、把 `objections` 追加进 `feedback_history`，`needs_new_angle` 为真时
调一次 `run_planner` 并把旧角度推进 `angle_history`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_decisions.py tests/test_loop.py -v`
Expected: PASS（测试数 = 移植的 decisions 测试 + 5 个新循环测试）

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph backend/tests/test_decisions.py backend/tests/test_loop.py
git commit -m "feat(loop): 三轮循环、退出条件与两级卡死"
```

---

### Task 11: 收尾校验

**Files:**
- Modify: `backend/pyproject.toml`（加 `[tool.pytest.ini_options] markers = ["live: 需要真实 API"]`）
- Create: `backend/tests/test_live_smoke.py`（`@pytest.mark.live`，默认不跑）

**Interfaces:**
- 无新接口。`@pytest.mark.live` 的用例在 `uv run pytest -m "not live"` 下必须跳过。

- [ ] **Step 1: 写测试**

```python
@pytest.mark.live
async def test_real_run_produces_valid_note():
    out = await run_loop(build_state(PERSONA, "租房第一年我终于搞清楚的事"), build_deps())
    assert out["status"] in {"passed", "exhausted"}
    assert out["usage"].cost_cny < 1.0
    assert 100 <= len(out["draft"].body) <= 1200
```

- [ ] **Step 2: 跑全量（不打网络）+ 契约校验**

Run: `cd backend && uv run pytest -m "not live" -q`
Expected: 全绿
Run: `python scripts/check_invariants.py --root .`
Expected: `6 项检查：6 通过 / 0 违规`，`exit 0`

- [ ] **Step 3: 手动跑一次真实调用（可选，需你配好 `.env`）**

Run: `cd backend && uv run python -m app.cli run --persona scripts/personas/p01.json --topic "租房第一年我终于搞清楚的事"`
Expected: 打印结果 JSON，`meta.usage.cost_cny < 1.0`

- [ ] **Step 4: 提交**

```bash
git add backend/pyproject.toml backend/tests/test_live_smoke.py
git commit -m "test: live 冒烟用例与收尾校验"
```

---

## 交付验收（D3 结束时应能演示）

1. `uv run python -m app.cli run --persona scripts/personas/p01.json --topic "…"` 打印出完整笔记 JSON。
2. `uv run pytest -m "not live" -q` 全绿，覆盖三条隔离、两级卡死、`needs_new_angle`、`best_round`、降级路径。
3. `xhs-invariants` 六条规则全过。
4. 一次真实 run 的 `usage.cost_cny < 1.0`。
