"""读者：换一家厂商的模型，看不到写作意图，只回答六个可数字段（§6/§7）。

prompt 文本一旦跑过评测就属于冻结物（§12），改动前先想清楚：改它等于让 E1/E2 作废。
本节点额外做两件事，都在代码里而不是提示词里：

1. 调用失败时降级：有历史判定就沿用上一轮，第 1 轮就失败则按未通过处理（§10）；
2. 引文校验：`Objection.quote` 必须真出现在正文里，否则丢弃——模型会编句子。
"""

from __future__ import annotations

import json

from app.context import build_reader_context
from app.llm.client import Deps, NodeCallFailed
from app.schemas import Verdict
from app.state import RunState, merge_usage

READER_PROMPT = """你是这篇小红书笔记的读者。你不是编辑，不是审稿人，也不认识作者。

【你现在的状态】
你的年龄、城市、职业见 reader_profile。你不是从业者，不负责评价写作技巧，
只负责如实说出你读到哪、想不想点、会不会存。

【你要做的事】
像平常刷推荐流一样，先看标题和封面字，决定要不要点开；然后读正文。
读完填一张判定卡。不要写读后感，不要给写作建议以外的空话。

【判定规则】
1. click：只看标题 + 封面字，你在信息流里会不会点开。不要说「看内容而定」。
2. drop_at_sentence：读到第几句会划走。句子编号见 note.sentences，从 1 开始；
   如果看完了就填 null。
3. read_through：你实际读完了多少，0 到 1 之间的小数。
4. save：以后遇到同样的事，你会不会翻出来照着做。
5. comment_intent：你会不会想在评论区说点什么。
6. objections：只针对具体句子，每条必须指向 note.sentences 里真实存在的编号；
   quote 必须是原文字段。problem_type 只能取这六个之一：
   ai_smell（像 AI 写的、空泛套话）、no_evidence（说了结论却没有依据或细节）、
   unclear（读不懂在说什么）、too_long（啰嗦、可以砍）、
   wrong_tone（语气不对、不像这个人在说话）、hook_weak（开头抓不住人）。
   没有问题就给空列表，不要为了显得认真而编造问题。

【禁止】
- 不要替作者解释他为什么这么写，也不要假设他有什么经历。
- 不要用「整体不错」「有点平淡」这类不可数的评价，判定卡里每个字段都要能数出来。
- 不要因为题材不感兴趣就一律给低分，也不要因为读着顺就放行。
- 不要输出 JSON 以外的任何文字。

【输出格式】
只输出一个 JSON 对象，结构如下：
{
  "click": true,
  "click_reason": "为什么点 / 不点",
  "drop_at_sentence": null,
  "read_through": 0.0,
  "save": false,
  "comment_intent": false,
  "objections": [
    {
      "sentence_index": 1,
      "quote": "原文片段",
      "problem_type": "ai_smell",
      "suggestion": "具体怎么改"
    }
  ]
}"""


def render_reader_prompt(context: dict) -> str:
    """把编号句子的笔记正文渲染成 user 消息。"""
    return "【这条笔记】\n" + json.dumps(context, ensure_ascii=False, indent=2)


def _fallback_verdict() -> Verdict:
    return Verdict(
        click=False,
        click_reason="读者调用失败，按未通过处理",
        read_through=0.0,
        save=False,
        comment_intent=False,
        objections=[],
    )


def _drop_hallucinated(verdict: Verdict, body: str) -> Verdict:
    verdict.objections = [o for o in verdict.objections if o.quote and o.quote in body]
    return verdict


async def run_reader(state: RunState, deps: Deps) -> Verdict:
    context = build_reader_context(state)
    try:
        result = await deps.llm.structured(
            role="reader",
            system=READER_PROMPT,
            user=render_reader_prompt(context),
            schema=Verdict,
        )
    except NodeCallFailed as exc:
        # 失败的那几次调用也花了钱，必须并进用量，否则成本被系统性低估（评审 C1）。
        merge_usage(state, exc.usage)
        state.setdefault("degraded_rounds", []).append(state.get("round", 1))
        history = state.get("verdicts") or []
        # 降级：沿用上一轮判定；第 1 轮就失败则按未通过路径走（§10）。
        fallback = history[-1] if history else _fallback_verdict()
        state.setdefault("verdicts", []).append(fallback)
        return fallback

    merge_usage(state, result.usage)
    draft = state.get("draft")
    body = draft.body if draft else ""
    verdict = _drop_hallucinated(result.value, body)
    state.setdefault("verdicts", []).append(verdict)
    return verdict
