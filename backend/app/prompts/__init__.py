"""prompt 的三层：默认（代码）→ 覆盖（data/prompts.json）→ 快照（每次 run）。

agent 只碰 `Deps.prompts`，不直接 import 文本；这样「用哪一版」只有一个答案。
"""

from app.prompts.defaults import DEFAULTS, ROLES
from app.prompts.set import PromptSet, prompt_sha8

__all__ = ["DEFAULTS", "ROLES", "PromptSet", "prompt_sha8"]
