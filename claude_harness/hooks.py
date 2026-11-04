"""最小 Hook 系统，对应 Claude Code 的 PreToolUse / PostToolUse。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class HookDecision:
    allow: bool = True
    reason: str = ""
    updated_args: dict | None = None


class HookManager:
    """允许宿主在工具前后插入确定性逻辑。

    这不是 Claude Code 的完整 JSON Hook 协议，而是 Python 版最小接口：
    - pre_tool 可以拒绝或改写参数；
    - post_tool 可以记录审计、观察结果。
    """

    def __init__(
        self,
        pre_tool: Callable[[str, dict], HookDecision | None] | None = None,
        post_tool: Callable[[str, dict, str], None] | None = None,
    ) -> None:
        self.pre_tool = pre_tool
        self.post_tool = post_tool

    def before(self, name: str, args: dict) -> HookDecision:
        if self.pre_tool is None:
            return HookDecision()
        return self.pre_tool(name, args) or HookDecision()

    def after(self, name: str, args: dict, output: str) -> None:
        if self.post_tool is not None:
            self.post_tool(name, args, output)
