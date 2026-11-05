"""Hermes 的后台复盘（background review）简化实现。

真实 Hermes 在每轮 ``run_conversation`` 结束后，可 fork 一个独立 AIAgent
重放对话快照，询问“这轮有没有值得长期保存的记忆或技能？”。它不修改主
对话，也不污染主对话的 prompt cache。

本实现保留三个关键点：
1. 独立模型调用和独立消息列表；
2. 只能使用 memory 和 skill 工具，不能改 workspace；
3. 复盘失败只记录 warning，不覆盖主任务结果。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from langchain_cases.common import message_text
from .tools import ToolContext, build_review_tools


REVIEW_PROMPT = """你是 Hermes 的后台复盘器。你的任务不是继续回答用户，而是检查本轮对话中
是否存在值得长期保存的内容。

保存规则：
1. USER.md：只保存用户明确表达、且未来仍有用的稳定偏好、身份信息或工作习惯。
2. MEMORY.md：只保存有对话证据的环境事实、项目约定、长期有效的资源位置。
3. Skills：只保存“以后如何完成一类任务”的类级别方法。优先更新已有 umbrella 技能；
   没有合适技能时才创建新技能。禁止按单次 PR、日期、事故或临时 bug 创建窄技能。
4. 不要保存临时故障、未解决的失败、模型猜测、密钥和一次性输出。
5. 修改已有技能前，必须先调用 skill_view；技能 description 不超过 60 字符。
6. 没有值得保存的内容时，什么都不写，直接说明“无需保存”。

可用动作：
- memory(target=memory|user, action=add|patch|remove)
- skill_manage(action=create|patch|add_file, name=..., description=..., body=...)
"""


@dataclass
class ReviewResult:
    attempted: bool = False
    changed_memory: list[str] = field(default_factory=list)
    changed_skills: list[str] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    final: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "changed_memory": self.changed_memory,
            "changed_skills": self.changed_skills,
            "actions": self.actions,
            "final": self.final,
            "error": self.error,
        }


def _transcript_text(messages: list[Any], max_chars: int = 16000) -> str:
    lines: list[str] = []
    for message in messages:
        role = getattr(message, "type", message.__class__.__name__)
        text = message_text(message)
        if text:
            lines.append(f"[{role}]\n{text}")
        for call in getattr(message, "tool_calls", None) or []:
            lines.append(f"[tool_call:{call.get('name')}]\n{json.dumps(call.get('args', {}), ensure_ascii=False)}")
    text = "\n\n".join(lines)
    return text if len(text) <= max_chars else text[:max_chars] + "\n...[transcript truncated]"


class BackgroundReview:
    """独立运行一次记忆/技能复盘。"""

    def __init__(
        self,
        model: Any,
        ctx: ToolContext,
        *,
        max_turns: int = 6,
    ) -> None:
        self.model = model
        self.ctx = ctx
        self.max_turns = max_turns

    def run(self, task: str, messages: list[Any], final: str) -> ReviewResult:
        result = ReviewResult(attempted=True)
        review_messages: list[Any] = []
        try:
            tools = build_review_tools(self.ctx)
            tool_map = {item.name: item for item in tools}
            bound = self.model.bind_tools(tools)
            review_messages = [
                SystemMessage(content=REVIEW_PROMPT),
                HumanMessage(
                    content=(
                        f"# 本轮任务\n{task}\n\n"
                        f"# 本轮最终回答\n{final}\n\n"
                        f"# 当前 MEMORY / USER\n{self.ctx.memory.format_for_review()}\n\n"
                        f"# 当前 Skills\n{self.ctx.skills.format_for_review()}\n\n"
                        f"# 对话轨迹\n{_transcript_text(messages)}"
                    )
                ),
            ]
            for _step in range(1, self.max_turns + 1):
                response: AIMessage = bound.invoke(review_messages)
                review_messages.append(response)
                calls = list(getattr(response, "tool_calls", None) or [])
                if not calls:
                    result.final = message_text(response)
                    break
                for call in calls:
                    name = call.get("name") or "unknown"
                    args = call.get("args") or {}
                    call_id = call.get("id") or f"review-{len(result.actions)}"
                    target = tool_map.get(name)
                    try:
                        output = str(target.invoke(args)) if target is not None else f"ERROR: unknown tool {name}"
                    except Exception as exc:
                        output = f"ERROR: {type(exc).__name__}: {exc}"
                    result.actions.append({"tool": name, "args": args, "result": output[:500]})
                    if name == "memory" and not output.startswith("ERROR"):
                        target_name = str(args.get("target", "memory"))
                        result.changed_memory.append(target_name)
                    if name == "skill_manage" and not output.startswith("ERROR"):
                        result.changed_skills.append(str(args.get("name", "")))
                    review_messages.append(ToolMessage(content=output, tool_call_id=call_id, name=name))
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
        return result
