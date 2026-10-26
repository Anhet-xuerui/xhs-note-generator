"""测试辅助：假 LLM + 常用夹具构造。

放在独立模块而不是 conftest，避免测试之间靠隐式导入互相看见。
"""

from __future__ import annotations

from typing import Any

from app.agents.planner import AngleSet
from app.agents.writer import WriterOutput
from app.config import Settings
from app.llm.client import CallResult, Deps
from app.schemas import (
    Angle,
    Draft,
    PersonaInput,
    ProfileCard,
    RunInput,
    Usage,
)


class FakeLLM:
    """按顺序吐出预设响应；可塞异常来模拟调用失败。"""

    def __init__(self, *responses: Any) -> None:
        self.queue = list(responses)
        self.roles: list[str] = []
        self.users: list[str] = []
        self.systems: list[str] = []
        self.models: list[str | None] = []
        self.max_attempts_seen: list[int | None] = []

    async def structured(
        self, *, role: str, system: str, user: str, schema: type, max_attempts=None, model: str | None = None
    ):
        self.max_attempts_seen.append(max_attempts)
        self.roles.append(role)
        self.users.append(user)
        self.systems.append(system)
        self.models.append(model)
        item = self.queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        if not isinstance(item, schema):
            raise TypeError(f"FakeLLM 排到的是 {type(item).__name__}，与 {schema.__name__} 不符")
        usage = Usage(input_tokens=100, output_tokens=50, cost_cny=0.01, calls=1, elapsed_s=0.5)
        return CallResult(value=item, usage=usage, attempts=1)


def make_settings(**overrides: Any) -> Settings:
    base = {
        "writer_api_key": "w-key",
        "reader_api_key": "r-key",
        "reader_base_url": "https://reader.example/v1",
        "reader_model": "qwen-plus",
    }
    base.update(overrides)
    return Settings(**base)


def deps_with(*responses: Any) -> Deps:
    return Deps(llm=FakeLLM(*responses), settings=make_settings())


def make_persona() -> PersonaInput:
    return PersonaInput(
        nickname="沪漂打工人",
        age_range="25-30",
        city="上海",
        occupation="市场营销",
        goal="涨粉",
        tone=["自嘲", "直给"],
        real_material=["被二房东坑过一个月押金", "中介说这栋楼隔音差"],
        taboo=[],
    )


def make_state(topic: str = "租房第一年") -> dict:
    return {
        "run_id": "run-1",
        "input": RunInput(persona=make_persona(), topic=topic),
        "angle_history": [],
        "draft_history": [],
        "verdicts": [],
        "feedback_history": [],
        "writer_responses": [],
        "round": 0,
        "status": "running",
    }


def make_card() -> ProfileCard:
    return ProfileCard(
        **make_persona().model_dump(),
        anchors=["被二房东坑过一个月押金"],
        can_say=["我跟你说"],
        cannot_say=[],
    )


def make_angles() -> AngleSet:
    return AngleSet(
        angles=[
            Angle(
                hook="把租房踩坑写成清单",
                target_emotion="实用",
                title_candidates=["t1", "t2"],
                chosen=True,
                why_not_others="另外两个太抒情",
            ),
            Angle(hook="b", target_emotion="共鸣", title_candidates=["t3", "t4"], chosen=False, why_not_others="x"),
            Angle(hook="c", target_emotion="好奇", title_candidates=["t5", "t6"], chosen=False, why_not_others="x"),
        ]
    )


def make_writer_output(persona: PersonaInput | None = None) -> WriterOutput:
    """正文里塞进该画像的前两条真实经历——主笔必须用足 real_material。"""
    materials = list((persona or make_persona()).real_material)
    if len(materials) > 1:
        body = f"{materials[0]}。后来才明白，{materials[1]}这句话是什么意思。"
    else:
        body = f"{materials[0]}。那之后我才知道，租房这件事得自己留证据。"
    return WriterOutput(
        draft=Draft(title="租房第三年，我才知道中介不会告诉你的三件事", body=body, tags=["租房", "沪漂"]),
        responses=[],
    )
