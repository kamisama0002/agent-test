"""上下文组装与压缩。

Codex 的上下文不是简单把聊天记录丢给模型，而是按层组合：
base instructions → developer instructions → AGENTS.md → environment → conversation → tool outputs。
Mini Codex 保留这个结构的关键部分，并实现一个确定性的上下文压缩器。
"""

# Codex refs: core/src/agents_md.rs; session/turn_context.rs; core/src/compact.rs
from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Iterable

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage


BASE_SYSTEM_PROMPT = """你是 Mini Codex，一个只面向软件开发任务的编码 Agent。

工作原则：
1. 先理解仓库和任务，再修改代码；不要凭想象猜文件内容。
2. 修改尽量小，保持现有风格，不做无关重构。
3. 必须使用提供的工具读取、搜索、修改文件和执行验证命令。
4. 修改后必须运行相关测试或检查；无法运行时明确说明。
5. 用 update_plan 维护计划进度。
6. 最终用中文总结：改了什么、验证结果、剩余风险。
7. 如果启用了 spawn_agent，可用它委派只读探索，并用 wait_agent 获取结果。

安全边界：
- 只能操作 workspace 内的文件。
- 不接受路径穿越、删除工作区、重置 Git 历史等破坏性操作。
- 不要声称执行了没有执行过的命令。
"""


def discover_agents_md(workspace: Path, max_chars: int = 16000) -> str:
    """读取 workspace 根目录的 AGENTS.md / AGENTS.override.md。"""

    candidates = [workspace / "AGENTS.override.md", workspace / "AGENTS.md"]
    for candidate in candidates:
        if candidate.is_file():
            text = candidate.read_text(encoding="utf-8", errors="replace")
            return text[:max_chars]
    return ""


def environment_context(workspace: Path) -> str:
    """收集环境上下文，等价于 Codex 的 EnvironmentContext + world state 的一部分。"""

    files = []
    for item in sorted(workspace.iterdir(), key=lambda p: p.name.lower())[:30]:
        if item.name in {".git", ".venv", "__pycache__", "node_modules", ".mini_codex"}:
            continue
        files.append(f"{'dir ' if item.is_dir() else 'file'} {item.name}")

    git_branch = "not a git repository"
    if (workspace / ".git").exists():
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            git_branch = result.stdout.strip()

    return "\n".join(
        [
            f"workspace: {workspace}",
            f"platform: {platform.platform()}",
            f"python: {sys.version.split()[0]}",
            f"git_branch: {git_branch}",
            "top_level:",
            *[f"- {name}" for name in files],
        ]
    )


class ContextManager:
    """负责初始上下文和简单 token 预算压缩。"""

    def __init__(self, workspace: Path, token_budget: int = 12000) -> None:
        self.workspace = workspace
        self.token_budget = token_budget
        self.agents_md = discover_agents_md(workspace)
        self.environment = environment_context(workspace)

    def initial_messages(self, task: str, plan_text: str) -> list[BaseMessage]:
        context = f"""# 仓库上下文

## AGENTS.md
{self.agents_md or "(未找到 AGENTS.md)"}

## 环境
{self.environment}

## 当前计划
{plan_text}
"""
        return [
            SystemMessage(content=BASE_SYSTEM_PROMPT),
            HumanMessage(content=context),
            HumanMessage(content=f"# 用户任务\n{task}"),
        ]

    @staticmethod
    def estimate_tokens(messages: Iterable[BaseMessage]) -> int:
        # 粗略估算：约 4 个字符 = 1 token；用于触发压缩，不用于精确计费。
        text = "\n".join(str(getattr(message, "content", "")) for message in messages)
        return max(1, len(text) // 4)

    def compact(self, messages: list[BaseMessage]) -> tuple[list[BaseMessage], int]:
        """超过预算时保留头部 + 最近消息，丢掉中间旧历史。

        这里选择确定性压缩而不是再调用一次模型总结，目的是让简单版的行为可预测。
        生产版可以像 Codex 一样调用摘要模型生成 CompactionSummary。
        """

        if self.estimate_tokens(messages) <= self.token_budget or len(messages) <= 14:
            return messages, 0

        head = messages[:3]
        tail = messages[-10:]
        # 避免 tail 从孤立 ToolMessage 开始，保持 ToolMessage 与前序 AIMessage 的配对。
        while tail and isinstance(tail[0], ToolMessage):
            tail = tail[1:]

        removed = len(messages) - len(head) - len(tail)
        summary = HumanMessage(
            content=f"[上下文已压缩：省略了 {removed} 条较早的对话/工具结果。"
            "请根据当前计划和最近工具结果继续工作。]"
        )
        compacted = [*head, summary, *tail]
        # 对保留下来的超大工具输出再做一次截断。
        normalized: list[BaseMessage] = []
        for message in compacted:
            if isinstance(message, ToolMessage) and len(str(message.content)) > 2000:
                message = message.model_copy(update={"content": str(message.content)[:2000] + "\n...[truncated]"})
            normalized.append(message)
        return normalized, removed
