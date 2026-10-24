# 小红书多角色笔记生成系统 — 设计文档

日期：2026-10-23
状态：已定稿，待实施
版本：v2（本地运行版）

---

## 1. 这是什么

给一份**用户画像**和一个**主题**，七个角色在一个受控的讨论循环里互相挑刺，产出一篇可以直接发的小红书图文笔记（标题、正文、标签、封面文案）。同时把「多角色讨论到底比单次生成好在哪，值不值这个成本」做成一个可复现的实验结论。

这个项目有两层目标，缺一不可：

- **产品目标**：产出的是能真发的稿子，不是 demo 文案。
- **项目目标**：这是作者应聘 AI Agent 岗位的作品。它要经得起面试官追问「为什么这么设计」，而不只是看起来热闹。

第二层目标决定了本文档里很多看起来「多余」的选择——比如为什么坚持信息隔离、为什么坚持做评测、为什么坚持不做自动发布。也决定了本版的两个明确取舍：**在本地运行**、**不采集平台真实数据**。这两条削弱了什么、拿什么补，见第 12 节和第 17 节。

## 2. 为什么（问题的根因拆解）

单次 prompt 生成的小红书稿有一组稳定出现的问题，各有各的根因，一个根因对应一个角色：

| 症状 | 根因 | 对应设计 |
|---|---|---|
| 一眼 AI 味：抽象形容词堆砌、没有具体细节 | 画像只被当成 prompt 前缀，没有被转成「这个人能说什么、不能说什么」 | **画像官**：把画像压成结构化约束卡，`real_material` 是硬性原料 |
| 角度平庸、同质化 | 角度选择和执行写作耦合，改稿救不回错角度 | **策划**：独立出角度，判定不通过时可回到桌面 |
| 自我评价偏宽松（模型给自己的稿子打高分） | 评价者与被评价者同模型、同上下文 | **读者**：换一家厂商模型、看不到写作意图、判定必须量化成字段 |
| 标题不错，但封面文案平，没人点 | 「三秒抓眼」是独立手艺，和写正文是两种活 | **封面**：只看标题与首句，牺牲信息量换点击 |
| 改了一版还是像 AI 写的 | 加法（找观点、用素材）和减法（删抽象词、拆长句）挤在同一个上下文里互相干扰 | **人味校订**：先程序化算 AI 味分，再按命中项做减法 |
| 踩违禁词、极限词 | 合规是硬规则，不该靠模型记忆 | **守门人**：规则库先筛，模型只判定与改写 |

**差异化不在技术栈。** LangGraph 和 RAG 现在是入场券，人人都有。这个项目真正稀缺的是两样东西：一组**结构化的判定信号**（判定卡 + 判别力验证），和一组**敢给负面结论的消融实验**。

## 3. 目标 / 非目标 / 反目标

### 目标

- **G1** 给定画像和主题，**标准模式** 3 分钟内产出完整笔记（标题、封面文案、正文、标签）；**极速模式** 40 秒内出稿。
- **G2** 全过程可观察：每个角色的结构化产物、每轮稿子的 diff、判定卡的变化、AI 味分数的变化。
- **G3** 判定卡被证明**有判别力**：读者能把好稿、平庸稿、烂稿排出正确顺序，且两家不同厂商的模型判定一致。
- **G4** 给出「多角色 vs 单角色」的消融结论，包含 token、时延、成本。

### 非目标

- **N1** 不做自动发布，不接小红书账号 API。
- **N2** 不写爬虫、不采集平台数据、不录入真实笔记。评测用的稿件全部由系统生成或人工构造。
- **N3** 不做多用户、账号体系、付费、权限。
- **N4** 不做图片生成。封面只出文案，配图留给用户或固定模板。
- **N5** 不做公网部署、不做域名、不做限流。本项目本地运行。

### 反目标（即使功能跑通也算失败）

- **A1** 七个角色看到同一段 context、说着同样的话——那只是一个模型自我对话了七次。
- **A2** 过程界面漂亮，但关掉页面流程就跑不下去，或者换到命令行跑不了。
- **A3** 结论只写「效果好」，没有对照组、没有成本数字。
- **A4** 为了演示效果，把一个 2 分钟能跑完的流程拖成 8 分钟。
- **A5** 为了显得严谨，编造或暗示拥有并不存在的真实互动数据。

## 4. 约束

- 单人开发，约 10 个工作日。
- 作者技术栈：Vue、Python、Java、Spring/Spring Boot。后端用 Python（模型生态与 LangGraph 都在 Python 侧），前端用 Vue 3。**本项目不引入 Java/Spring**——单人作品里放两套后端语言，面试官第一反应是「为什么」而不是「厉害」。
- **赛道不固定**：任何主题都能跑。因此没有赛道专属的样本库和规则类别，规则库只覆盖跨赛道通用的合规类别。
- 模型预算：单次 run 控制在 1 元人民币以内；整个项目（含评测）预算 100 元。
- 运行方式：本地 `docker compose up` 一键起，浏览器打开 `localhost` 即可。

## 5. 输入与输出

### 输入

```json
{
  "persona": { ... },
  "topic": "租房第一年我终于搞清楚的事"
}
```

画像字段（`taboo` 可为空，其余必填）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `nickname` | string | 人设身份，如「沪漂第三年的市场岗打工人」 |
| `age_range` / `city` / `occupation` | string | 定位人群的基本盘 |
| `tone` | string[1..3] | 语气词，如「自嘲、直给、偶尔文艺」 |
| `real_material` | string[1..10] | **真实经历碎片**，一句话一条。这是反 AI 味的原料，缺了它整套系统会退化成套模板 |
| `taboo` | string[0..10] | 不能说的：公司名、隐私、不能承诺的效果 |
| `goal` | string | 这篇想拿到什么（涨粉/表达/带货铺垫），影响钩子强度 |

### 输出

```json
{
  "title": "租房第三年，我才知道中介不会告诉你的三件事",
  "cover_text": "中介没说的三件事",
  "body": "……（300–800 字）",
  "tags": ["租房", "沪漂", "独居生活", "租房避坑", "租房经验"],
  "meta": {
    "rounds_used": 2,
    "status": "passed",
    "best_round": 2,
    "verdicts": [ ... ],
    "smell": { "before": 62, "after": 28, "fidelity": "passed" },
    "gate_findings": [ ... ],
    "usage": { "input_tokens": 0, "output_tokens": 0, "cost_cny": 0.0, "elapsed_s": 0 }
  }
}
```

`status` 取值：`passed` / `exhausted`（三轮未完但输出最高分版）/ `gate_blocked` / `failed`。

## 6. 七个角色与信息食谱

角色数量本身不是重点，关键是**谁看到什么**。判断一个角色该不该独立存在，只过一道检验：**信息食谱是否与其他角色不同、判断标准是否会跟别人冲突**。两个条件都满足才留。

> 原本设计的第 8 个角色「侦察」（看爆款样本、归纳钩子模式）已删除。本项目不采集平台样本，它的信息食谱就退化成「模型的品味」，与策划重复——留着它只是噪音。这条删除本身要写进 README，面试官会问「为什么不是八个」。

| 角色 | 看得到 | 看不到 | 输出 | 判断标准 |
|---|---|---|---|---|
| 画像官 | 画像原文 + 主题 | — | `ProfileCard` | 完整、可执行、不脑补 |
| 策划 | 约束卡 + 上一轮的判定卡 | **成稿全文** | `Angle[]`：3 个角度，自选 1 个 | 差异化，不给同质化角度 |
| 主笔 | 约束卡全量 + 选定角度 + 上一轮 `Objection[]` | 规则库全文 | `Draft` + `WriterResponse[]` | 具体、像人话、用足 `real_material` |
| 封面 | 标题、正文首句、`tone` | 正文全篇 | `cover_text`（≤12 字） | 三秒抓眼，可牺牲信息量 |
| 读者 | 成稿全文 + 画像的**读者侧**字段（年龄/城市/职业/刷手机场景） | `real_material`、策划意图、历史 `Objection` | `Verdict` + `Objection[]` | 我是刷到这条的陌生人，不是审稿人 |
| 人味校订 | 定稿全文 + **画像卡全文** + AI 味检测报告 | 读者历史意见、策划意图 | `HumanizedDraft` + `ChangeLog[]` | 只做减法，不改事实 |
| 守门人 | 校订后的全文 + 规则库 | 画像 | `GateResult` | 合规是二值的，没有「差不多」 |

三条隔离是有意为之，实现时必须保证：

1. **读者看不到 `real_material`。** 它要判断的是「读起来像不像真人」，不是「作者是不是真经历过」。给了原料它会替作者打同情分。
2. **策划看不到成稿。** 它只看判定卡。看到稿子它会开始替稿子辩护——这是模型最稳定的行为之一。
3. **主笔看不到规则库全文。** 只看到守门人反馈的具体命中项，否则它会为了绕规则把句子写得又长又空。

实现方式：每个节点的 prompt 由 `context_builder(role, state)` 生成，**只允许读取白名单字段**。这一层要有单测：断言「读者节点的输入里不含 `real_material`」等三条，防止后续改动悄悄破坏隔离。

## 7. 主循环

```
画像官 → 策划（出 3 个角度，自选 1 个并说明为何弃其他）
round = 1..3:
    策划  （仅当 needs_new_angle 时；最多重开 1 次）
    主笔  → Draft vN + 逐条回应上一轮 Objection（accept / reject + 理由）
    封面  → cover_text
    读者  → Verdict + Objections
    if verdict.passed: break
if 未通过: 取 score 最高的那一轮作为 best
人味校订 → AI 味检测 → 按命中项改写 → 事实保真校验 → HumanizedDraft
守门人 → 若有 blocking 命中：人味校订带命中项再修一次（不计入轮次）→ 守门人复核
输出
```

### 角度怎么选

策划一次出 3 个角度，**由策划自己选 1 个，并强制写出「为什么不选另外两个」**。代码取 `angle.chosen`，不取 `angles[0]`——顺序不该有语义。

这是有意的偷懒：让选择者和评判者统一（读者选角度）更干净，但要多一次调用，而且读者没读正文时对标题的判断本来就不准。先用自选跑通；如果你在评测里发现「策划选的角度读者点击率明显偏低」，再换成「读者对 3 个标题做一次快速打分」。这个改动只需替换一个节点，不影响其他部分。

```python
class Angle(BaseModel):
    hook: str                    # 一句话概括这个切入角度
    target_emotion: Literal["焦虑", "爽感", "共鸣", "好奇", "实用"]
    title_candidates: list[str]  # 2-3 个标题
    chosen: bool                 # 恰好一个为 True
    why_not_others: str          # 必须非空
```

### 判定卡

```python
class Objection(BaseModel):
    sentence_index: int
    quote: str
    problem_type: Literal[
        "ai_smell", "no_evidence", "unclear", "too_long", "wrong_tone", "hook_weak"
    ]
    suggestion: str

class Verdict(BaseModel):
    click: bool                   # 信息流里我会点开吗
    click_reason: str
    drop_at_sentence: int | None  # 第几句划走；None 表示看完
    read_through: float           # 0..1
    save: bool
    comment_intent: bool
    objections: list[Objection]
```

判定必须是**可数的字段**，不能是「我觉得还不错」。这是系统能收敛的前提，也是它能在第 12 节被检验的前提。

### 通过条件（硬编码，不让模型自己说「可以了」）

```python
blocking = [o for o in verdict.objections if o.problem_type in {"ai_smell", "no_evidence"}]
passed = verdict.click and verdict.save and verdict.read_through >= 0.6 and not blocking
```

### 评分（用于未通过时选最佳轮）

```python
score = 3*verdict.click + 4*verdict.save + 2*verdict.comment_intent \
        + 2*verdict.read_through - 0.5*len(blocking)
```

权重是拍出来的初始值，依据只有一个：「收藏」比「点赞」更能代表内容有用，所以给到 4。第 12 节有一项敏感性检查——权重上下浮动 30%，看三档稿的排序是否稳定。不稳定就在报告里写明「结论对权重敏感」，不假装它客观。

### 收敛与防抖

- 轮次硬上限 3，不对外开放调高。
- **卡死检测（两级）**：
  - 一级：连续两轮 `Verdict` 与 `objections` 完全相同 → 终止。
  - 二级：`score` 连续两轮无提升（差值 ≤ 0）→ 终止。读者每轮看到的是不同稿子，一级条件在实践中几乎不成立，二级才是实际生效的那个。
- 策划重开角度最多 1 次，且必须给出「上一版角度错在哪」，不接受无理由换向。

### 什么时候算「角度错了」（needs_new_angle）

读者被禁止看策划意图，也看不到角度本身，所以它不会说「你角度错了」——判定卡里六种 `problem_type` 全是句子级的。这个信号**必须由代码判定，不能交给模型**：

```python
def needs_new_angle(round: int, verdict: Verdict, angle_history: list[Angle]) -> bool:
    if round < 2 or len(angle_history) >= 2:
        return False
    return (not verdict.click) and (verdict.read_through < 0.3) and any(
        o.problem_type in {"hook_weak", "wrong_tone"}
        for o in verdict.objections
        if o.sentence_index <= 3
    )
```

即：第二轮仍未通过、且问题集中在开头三句的钩子或语感上 → 认为换句子救不回来，允许重开一次角度。

> **冻结约束**：读者节点的 prompt 与 `Verdict` schema 必须在第 12 节的评测开跑之前定稿。改动 schema 等于让全部评测结果作废、重跑。

### 未通过怎么办

不交最后一版，交**分数最高的一版**，并在结果和界面上标注未达标项（例：`未达标：读者在第 3 句划走，read_through 0.42`）。失败也是一条可解释的结果，不是白跑三分钟。

## 8. 人味校订（AI 味清理）

位置：主笔与读者的循环结束之后、守门人之前。它是**最后一个动笔的角色**，但不是最后一个角色——它改写可能引入违禁词，守门人必须在它后面兜底。

### 为什么它是独立角色

主笔在做加法：找观点、用素材、搭结构、控节奏。人味校订在做减法：删抽象词、拆长句、把形容词换成动作和数字。同一个上下文里同时做加法和减法，模型会两头都不彻底。这是它单独存在的全部理由。

### 它凭什么改：先算分，再改

它的输入是一份 **AI 味检测报告**，不是一句「让这篇文章更自然」。检测全部可程序化，不依赖模型判断：

| 特征 | 检测方式 |
|---|---|
| 抽象名词密度 | 词表匹配：焦虑、成长、治愈、松弛感、边界感、内耗 |
| 四字词 / 成语密度 | 分词后按词长与词性统计 |
| 典型 AI 句式 | 正则：`不是…而是…`、`这不仅…更是…`、`愿你…`、`其实…`、`本质上…` |
| 段落长度过于均匀 | 段长标准差低于阈值 |
| 缺具体锚点 | 全文无数字、无时间、无地点、无直接引语 |
| emoji 分布规律化 | 每段收尾都是 emoji |

```python
class SmellHit(BaseModel):
    category: Literal["abstract_noun", "idiom_density", "ai_pattern",
                      "uniform_paragraph", "no_anchor", "emoji_rhythm"]
    spans: list[tuple[int, int]]
    examples: list[str]
    penalty: float

class SmellReport(BaseModel):
    score: int                     # 0-100，越高越像 AI
    hits: list[SmellHit]
```

模型只按 `hits` 改写，不许自由发挥。前端把 `AI 味 62 → 28` 和被删掉的词并排显示——这是仅次于稿子 diff 的第二个画面。

### 它看画像卡，但只用来对齐语气

输入包含画像卡全文（`tone`、`real_material`、`taboo`），用来决定「这个人会怎么说话」。这带来一个风险：它可能把稿子往「人设模板」方向拽。因此配三条硬约束，违反即回退：

```python
def fidelity_ok(before: str, after: str, profile: ProfileCard) -> bool:
    return (
        extract_numbers(before) == extract_numbers(after)                # 数字集合不变
        and extract_proper_nouns(before) == extract_proper_nouns(after)  # 专名不变
        and all(anchor in after for anchor in profile.anchors)           # 素材锚点不丢
        and 0.85 <= len(after) / len(before) <= 1.15                     # 长度 ±15%
    )
```

### 输出

```python
class ChangeLog(BaseModel):
    before: str
    after: str
    category: str        # 对应 SmellHit.category
    reason: str

class HumanizedDraft(BaseModel):
    title: str
    cover_text: str
    body: str
    tags: list[str]
    smell_before: int
    smell_after: int
    changes: list[ChangeLog]
    fidelity: Literal["passed", "reverted", "skipped"]
```

`fidelity: reverted` 时，**输出改写前的版本**（即 `smell_after == smell_before`），`changes` 保留供前端展示「它想改但被拦下了什么」，`meta.smell.reverted_reason` 记下违反的是哪一条约束。回退不重试——重试只会烧钱，改写失败一次就接受原稿。

## 9. 守门人

规则库用 YAML 维护，人工可扩。因为赛道不固定，规则只覆盖**跨赛道通用**的类目：

```yaml
- id: absolute-claim
  patterns: ["最", "第一", "唯一", "100%", "彻底", "保证"]
  severity: blocking
  hint: 换成主观表达或具体范围
- id: medical-efficacy
  patterns: ["治疗", "祛痘", "见效", "排毒"]
  severity: blocking
- id: diversion
  patterns: ["加微信", "私信我", "VX", "vx", "评论区扣1"]
  severity: blocking
- id: body-length
  rule: 300 <= len(body) <= 800
  severity: warning
- id: tag-count
  rule: 3 <= len(tags) <= 8
  severity: warning
```

流程是**正则先筛 → 模型只做两件事**：判断命中项是否为误报、给改写建议。不让模型自己去「记住」违禁词。

`Absolute-claim` 里的「最 / 第一」会有大量误报（「最后」「第一次」）。误报判定正是交给模型的那一半工作，这也是这个角色值得存在的原因——纯正则做不了，纯模型不可靠。

## 10. 架构

```
xhs-agent/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口
│   │   ├── cli.py               # 命令行入口（等价的另一条调用路径）
│   │   ├── api/runs.py          # POST /runs, GET /runs/{id}, GET /runs/{id}/events, /report
│   │   ├── graph/
│   │   │   ├── state.py         # RunState (TypedDict)
│   │   │   ├── nodes.py         # 7 个角色节点
│   │   │   ├── edges.py         # 条件边：是否需要新角度、是否继续、是否取最优
│   │   │   └── build.py         # 编译图 + SqliteSaver
│   │   ├── agents/              # 每个角色的 prompt 模板 + pydantic schema
│   │   ├── context.py           # context_builder：按白名单裁剪输入（隔离的实现处）
│   │   ├── llm/                 # client：重试、超时、JSON 校验失败重问、usage 计数
│   │   ├── rules/               # 违禁词 YAML + 正则引擎（守门人用）
│   │   ├── humanize/            # AI 味检测器 + 事实保真校验（人味校订用）
│   │   ├── store/               # sqlite（runs/events）+ JSONL trace
│   │   └── events.py            # 事件总线：内存队列 + 落盘
│   ├── tests/
│   └── pyproject.toml
├── frontend/                    # Vue 3 + Vite + TS
├── eval/                        # 三档稿、评测脚本、报告
├── docs/
└── docker-compose.yml
```

### State

```python
class RunState(TypedDict):
    run_id: str
    input: RunInput
    profile: ProfileCard | None
    angle: Angle | None
    angle_history: list[Angle]
    round: int
    draft: Draft | None
    draft_history: list[Draft]
    verdicts: list[Verdict]
    feedback_history: list[list[Objection]]
    writer_responses: list[WriterResponse]
    best_round: int | None
    humanized: HumanizedDraft | None
    smell: SmellReport | None
    gate: GateResult | None
    status: Literal["running", "passed", "exhausted", "gate_blocked", "failed"]
    usage: Usage
```

LangGraph 用 `SqliteSaver` 做 checkpointer，每次 run 可中断、可续跑、可回放。**状态必须显式**——这是选 LangGraph 的理由，不是「因为它流行」。

### 事件协议（SSE）

```
event: node_start  data: {"run_id": "...", "node": "writer", "round": 2, "ts": 0}
event: token       data: {"node": "writer", "text": "…"}
event: node_end    data: {"node": "writer", "round": 2, "payload": {...}, "usage": {...}}
event: round_end   data: {"round": 2, "verdict": {...}, "passed": true}
event: done        data: {"status": "passed", "result": {...}}
```

`node_end.payload` 是结构化产物，前端直接渲染成卡片，不解析自然语言。

### API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/runs` | 提交画像和主题，返回 `run_id`，异步开跑 |
| GET | `/runs/{id}/events` | SSE 订阅事件流 |
| GET | `/runs/{id}` | state 快照，断线重连用 |
| POST | `/runs/{id}/override-verdict` | 人工修改判定后继续 |
| GET | `/runs/{id}/report` | 导出 markdown / HTML 全过程报告 |

> **实现坑**：`EventSource` 只支持 GET。所以生成必须拆成两步——先 `POST /runs` 拿 id，再 `EventSource('/runs/{id}/events')`。

> **override-verdict 的实现方式**：不引 LangGraph 的 `interrupt`，用「写入 state → 从 checkpoint 恢复」的普通补丁实现。API 表面不变，风险低。

### 失败与降级

每个节点按同一套规则处理失败，不写特例：

| 情况 | 处理 |
|---|---|
| 调用超时（默认 60s） | 重试 1 次，仍失败则该节点 `degraded` |
| 返回不合 pydantic schema | 带错误信息重问 1 次（最常见的情况），仍失败则 `degraded` |
| 主笔失败 | run 标记 `failed`，不产出半成品——没有稿子就没有意义 |
| 读者失败 | 沿用上一轮 `Verdict` 并标注 `degraded`，循环继续；第 1 轮就失败则直接走「未通过」路径 |
| 策划 / 封面失败 | 用兜底值（封面取标题前 12 字；角度取已有 `angle_history` 最后一个）并标注 |
| 人味校订失败 | 跳过，输出改写前版本，`fidelity: skipped` |
| 守门人失败 | **不降级**，直接 `gate_blocked`——不能因为模型挂了就放行合规 |

原则：**能降级的降级并留痕，不能降级的失败。** 合规判定和成稿本身属于后者。

### 本地运行

不做公网部署，因此没有 nginx、域名、备案、限流、日预算。`docker-compose.yml` 两个服务：

- `backend`：uvicorn 单进程，挂载 `./data` 存 SQLite 与 trace
- `frontend`：`vite build` 后的静态产物，由 backend 直接托管，省掉一个容器

打开 `http://localhost:8000` 即可。开发时前后端分离跑（Vite dev server 代理到 8000）。

## 11. 前端

单页三栏，不做多页路由。

- **左栏 输入**：画像 8 个字段的表单 + 主题输入；高级选项折叠（极速模式、展示轮数）。预置 3 个示例画像，点一下就能跑。
- **中栏 过程**：阶段时间线。每个角色一张卡片，卡片内容是结构化产物——约束卡、三个角度（标出选中哪个及理由）、稿子、判定卡三数字、人味校订（`AI 味 62 → 28` + 被删词清单）、守门人命中项（正文里标红）。
- **右栏 稿子**：`v1 / v2 / v3` 版本切换，内联 diff，读者指出的句子高亮；最右一版是校订后的定稿，可一键切换「改前 / 改后」对比。
- **底部 判定表**：每轮一列，并排看 `click / save / read_through` 的变化，最后一列显示通过与否。

演示开关：**极速模式**跳过 token 流，直接出结果；**演示模式**每个节点留约 1 秒呼吸。

## 12. 评测

本版没有真实互动数据，因此评测换了三个能自证的实验。核心问题从「判定器像不像真实用户」改成了「**判定器有没有判别力、是不是可复现**」——这是一个更弱但能诚实回答的问题。

### E1 判别力测试（construct validity）

**这是本版替代「真实数据校准」的核心实验。**

- **构造三档稿**：每个主题下各一篇好、平庸、烂。
  - `good`：系统跑通的成稿（`status == passed`）
  - `mid`：同一主题的第 1 轮未通过稿
  - `bad`：用一个**反向 prompt** 生成——明确要求「多用抽象形容词、多用排比、不要出现任何具体数字和场所、结尾加一句升华」。这个 prompt 本身就是对「AI 味」的可操作定义，值得单独在 README 里展示。
- **规模**：10 个主题 × 3 档 = 30 篇。几乎零人工。
- **方法**：让读者对 30 篇评分，统计「三档排序正确率」——即 `score(good) > score(mid) > score(bad)` 的比例，以及 Kendall τ。
- **判据**：排序正确率 ≥ 80% 视为判定器有判别力；< 60% 视为无效，需要重新设计判定卡。
- **敏感性检查**：评分权重上下浮动 30%，重算排序正确率；若结论反转，如实写「结论对权重敏感」。

### E2 双厂商一致性（reliability）

- 同一批 30 篇，让**两家不同厂商**的模型都当读者。
- 指标：`click` / `save` 两个二值字段的 Cohen's κ；`score` 的 Spearman ρ。
- 判据：κ ≥ 0.6 视为一致性可接受。
- 这条回答的是「判定卡衡量的是文本属性，还是某个模型的偏好」。也是「为什么读者必须换厂商」这个设计的直接证据。

### E3 消融对照

三组，各 20 个画像-主题对：

| 组 | 配置 |
|---|---|
| A | 裸模型单次成稿（无角色、无循环） |
| B | 完整七角色循环（含人味校订） |
| C | 七角色循环，但读者与主笔同模型 |

指标：pass 率、平均 score、token 总量、时延、成本、`smell_before → smell_after`。

> **评分口径必须统一**：A 组本身没有 `Verdict`，所以所有组的成稿都由**同一个读者实例**事后打分。循环只影响「稿子怎么产出」，不影响「稿子怎么被评判」——不写死这条，A/B 的 pass 率就不可比，整个消融没有意义。A 组的成本要额外计入这次评分调用，报告里单独标注。

### E4 人工盲评（可选，若时间允许）

15 篇（三组各 5 篇，来源打乱），作者自己盲评 5 分制三项：像不像真人写的、有没有具体细节、会不会收藏。这是整套评测里唯一的人类信号，有它比没有强。不做也成立，但要在报告里写明「无人工信号」这一局限。

### 数据与复现

- `eval/` 里存三档稿的生成脚本与结果、评测脚本、报告。
- 每次跑评测记录**读者 prompt 文件的 hash** 与模型版本。否则「你改过 prompt 之后还叫同一组数据吗」答不上来。
- 全部数据均为系统生成，**不含任何真实用户内容**。

## 13. 技术栈

**后端**

| 用途 | 选型 | 备注 |
|---|---|---|
| 运行时 | Python 3.11 | |
| Web | FastAPI + uvicorn | async 原生 |
| 编排 | LangGraph + `SqliteSaver` | state 显式、可回放、可中断 |
| 校验 | pydantic v2 | 判定卡必须是 model |
| 模型 | `openai` SDK（兼容协议）+ `tenacity` | 换 base_url 即换厂商 |
| 流式 | `sse-starlette` | |
| 分词 | `jieba` | AI 味检测需要中文分词 |
| 存储 | SQLite（`runs`/`events`）+ JSONL trace | 不引 Postgres/Redis |
| 配置 | `pydantic-settings` + `.env` | key 不入库 |
| 统计 | `scipy`（Kendall τ / Spearman）、`statsmodels` 或手写 Cohen's κ | 只在 `eval/` 里用 |
| 测试 | `pytest` + `pytest-asyncio` | 覆盖退出条件、轮次上限、卡死检测、上下文隔离、JSON 重试 |
| 质量 | `ruff` + `mypy` | CI 绿标很便宜 |

**前端**

| 用途 | 选型 |
|---|---|
| 框架 | Vue 3 + TS + Vite（`<script setup>`） |
| 状态 | Pinia |
| 组件 | Element Plus |
| 流 | 原生 `EventSource`（两步：POST 拿 id → 订阅） |
| diff | `jsdiff` |
| 图表 | ECharts（评测结果、成本对比） |
| Markdown | `markdown-it` |

**模型分工**

| 角色 | 模型 |
|---|---|
| 画像官、策划、主笔、封面、人味校订、守门人 | DeepSeek |
| 读者 | **Qwen 或 GLM（另一家厂商）** |

「换厂商」是防自我附和的核心机制，代码里必须真的是两个 provider，不是两个 temperature。E2 直接测这一点。

**成本估算**：单次 run 约 13–14 次调用、3.3 万 token 上下，成本不到 1 元。评测总量（30 篇 × 2 家 + 60 次消融 run）几十元。

**运行**：`docker compose up`，浏览器开 `localhost:8000`。

**命令行入口**（满足 A2：关掉页面也能跑）：

```
python -m app.cli run --persona eval/personas/p03.json --topic "租房第三年才知道的事"
```

## 14. 作品集呈现

本地运行意味着**面试官点不开你的 demo**。这是明确付出的代价，靠三样东西补：

1. **5 分钟录屏**（不是 GIF——GIF 撑不住完整流程，只能当第一屏的引子）。开头十秒必须是这一幕：读者说「第 4 句划走」→ 第 2 轮那句被改 → 判定卡从 `no/no` 翻成 `yes/yes`。
2. **一键启动**：`docker compose up` + 一句「3 个预置画像，点开即跑」。
3. **一份导出的 HTML 报告**：一次真实 run 的全过程 + 评测结果，可以直接在浏览器里点开看，不需要跑代码。

**README 第一屏四样东西**，顺序不能换：一句话是什么 + 10 秒 GIF + 录屏链接 + 一个带成本的数字（例：「20 组画像上，多角色循环把读者通过率从 X% 提到 Y%，代价是 4.7 倍 token」）。

**README 正文五节**：是什么 / 三条关键设计决策（信息隔离、换厂商读者、规则先筛模型后改）/ 评测结果与消融表 / 怎么跑起来 / **局限**。

「局限」这一节必须有，而且要写具体：

- 没有真实互动数据，判定器的有效性只有内部验证（判别力 + 一致性），**不能证明它等同于真实用户**。
- 三档稿的 `bad` 档是用反向 prompt 构造的，它定义的是「我们能想到的 AI 味」，不是全部。
- 标签级、选题级的效果没有验证。
- 单赛道禁止，导致没有赛道专属规则和样本。
- 三轮上限是拍的。

主动写出缺点，比被面试官问出来强一个量级——它证明你知道自己在做什么。

另备一页 A4 的「设计决策与取舍」，可直接从本文档第 6–9 节压缩，面试投屏用。

## 15. 里程碑（10 个工作日）

| 天 | 交付 |
|---|---|
| D1–2 | 骨架；画像官 → 策划 → 主笔 → 读者单轮跑通（无循环、无前端）。**同批完成**：读者 prompt 与 `Verdict` schema 定稿冻结、`context_builder` 白名单与隔离单测 |
| D3 | 循环、判定、退出条件、两级卡死检测、`needs_new_angle` 单测 |
| D4 | 封面、人味校订、守门人 + AI 味检测器与事实保真校验 |
| D5 | LangGraph 化 + checkpointer + 事件总线 |
| D6 | 前端时间线 + SSE 打通 |
| D7 | 稿子 diff + 导出报告 + CLI 入口 |
| D8 | 本地 docker compose 打通 + 5 分钟录屏 |
| D9 | E1 判别力 + E2 一致性 + E3 消融 |
| D10 | README、报告整理、A4 决策页 |

D9 之前没有评测数据不许写「效果好」。

## 16. 风险与预案

| 风险 | 预案 |
|---|---|
| E1 判别力测试不通过（读者分不开三档） | 这是真结论，照写。改法：判定卡换成两两比较（直接问「这两篇哪篇更想收藏」），比绝对打分容易做对 |
| 三档稿构造费时 | 10 个主题砍到 6 个（18 篇），仍能算排序正确率 |
| 三轮通过率过低 | 放宽阈值，但报告里如实写通过率，不修饰 |
| 时延超 3 分钟 | 极速模式；封面与正文并行 |
| `Absolute-claim` 规则误报太多 | 把「最/第一」降为 `warning`，只保留「100%/保证/唯一」为 blocking |
| 人味校订把稿子改成人设模板 | 事实保真校验（数字/专名/素材锚点/长度）硬拦截，违反即回退；`fidelity: reverted` 在界面可见 |
| 单人 10 天做不完 | 砍 D7 的导出报告、砍 E4 人工盲评、三档稿从 10 个主题降到 6 个 |

## 17. 已定的取舍

评审时可以直接反对：

- **本地运行，不做公网部署。** 代价是面试官点不开 demo，用录屏 + HTML 报告补偿。
- **不采集任何平台真实数据，不做爬虫。** 代价是判定器只有内部验证，没有外部效度。这条必须写进 README 的「局限」。
- **删除「侦察」角色。** 没有样本库，它的信息食谱与策划重合。角色数定为 7。
- **赛道不固定**，规则库只保留跨赛道通用类目。
- SQLite 而非 Postgres——单人作品不需要。
- 不做 RAG——没有检索需求，硬塞像到处找钉子。
- 不引 Java/Spring。
- 前端选 Element Plus 而非 Naive UI——生态更熟。
- 读者用另一家厂商模型——这是机制，不是偏好。
- 轮次上限 3 不对外开放调高。
- **`needs_new_angle` 用代码启发式判定**，不给 `Verdict` 加角度级字段——读者在结构上就不该看到角度。
- **卡死检测加二级触发**（分数连续两轮无提升），因为一级条件在实践中几乎不成立。
- **`override-verdict` 用普通状态补丁**，不引 LangGraph `interrupt`。
- **角色数封顶 7。** 第 8 个角色必须同时过两道检验：信息食谱与所有现有角色都不同，且判断标准会与至少一个现有角色冲突。过不了就是噪音。这条要写进 README。
- **角度由策划自选**（强制写「为什么不选另外两个」），不引入第四个裁判节点。
- **AI 味检测用规则实现，模型只按命中项改写**，与守门人同构。`AI 味分数`进前端，也进 E3 的指标表。

## 18. 待定（需要作者决定）

1. **第二家厂商具体用哪家**（Qwen / 通义 DashScope、智谱 GLM，或其他）。读者和 E2 的第二个 judge 都用它，选一次就定死，中途换会让 E2 作废。
2. **E4 人工盲评做不做**：15 篇、约 20 分钟。做，评测多一个人类信号；不做，README 里多一条局限。
3. **预置示例画像写哪三个**：最好覆盖三个差别大的场景（打工人 / 学生 / 宝妈之类），演示时一眼看出「换画像就换人设」。
