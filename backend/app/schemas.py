"""数据契约（设计文档 §5 输入输出、§7 判定卡）。

`Verdict` / `Objection` 逐字沿用雏形实现，字段**冻结**：改动等于让 D9 的全部评测结果作废（§7）。
`Usage` 是内部累加器、不来自模型输出，所以用 dataclass 而不是 pydantic 模型。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

ProblemType = Literal[
    "ai_smell",
    "no_evidence",
    "unclear",
    "too_long",
    "wrong_tone",
    "hook_weak",
]

TargetEmotion = Literal["焦虑", "爽感", "共鸣", "好奇", "实用"]


class Objection(BaseModel):
    """针对具体一句的反对意见。sentence_index 从 1 开始，对应正文句子编号。"""

    sentence_index: int = Field(ge=1, description="第几句，1-based")
    quote: str = Field(min_length=1, description="原文摘句，必须能在正文里对上")
    problem_type: ProblemType
    suggestion: str = Field(min_length=1, description="怎么改，具体到句子")


class Verdict(BaseModel):
    """读者判定卡：全部是可数字段，不许出现「我觉得还不错」。"""

    click: bool = Field(description="信息流里我会点开吗")
    click_reason: str = Field(default="", description="点 / 不点的理由")
    drop_at_sentence: int | None = Field(
        default=None, ge=1, description="第几句划走；None 表示看完了"
    )
    read_through: float = Field(ge=0.0, le=1.0, description="读完比例 0..1")
    save: bool = Field(description="会不会收藏")
    comment_intent: bool = Field(description="会不会想评论")
    objections: list[Objection] = Field(default_factory=list)


class PersonaInput(BaseModel):
    """用户画像原文（§5）。`real_material` 是反 AI 味的硬性原料，缺了整套系统退化成套模板。"""

    nickname: str = Field(description="人设身份，如「沪漂第三年的市场岗打工人」")
    age_range: str
    city: str
    occupation: str
    goal: str = Field(description="这篇想拿到什么（涨粉 / 表达 / 带货铺垫）")
    tone: list[str] = Field(min_length=1, max_length=3, description="语气词")
    real_material: list[str] = Field(min_length=1, max_length=10, description="真实经历碎片")
    taboo: list[str] = Field(default_factory=list, max_length=10, description="不能说的")


class ProfileCard(PersonaInput):
    """画像官产物：把画像压成「这个人能说什么、不能说什么」的约束卡（§6）。"""

    anchors: list[str] = Field(
        default_factory=list, description="从 real_material 摘取的事实锚点，§8 保真校验依赖它"
    )
    can_say: list[str] = Field(default_factory=list, description="这个人会说的话 / 口癖")
    cannot_say: list[str] = Field(default_factory=list, description="不能说的（taboo 展开）")


class Angle(BaseModel):
    """策划产物。一次出三个，自选其一，并强制写清为什么不选另外两个（§7）。"""

    hook: str = Field(description="一句话概括这个切入角度")
    target_emotion: TargetEmotion
    title_candidates: list[str] = Field(min_length=2, max_length=3)
    chosen: bool
    why_not_others: str


class Draft(BaseModel):
    title: str
    body: str
    tags: list[str]
    cover_text: str | None = Field(default=None, description="D4 封面角色写入；D1–D3 恒为 None")


class WriterResponse(BaseModel):
    """主笔对上一轮某条反对意见的回应（§6：accept / reject + 理由）。"""

    objection_index: int = Field(ge=0, description="对应上一轮 objections 的下标，0-based")
    decision: Literal["accept", "reject"]
    reason: str


SmellCategory = Literal[
    "abstract_noun",
    "idiom_density",
    "ai_pattern",
    "uniform_paragraph",
    "no_anchor",
    "emoji_rhythm",
]


class SmellHit(BaseModel):
    """一类 AI 味命中（§8）。spans 是 Python 字符下标，不是字节。"""

    category: SmellCategory
    spans: list[tuple[int, int]] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    penalty: float


class SmellReport(BaseModel):
    score: int = Field(ge=0, le=100, description="0–100，越高越像 AI")
    hits: list[SmellHit] = Field(default_factory=list)


class ChangeLog(BaseModel):
    """一处改写：改了什么、为什么改。被回退时也保留，供前端展示「想改但被拦下了」。"""

    before: str
    after: str
    category: str
    reason: str


class HumanizedDraft(BaseModel):
    """人味校订的产物。fidelity=reverted 时正文是**改写前**的版本（§8）。"""

    title: str
    cover_text: str | None = None
    body: str
    tags: list[str] = Field(default_factory=list)
    smell_before: int = Field(ge=0, le=100)
    smell_after: int = Field(ge=0, le=100)
    changes: list[ChangeLog] = Field(default_factory=list)
    fidelity: Literal["passed", "reverted", "skipped"]


class GateFinding(BaseModel):
    """一条合规命中。`false_positive` 由模型判定，其余由正则给出。"""

    rule_id: str
    severity: Literal["blocking", "warning"]
    matched: str
    span: tuple[int, int]
    false_positive: bool = False
    hint: str = ""


class GateResult(BaseModel):
    passed: bool
    findings: list[GateFinding] = Field(default_factory=list)


class RunInput(BaseModel):
    persona: PersonaInput
    topic: str = Field(min_length=1)


@dataclass(slots=True)
class Usage:
    """累计用量。字段顺序即构造顺序，Task 2 的客户端按此累加。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_cny: float = 0.0
    calls: int = 0
    elapsed_s: float = 0.0

    def merge(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cost_cny + other.cost_cny,
            self.calls + other.calls,
            self.elapsed_s + other.elapsed_s,
        )
