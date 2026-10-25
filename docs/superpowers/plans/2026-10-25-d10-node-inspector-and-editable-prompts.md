# D10 节点可见 + prompt 可改 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 七个角色的产物与 prompt 在前端可见、可改，改完整条重跑；每轮 run 自带 prompt 快照，事后能自证用了哪一版。

**Architecture:** 后端加一层 `app/prompts`（默认层=代码常量、覆盖层=`data/prompts.json`、快照层=每次 run 的不可变 `PromptSet`），`Deps.prompts` 成为 agent 取 prompt 的唯一入口；`_step` 从「只推节点名」升级为「推产物 + 耗时 + 花费 + 是否降级」；前端把三栏重排，节点可点开抽屉看产物、看本轮 prompt、编辑下一版。

**Tech Stack:** Python 3.11 + FastAPI + pydantic v2 + pytest；Vue 3 + TS + Pinia + Element Plus + Vite（新增 devDependency `vue-tsc`）。

**Spec:** `docs/superpowers/specs/2026-10-25-node-inspector-and-editable-prompts-design.md`

## Global Constraints

- Python 3.11；**不新增后端运行时依赖**，只用标准库 + 现有的 fastapi / pydantic / openai。
- 前端只加一个 devDependency `vue-tsc`；不引入图表库、diff 库、新 UI 框架。
- prompt 单条上限 **20000 字符**；空串或纯空白一律拒绝。
- 界面文案用中文，错误信息要人能读懂。
- 所有测试必须离线（`FakeLLM` / `httpx2.MockTransport`），不许调用真 API。
- 本机 `uv` 缓存在沙箱下不可写 → 一律用 `.\.venv\Scripts\python.exe -m …` 跑命令。
- 每个任务提交前跑四件套：`pytest -q`、`ruff check app tests`、`mypy app`、`check_invariants.py --root ..`。
- 分支：`feat/d10-node-inspector`，最终 `git merge --no-ff` 回 `main`。

## Review Focus

以下五类输入/失败模式，spec 隐含但任何单个任务的测试都不天然覆盖；每条都已落到具体任务的测试里：

1. 用户把 prompt 改成空白、超长、或给读者塞隔离词 → 必须 422/409，而不是 500、也不能静默写入（Task 2/3）。
2. 守门人不通过时 `finish_draft` 会再跑一次 humanizer+gatekeeper → 一轮 9 条 `node_end`，第二条 `attempt=2`，首条不被覆盖（Task 6）。
3. 读者调用失败走兜底 → 时间线显示「降级」，不是「完成」（Task 5/6）。
4. 关掉编辑器切回旧 run → 看到的是**旧** prompt 与旧产物，不是当前编辑值（Task 9）。
5. 首次启动、无 `data/prompts.json`、run 列表为空 → 页面用默认值正常渲染，不白屏（Task 2/8/9）。

---

### Task 1: `app/prompts` 默认层 + `PromptSet`，agent 改从 `Deps` 取 prompt

**Files:**
- Create: `backend/app/prompts/__init__.py`、`backend/app/prompts/defaults.py`、`backend/app/prompts/set.py`
- Modify: `backend/app/agents/{profile,planner,writer,reader,cover,humanize,gatekeeper}.py`（删常量、改取文本处）
- Modify: `backend/app/llm/client.py:60-67`（`Deps` 加字段）
- Modify: `backend/app/cli.py:35-38`（`build_deps` 加 `prompts` 参数）
- Modify: `backend/app/evaluation/judge.py:12`（导入改到 `app.prompts.defaults`）
- Test: `backend/tests/test_prompts.py`（新建）

**Interfaces:**
- Produces: `ROLES: tuple[str, ...]`（顺序固定 profile/planner/writer/reader/cover/humanizer/gatekeeper）、`DEFAULTS: dict[str, str]`、`prompt_sha8(text: str) -> str`（sha256 前 8 位十六进制）、`PromptSet.defaults() -> PromptSet`、`PromptSet.with_text(role, text) -> PromptSet`、`.text(role) -> str`、`.sha8(role) -> str`、`.record() -> dict[str, dict[str,str]]`、`.edited_roles() -> list[str]`、`Deps.prompts: PromptSet`、`build_deps(prompts: PromptSet | None = None) -> Deps`。

- [ ] **Step 1: 建分支**

```powershell
git checkout main; git checkout -b feat/d10-node-inspector
```

- [ ] **Step 2: 写失败的测试**（`backend/tests/test_prompts.py`）

```python
from app.prompts import DEFAULTS, ROLES, PromptSet, prompt_sha8

def test_seven_roles_in_fixed_order():
    assert ROLES == ("profile", "planner", "writer", "reader", "cover", "humanizer", "gatekeeper")
    assert set(DEFAULTS) == set(ROLES)

def test_default_set_is_all_nonempty_and_sourced_default():
    pset = PromptSet.defaults()
    assert all(pset.text(role).strip() for role in ROLES)
    assert pset.edited_roles() == []

def test_prompt_sha8_is_stable_and_short():
    assert prompt_sha8("abc") == prompt_sha8("abc")
    assert len(prompt_sha8("abc")) == 8

def test_agents_read_prompt_from_deps_state():
    # 用 FakeLLM 跑一次画像官，断言收到的 system 来自 deps.prompts（被覆盖的那份）
    ...
```

最后一个用例的断言方式：构造 `Deps(llm=FakeLLM(expected_card), settings=make_settings(), prompts=PromptSet.defaults().with_text("profile", "改过的画像官 prompt"))`，跑 `run_profile`，断言 `llm.systems[0] == "改过的画像官 prompt"`。

> `PromptSet.with_text(role, text) -> PromptSet` 也要在本任务实现（冻结对象的复制式修改，Task 2 的 store 会用它）。

- [ ] **Step 3: 跑测试，确认失败**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_prompts.py -q`
Expected: `ModuleNotFoundError: No module named 'app.prompts'`

- [ ] **Step 4: 实现**

- `defaults.py`：把七个常量从各 agent 原样搬来（`PROFILE_SYSTEM`/`PLANNER_SYSTEM`/`WRITER_SYSTEM`/`READER_PROMPT`/`COVER_SYSTEM`/`HUMANIZE_SYSTEM`/`GATEKEEPER_SYSTEM`），再给 `ROLES` 与 `DEFAULTS` 两个汇总。
- `set.py`：`PromptSet` 用 `@dataclass(frozen=True, slots=True)`，字段 `texts: Mapping[str,str]`、`sources: Mapping[str, Literal["default","edited"]]`；`__post_init__` 校验七个 role 齐全；`defaults()` 用 `DEFAULTS` + 全 `default`；`with_text()` 复制后把该 role 标 `edited`。
- `__init__.py` 只做 re-export。
- 七个 agent 里 `system=XXX_SYSTEM` 改成 `system=deps.prompts.text("<role>")`，并删掉本地常量。
- `Deps` 加 `prompts: PromptSet = field(default_factory=PromptSet.defaults)`（**必须带默认值**，现有四处 `Deps(...)` 都是关键字构造）。
- `build_deps(prompts=None)`：`None` 时用 `PromptSet.defaults()`（Task 2 再换成读 store）。
- `judge.py` 的 `READER_PROMPT` 改从 `app.prompts.defaults` 导入，行为不变。

- [ ] **Step 5: 跑测试 + 全量回归**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 原 163 passed + 新增 4 passed。

- [ ] **Step 6: 四件套 + 提交**

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m mypy app
cd ..; python .dsh/skills/xhs-invariants/scripts/check_invariants.py --root .
git add backend/app backend/tests
git commit -m "refactor: prompt 收进 app.prompts，七个 agent 从 Deps.prompts 取文本"
```

---

### Task 2: `PromptStore`：持久化 + 校验 + 读者 C3 守卫

**Files:**
- Create: `backend/app/prompts/store.py`
- Modify: `backend/app/prompts/__init__.py`（导出 store 与异常）
- Test: `backend/tests/test_prompts.py`（追加）

**Interfaces:**
- Produces: `PromptStore(path: Path | None = None)`、`PromptStore.default_path() -> Path`（`%XHS_PROMPT_STORE%` 优先，否则 `data/prompts.json`）、`.snapshot() -> PromptSet`、`.set(role, text) -> PromptSet`、`.reset(role: str | None = None) -> PromptSet`、`.items() -> list[dict]`；异常 `PromptError`（基类）、`UnknownPromptRole`、`EmptyPrompt`、`PromptTooLong`、`PromptGuardError(name: str)`；常量 `READER_FORBIDDEN: frozenset[str]`。

- [ ] **Step 1: 写失败的测试**

```python
def test_store_roundtrip_and_reset(tmp_path):
    store = PromptStore(tmp_path / "prompts.json")
    store.set("writer", "新 prompt")
    assert PromptStore(tmp_path / "prompts.json").snapshot().text("writer") == "新 prompt"
    assert store.snapshot().sha8("writer") == prompt_sha8("新 prompt")
    store.reset("writer")
    assert store.snapshot().text("writer") == DEFAULTS["writer"]

def test_store_rejects_unknown_role_empty_and_too_long(tmp_path):
    store = PromptStore(tmp_path / "p.json")
    with pytest.raises(UnknownPromptRole): store.set("nobody", "x")
    with pytest.raises(EmptyPrompt): store.set("writer", "   ")
    with pytest.raises(PromptTooLong): store.set("writer", "x" * 20001)

def test_reader_guard_blocks_isolated_identifiers(tmp_path):
    store = PromptStore(tmp_path / "p.json")
    for word in ("real_material", "angle", "verdicts", "feedback_history", "previous_objections", "taboo"):
        with pytest.raises(PromptGuardError): store.set("reader", f"参考 {word}")
    store.set("writer", "real_material 可以用")   # 其它角色不受限

def test_guard_list_matches_checker():
    # 防止两份清单漂移：读 checker 源码里的 READER_HIDDEN 字面量对比
    ...

def test_snapshot_is_frozen_against_later_edits(tmp_path):
    store = PromptStore(tmp_path / "p.json")
    snap = store.snapshot()
    store.set("writer", "改过的")
    assert snap.text("writer") == DEFAULTS["writer"]
```

`test_guard_list_matches_checker` 用 `re.search(r"READER_HIDDEN = \{(.*?)\}", path.read_text())` 取出词表与 `READER_FORBIDDEN` 对比。

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_prompts.py -q`
Expected: `ImportError` / `AttributeError: PromptStore`

- [ ] **Step 3: 实现**

- 文件格式见 spec §8；`version: 1`、`updated_at`、`overrides`。
- 写入用「写临时文件 + `os.replace`」保证原子；文件缺失或 JSON 坏了 → 当全默认（不要因此起不来）。
- `items()` 返回 spec §7.1 的 `items` 列表（含 `text`/`default_text`/`source`/`sha8`/`updated_at`）。
- `READER_FORBIDDEN` 与 checker 的 `READER_HIDDEN` 同集合（`taboo` 也在内）。

- [ ] **Step 4: 跑测试**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_prompts.py -q`
Expected: 全绿（此时约 10 个用例）。

- [ ] **Step 5: `build_deps` 改读 store + 提交**

`build_deps(prompts=None)`：`prompts or PromptStore().snapshot()`；`cli eval` 的两条构造点（`_swapped_reader`、`_evaluate`）显式传 `PromptSet.defaults()`，并打印「当前有 N 个 prompt 被改过，本次评测仍用默认版」。

```powershell
.\.venv\Scripts\python.exe -m pytest -q; .\.venv\Scripts\python.exe -m ruff check app tests
git add -A backend/app backend/tests
git commit -m "feat: prompt 覆盖层落盘 + 校验 + 读者隔离守卫"
```

---

### Task 3: `/prompts` 接口

**Files:**
- Modify: `backend/app/api/app.py`（`create_app` 加 `prompt_store` 参数 + 四个路由）
- Test: `backend/tests/test_api.py`（追加）

**Interfaces:**
- Consumes: `PromptStore`、`PromptError` 家族（Task 2）。
- Produces: `create_app(*, deps_factory=None, engine="loop", prompt_store: PromptStore | None = None)`；`GET /prompts`、`PUT /prompts/{role}`、`DELETE /prompts/{role}`、`DELETE /prompts`。

- [ ] **Step 1: 写失败的测试**

```python
def test_prompts_endpoint_lists_seven(tmp_path):
    client = _client_with_store(tmp_path)
    body = client.get("/prompts").json()
    assert body["roles"] == list(ROLES)
    assert {item["source"] for item in body["items"]} == {"default"}

def test_put_delete_prompt_roundtrip(tmp_path):
    client = _client_with_store(tmp_path)
    assert client.put("/prompts/writer", json={"text": "新"}).json()["source"] == "edited"
    assert client.delete("/prompts/writer").json()["source"] == "default"
    client.put("/prompts/writer", json={"text": "新"})
    client.delete("/prompts")
    assert all(i["source"] == "default" for i in client.get("/prompts").json()["items"])

@pytest.mark.parametrize("payload,code", [({"text": ""}, 422), ({"text": "   "}, 422), ({"text": "x"*20001}, 422)])
def test_put_prompt_rejects_bad_text(tmp_path, payload, code):
    assert _client_with_store(tmp_path).put("/prompts/writer", json=payload).status_code == code

def test_put_prompt_unknown_role_404_and_reader_guard_409(tmp_path):
    client = _client_with_store(tmp_path)
    assert client.put("/prompts/nobody", json={"text": "x"}).status_code == 404
    response = client.put("/prompts/reader", json={"text": "看看 real_material"})
    assert response.status_code == 409 and "real_material" in response.json()["detail"]
```

`_client_with_store(tmp_path)` 是新 helper：`create_app(prompt_store=PromptStore(tmp_path / "p.json"), deps_factory=factory)`。

- [ ] **Step 2: 跑测试，确认失败**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_api.py -q -k prompt`
Expected: 404（路由不存在）。

- [ ] **Step 3: 实现**

- `PromptUpdate(BaseModel): text: str`（空串交给 store 判，别用 `min_length=1`，否则错误码分不清）。
- 路由里 `try/except PromptError` 映射：`UnknownPromptRole→404`、`PromptGuardError→409`、`EmptyPrompt/PromptTooLong→422`；`detail` 用人话（守卫错误要带上被拦的词）。
- 默认 `prompt_store or PromptStore()`；**不要在 import 时读文件**，测试要能注入。

- [ ] **Step 4: 跑测试 + 提交**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_api.py -q
git add backend/app/api/app.py backend/tests/test_api.py
git commit -m "feat: /prompts 读写接口（含 404/409/422 映射）"
```

---

### Task 4: run 自带 prompt 快照 + `GET /runs` + `GET /runs/{id}/prompts`

**Files:**
- Modify: `backend/app/api/app.py:59-94`、`backend/app/cli.py:59-97`（`result_payload` 加 meta）
- Modify: `backend/app/state.py`（`prompts` 字段）
- Test: `backend/tests/test_api.py`（追加）

**Interfaces:**
- Produces: `state["prompts"]: dict[role, {"text","sha8","source"}]`；`result_payload(...)["meta"]["prompts_edited"]: list[str]`、`["prompts_sha8"]: dict[str,str]`；`GET /runs` → `{"items":[{run_id, topic, status, created_at, prompts_edited}]}`（倒序）；`GET /runs/{run_id}/prompts` → `{"items":[{role, text, sha8, source}]}`。

- [ ] **Step 1: 写失败的测试**

```python
def test_run_records_prompt_snapshot_and_uses_override(tmp_path):
    # PUT /prompts/writer 后再跑 run；断言 FakeLLM 收到的 writer system == 新文本
    ...
    assert client.get(f"/runs/{run_id}/prompts").json()["items"][2]["source"] == "edited"
    assert client.get(f"/runs/{run_id}").json()["meta"]["prompts_edited"] == ["writer"]

def test_run_snapshot_survives_later_prompt_edit(tmp_path):
    # 跑完 run 后 PUT 改 writer，再读 /runs/{id}/prompts，仍是旧文本

def test_list_runs_is_newest_first(tmp_path):
    # 跑两次，断言 items[0]["run_id"] == 第二次
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api.py -q -k "snapshot or list_runs"`
Expected: FAIL（404 / KeyError）。

- [ ] **Step 3: 实现**

- `create_run` 里：`snapshot = prompt_store.snapshot()` → `state["prompts"] = snapshot.record()` → `runs[run_id] = {"state": state, "prompts": snapshot, "created_at": _now()}`。
- `execute()` 里 `deps.prompts = snapshot`（工厂可能又读了一次 store，这里强制覆盖成同一份）。
- `GET /runs` 用 `reversed(runs.items())` 生成摘要；不返回正文。
- `result_payload` 的 meta 加两个键（值从 `state["prompts"]` 推）。
- 可选顺手（别为它单开一轮）：淘汰 run 时一并 `bus` 的历史清掉（`bus.py` 加 `drop(run_id)`），防载荷变大后的既有无界增长。

- [ ] **Step 4: 跑测试 + 提交**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git add backend/app backend/tests/test_api.py
git commit -m "feat: run 带 prompt 快照，新增 /runs 列表与快照读取"
```

---

### Task 5: 降级可见（`mark_degraded` + 四个 agent）

**Files:**
- Modify: `backend/app/state.py`（`degraded_nodes` + `mark_degraded`）
- Modify: `backend/app/agents/reader.py:99-107`、`humanize.py:92-106`、`gatekeeper.py:83-87`、`cover.py:41-46`
- Test: `backend/tests/test_agents_reader.py`（追加）、`backend/tests/test_pipeline_d4.py`（追加）

**Interfaces:**
- Produces: `mark_degraded(state: RunState, node: str, reason: str) -> None`；`state["degraded_nodes"]: list[{"node","round","reason"}]`。

- [ ] **Step 1: 写失败的测试**

```python
def test_reader_failure_marks_degraded():
    ...
    assert state["degraded_nodes"] == [{"node": "reader", "round": 1, "reason": "读者调用失败，按未通过处理"}]
```

- [ ] **Step 2: 跑测试，确认失败** → `KeyError: 'degraded_nodes'`。

- [ ] **Step 3: 实现**

`mark_degraded` 用 `state.setdefault("degraded_nodes", []).append({...})`，`round` 取 `state.get("round", 1)`；四个 agent 在返回兜底产物前各调一次，`reason` 用人话（读者：`读者调用失败，按未通过处理`；人味校订：`校订调用失败，输出改前版本`；守门人：`守门人调用失败，按不放行处理`；封面：`封面调用失败，回落标题前 12 字`）。

- [ ] **Step 4: 跑测试 + 提交**

```powershell
.\.venv\Scripts\python.exe -m pytest -q; .\.venv\Scripts\python.exe -m mypy app
git add backend/app backend/tests
git commit -m "feat: 兜底降级显式记录，避免把失败显示成完成"
```

---

### Task 6: `_step` 事件契约（产物 / seq / attempt / 降级 / 用量差）

**Files:**
- Modify: `backend/app/graph/loop.py:21-29` 与全部 10 处调用点
- Test: `backend/tests/test_loop_events.py`（新建）

**Interfaces:**
- Produces: `_step(state, deps, node, round_no, factory, *, serialize=None)`；`node_start = {event,node,round,attempt,seq}`；`node_end = {event,node,round,attempt,seq,ok,degraded,error?,degraded_reason?,elapsed_ms,usage{prompt_sha8,product?}}`。
- Consumes: `deps.prompts.sha8(role)`（Task 1）、`state["degraded_nodes"]`（Task 5）。

- [ ] **Step 1: 写失败的测试**（spec §10 列的 5 条，逐条一个用例）

```python
def test_full_run_emits_seven_node_end_with_products(events):
    assert {e["node"] for e in events if e["event"] == "node_end"} == set(ROLES)
    assert all(e["product"] is not None for e in events if e["event"] == "node_end")

def test_gate_retry_emits_nine_with_attempt_two(events_gate_blocked):
    ends = [e for e in events_gate_blocked if e["event"] == "node_end"]
    assert len(ends) == 9
    assert [e["attempt"] for e in ends if e["node"] == "gatekeeper"] == [1, 2]

def test_writer_failure_emits_ok_false_without_product(...)
def test_reader_fallback_emits_degraded_true(...)
def test_usage_delta_sums_to_state_total(...)
```

- [ ] **Step 2: 跑测试，确认失败** → `KeyError: 'product'`。

- [ ] **Step 3: 实现**

`_step` 里：`seq = state["node_seq"] = state.get("node_seq", 0) + 1`；`attempt = state["node_attempts"][key] = state["node_attempts"].get(key, 0) + 1`；`perf_counter()` 计耗时；调用前后各取一次 `state.get("usage")` 做字段差；调用前后 `len(state.get("degraded_nodes") or [])` 判降级；异常时先发 `ok:false` 再 `raise`。`serialize` 默认 `lambda v: v.model_dump() if hasattr(v,"model_dump") else v`；主笔传 `lambda pair: {"draft": pair[0].model_dump(), "responses": [r.model_dump() for r in pair[1]]}`；封面传 `lambda text: {"cover_text": text}`。

- [ ] **Step 4: 跑测试 + 全量回归 + 提交**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git add backend/app/graph/loop.py backend/tests/test_loop_events.py
git commit -m "feat: node_end 带产物/耗时/花费/降级/重试序号"
```

---

### Task 7: 报告写入 prompt 快照

**Files:**
- Modify: `backend/app/report/trace.py:22-39`、`backend/app/report/html.py:94-139`
- Test: `backend/tests/test_report.py`（追加）

**Interfaces:**
- Consumes: `state["prompts"]`（Task 4）。
- Produces: trace 事件 `{"event":"prompts","data":{role:{text,sha8,source}}}`（在 `result` 之前）；报告含 `<h2>prompt</h2>` 与每个角色的 `<details>`，`source == "edited"` 时带「已改动」标记。

- [ ] **Step 1: 写失败的测试**

```python
def test_report_contains_prompt_texts_and_edited_badge():
    page = render_report(build_trace(state, payload), payload)
    assert "prompt" in page and "已改动" in page and DEFAULT_WRITER[:20] in page
```

- [ ] **Step 2: 跑测试，确认失败** → 断言不成立。

- [ ] **Step 3: 实现**：`build_trace` 里 `if state.get("prompts"): events.append(...)`；html 里逐角色渲染，`<details>` 默认折叠，正文 `<pre>` 转义。

- [ ] **Step 4: 跑测试 + 提交**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_report.py -q
git add backend/app/report backend/tests/test_report.py
git commit -m "feat: 报告里写入七个 prompt 的全文与来源"
```

---

### Task 8: 前端数据层（类型 / API / store）

**Files:**
- Modify: `frontend/src/types.ts`、`frontend/src/api.ts`、`frontend/src/stores/run.ts`、`frontend/package.json`、`frontend/vite.config.ts:11-14`
- Test: 无单测；以 `pnpm typecheck` + `pnpm build` 为验证

**Interfaces:**
- Produces: `PromptItem`/`PromptsResponse`/`RunSummary`/`NodeEvent` 类型；`fetchPrompts()`、`savePrompt(role,text)`、`resetPrompt(role)`、`resetAllPrompts()`、`fetchRuns()`、`fetchRunPrompts(runId)`；store 暴露 `prompts`、`runPrompts`、`runs`、`nodes`（按 round+attempt 分组）、`loadPrompts/savePrompt/resetPrompt/resetAll/loadRuns/viewRun`。

- [ ] **Step 1: 装 `vue-tsc` 并加脚本**

```powershell
cd frontend; pnpm add -D vue-tsc
```
`package.json` 的 `scripts` 加 `"typecheck": "vue-tsc --noEmit"`；`vite.config.ts` 的 proxy 加 `'/prompts': 'http://127.0.0.1:8000'`。

- [ ] **Step 2: 先写类型与 API 函数**（编译级验证）

按上面 Interfaces 列的形状补齐；`NodeEvent.product` 用 `unknown`，交给组件窄化。

- [ ] **Step 3: 改 store**

`start()` 里记录新 run 并刷新 `runs`；新增 `viewRun(runId)`：拉 `GET /runs/{id}` + `/runs/{id}/prompts` + 订阅事件（已完成 run 会在 `done` 后关闭）；`savePrompt` 成功后刷新 `prompts` 并把该 role 标 `dirty=false`。

- [ ] **Step 4: 验证**

Run: `pnpm typecheck; pnpm build`
Expected: 均成功（此时界面还是旧的，允许）。

- [ ] **Step 5: 提交**

```powershell
git add frontend/package.json frontend/pnpm-lock.yaml frontend/vite.config.ts frontend/src
git commit -m "feat: 前端接通 prompt / run 历史接口，接上 vue-tsc"
```

---

### Task 9: 布局重排 + 节点时间线

**Files:**
- Create: `frontend/src/components/AppHeader.vue`、`NodeTimeline.vue`
- Modify: `frontend/src/App.vue`、`PersonaForm.vue`、`DraftPanel.vue`、`style.css`
- Delete: `frontend/src/components/TimelinePanel.vue`
- Test: 无单测；`pnpm typecheck` + `pnpm build` + 手动 smoke

**Interfaces:**
- Consumes: Task 8 的 store 与类型。
- Produces: `<AppHeader />`（无 props，读 store）、`<NodeTimeline @open="(node: NodeEvent) => …" />`。

- [ ] **Step 1: 重写布局**：`App.vue` 用 grid `300px minmax(0,1fr) 380px`；`AppHeader` 放标题、状态、成本、run 选择器（`store.runs`）、「用当前 prompt 重跑」、prompt 徽标（`已修改 N 个 prompt`）。

- [ ] **Step 2: 节点时间线**：按 `round` 分组，每行 `状态点 / 中文名 / 角色代号 / 耗时 / 花费 / attempt 徽标（>1 显示「复核」）/ 降级黄标`；点击 `emit('open', event)`；无事件时给空态文案。

- [ ] **Step 3: 视觉**：间距 4/8/12/16/24，圆角 10，边框 `#e5e7eb`，页底 `#f7f8fa`，强调色 `#be123c`；`<1100px` 三栏改单栏；等宽字体只用于 prompt 与 JSON。

- [ ] **Step 4: 验证**

Run: `pnpm typecheck; pnpm build`
然后重启后端 → 打开 `http://127.0.0.1:8000` → 跑一次 → 确认七行节点各自状态、耗时、花费都对得上。

- [ ] **Step 5: 提交**

```powershell
git add frontend/src
git commit -m "feat: 三栏重排 + 节点时间线（产物/耗时/花费/降级）"
```

---

### Task 10: 抽屉（产物 / 本轮 prompt / 编辑下一版）+ 契约提醒

**Files:**
- Create: `frontend/src/components/NodeDrawer.vue`、`PromptEditor.vue`、`frontend/src/promptGuard.ts`
- Modify: `frontend/src/App.vue`（挂抽屉）、`frontend/src/stores/run.ts`（`dirty` 与 `openNode`）
- Test: 无单测；`pnpm typecheck` + `pnpm build` + 手动 smoke

**Interfaces:**
- Consumes: Task 8 的 `savePrompt/resetPrompt`、Task 9 的 `@open`。
- Produces: `NodeDrawer(open: boolean, node: NodeEvent | null)`、`PromptEditor(role: string, snapshot: PromptItem | null)`、`contractWarnings(role: string, text: string): string[]`。

- [ ] **Step 1: 抽屉三页签**：「产物」（结构化渲染 `node.product`，未知形状退化成 `<pre>` JSON）、「本轮 prompt（只读）」（来自 `store.runPrompts`，标 `default`/`edited <sha8>`）、「编辑下一版」（`PromptEditor`）。

- [ ] **Step 2: 编辑器**：textarea + 与 `default_text` 的逐行对比（左默认右当前，改动行高亮）+ 保存 / 恢复默认；保存成功后刷新 `store.prompts`，把该 role 标 `dirty=false`。

- [ ] **Step 3: 契约提醒（D10-7）**：`promptGuard.ts` 维护 `{role: [{keyword, hint}]}`——策划 `chosen`/`why_not_others`、主笔 `objection_index`、守门人 `findings`、全部 `JSON`；`contractWarnings` 返回缺失项，编辑器顶部黄条提示「这几条由代码校验，删掉会被重问或直接失败」，**不阻止保存**。

- [ ] **Step 4: 未保存保护**：有 `dirty` 时点「重跑」走 `el-popconfirm` 二次确认。

- [ ] **Step 5: 验证**

Run: `pnpm typecheck; pnpm build`
手动：跑一次 → 点「主笔」→ 改一行 → 保存 → 重跑 → 顶部切回上一版，确认旧 prompt 仍是旧文本、产物仍是旧稿。

- [ ] **Step 6: 提交**

```powershell
git add frontend/src
git commit -m "feat: 节点抽屉 + prompt 编辑（含契约提醒与未保存确认）"
```

---

### Task 11: 文档收尾 + 全量验收

**Files:**
- Modify: `README.md:121-130`、`docs/HANDOFF.md`（状态表与未完成项 A）、`docs/decisions/2026-10-25-node-inspector-rulings.md`（新建）
- Modify: `.dsh/skills/xhs-invariants/SKILL.md`（C1 的「八字段」→「七字段」）

- [ ] **Step 1: 更新 README「界面」小节**：写清「节点可点开、prompt 可改、整条重跑、每次 run 带快照」，并说明「改过 prompt 的 run 不能与 D9 数字对比」。

- [ ] **Step 2: 写裁决记录**：`docs/decisions/2026-10-25-node-inspector-rulings.md`，把 D10-1…D10-12 里真正改变了既有行为的四条（prompt 覆盖层、评测不用覆盖、降级标记、run 列表）记成「为什么这样、代价是什么」。

- [ ] **Step 3: 修技能文档笔误**：C1 表里「Verdict 八字段」改成「七字段」（代码与设计文档都是七个）。

- [ ] **Step 4: 更新 HANDOFF**：第 0 节状态表（测试数、接口数）、第 7 节未完成项 A 划掉并写「已完成 D10，见 specs/2026-10-25-…」。

- [ ] **Step 5: 全量验收**

```powershell
cd backend; .\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m mypy app
cd ..; python .dsh/skills/xhs-invariants/scripts/check_invariants.py --root .
cd frontend; pnpm typecheck; pnpm build
```
Expected: 测试全绿（163 + 新增约 25）；ruff/mypy 无输出；6/6；typecheck/build 成功。

- [ ] **Step 6: 提交 + 合并**

```powershell
git add -A
git commit -m "docs: D10 收尾（README/交接/裁决记录）"
git checkout main; git merge --no-ff feat/d10-node-inspector
```

---

## 验收清单（对应 spec §16）

- [ ] 七个节点在前端各自可点开：有产物、耗时、花费、本轮 prompt、上游跳转
- [ ] 改 prompt → 保存 → 重跑 → 报告里标 `edited`；旧 run 仍显示旧文本
- [ ] `cli eval` 在存在覆盖时仍用默认 prompt 并打印警告
- [ ] 读者降级在界面上显示「降级」
- [ ] `pnpm build` 与 `pnpm typecheck` 都过；四件套全绿
