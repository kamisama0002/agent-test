"""Claude Code 风格的上下文组装与压缩。

对应 Claude Code 源码研究中的：
- context.ts / utils/claudemd.ts：CLAUDE.md 层级发现与注入；
- services/compact/microCompact.ts：清理旧工具结果；
- services/compact/compact.ts：超过预算后的完整摘要；
- services/SessionMemory：跨 turn 的会话记忆。
"""

from __future__ import annotations

import platform
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage


BASE_PROMPT = """你是 Claude Code 风格的开发 Agent，只在 workspace 内工作。

工作要求：
1. 先探索仓库，再编辑；不要猜文件内容。
2. 用 TodoWrite 维护任务清单，完成后更新状态。
3. 只做完成任务所需的最小修改，保持原有代码风格。
4. 写文件或执行命令前遵守当前 permission mode。
5. 修改后运行相关测试或 lint。
6. 用中文总结：改动、验证结果、风险。
7. 需要并行探索时，用 Task 启动只读子 Agent；用 SendMessage 发后续指令，用 TaskOutput 获取结果。

上下文边界：
- CLAUDE.md 是仓库级指令，优先级高于一般习惯；
- 工具结果只代表当前 workspace 的事实；
- 不要声称执行了没有执行的命令。
"""

COMPACTABLE_TOOLS = {"Read", "Bash", "Grep", "Glob", "Edit", "Write"}


def discover_claude_md(workspace: Path) -> str:
    """按 Claude Code 的项目/规则/本地优先级读取 CLAUDE.md。

    简单版读取：
    - CLAUDE.md
    - .claude/CLAUDE.md
    - .claude/rules/*.md
    - CLAUDE.local.md

    后读取的文件放在后面，保持“越接近本地、优先级越高”的语义。
    """

    paths: list[Path] = [
        workspace / "CLAUDE.md",
        workspace / ".claude" / "CLAUDE.md",
    ]
    rules_dir = workspace / ".claude" / "rules"
    if rules_dir.is_dir():
        paths.extend(sorted(rules_dir.glob("*.md")))
    paths.append(workspace / "CLAUDE.local.md")

    chunks: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if text:
            chunks.append(f"# {path.relative_to(workspace)}\n{text}")
    return "\n\n".join(chunks)[:24000]


def environment_context(workspace: Path) -> str:
    """注入工作目录、平台、Git 和顶层文件。"""

    files: list[str] = []
    for item in sorted(workspace.iterdir(), key=lambda p: p.name.lower())[:40]:
        if item.name in {".git", ".venv", "__pycache__", "node_modules", ".claude"}:
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
            f"cwd: {workspace}",
            f"platform: {platform.platform()}",
            f"python: {sys.version.split()[0]}",
            f"git_branch: {git_branch}",
            "top_level:",
            *[f"- {item}" for item in files],
        ]
    )


@dataclass
class CompactionResult:
    messages: list[BaseMessage]
    method: str
    before_tokens: int
    after_tokens: int
    removed: int


class ClaudeContextManager:
    """上下文拼装和 deterministic-first 压缩。"""

    def __init__(self, workspace: Path, token_budget: int = 14000, compact_threshold: int = 10000) -> None:
        self.workspace = workspace
        self.token_budget = token_budget
        self.compact_threshold = compact_threshold
        self.claude_md = discover_claude_md(workspace)
        self.environment = environment_context(workspace)
        self.session_memory_path = workspace / ".claude" / "session-memory" / "summary.md"
        self.session_memory = self._load_session_memory()

    def _load_session_memory(self) -> str:
        if not self.session_memory_path.is_file():
            return ""
        return self.session_memory_path.read_text(encoding="utf-8", errors="replace")[:8000]

    @staticmethod
    def estimate_tokens(messages: Iterable[BaseMessage]) -> int:
        text = "\n".join(str(getattr(message, "content", "")) for message in messages)
        return max(1, len(text) // 4)

    def initial_messages(self, task: str, todo_text: str) -> list[BaseMessage]:
        context = f"""# CLAUDE.md
{self.claude_md or "(未找到 CLAUDE.md)"}

# Session Memory
{self.session_memory or "(empty)"}

# Environment
{self.environment}

# Current Todo
{todo_text}
"""
        return [
            SystemMessage(content=BASE_PROMPT),
            HumanMessage(content=context),
            HumanMessage(content=f"# User Task\n{task}"),
        ]

    def microcompact(self, messages: list[BaseMessage], keep_recent: int = 4) -> tuple[list[BaseMessage], int]:
        """只清理较早的工具结果，保留最近结果和所有对话骨架。"""

        tool_indices = [
            index
            for index, message in enumerate(messages)
            if isinstance(message, ToolMessage) and getattr(message, "name", None) in COMPACTABLE_TOOLS
        ]
        stale = set(tool_indices[:-keep_recent]) if len(tool_indices) > keep_recent else set()
        if not stale:
            return messages, 0

        compacted: list[BaseMessage] = []
        for index, message in enumerate(messages):
            if index in stale:
                compacted.append(
                    message.model_copy(update={"content": "[Old tool result content cleared by microcompact]"})
                )
            else:
                compacted.append(message)
        return compacted, len(stale)

    def full_compact(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """确定性 full compact。

        真实 Claude Code 会调用模型生成 9 段摘要；这里保留“把长历史替换成
        摘要 + 最近消息”的结构，使用确定性摘要以避免额外 API 成本。
        """

        head = messages[:3]
        tail = messages[-8:]
        while tail and isinstance(tail[0], ToolMessage):
            tail = tail[1:]
        removed = max(0, len(messages) - len(head) - len(tail))
        summary = HumanMessage(
            content=(
                f"[Compacted context: {removed} older messages omitted. "
                "Keep the current task, CLAUDE.md rules, Todo state, recent tool results, "
                "and verification status in mind.]"
            )
        )
        return [*head, summary, *tail]

    def maybe_compact(self, messages: list[BaseMessage]) -> CompactionResult:
        before = self.estimate_tokens(messages)
        if before <= self.compact_threshold:
            return CompactionResult(messages, "none", before, before, 0)

        micro, removed = self.microcompact(messages)
        after_micro = self.estimate_tokens(micro)
        if after_micro <= self.token_budget:
            return CompactionResult(micro, "microcompact", before, after_micro, removed)

        compacted = self.full_compact(micro)
        after = self.estimate_tokens(compacted)
        return CompactionResult(compacted, "full_compact", before, after, removed + (len(micro) - len(compacted)))

    def save_session_memory(self, task: str, todo_text: str, final: str, changed_files: list[str], commands: list[str]) -> Path:
        """在 finalize 阶段写会话记忆，下一次 query 会重新注入。"""

        self.session_memory_path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(
            [
                "# Claude-Style Session Memory",
                "",
                "## Task",
                task,
                "",
                "## Todo",
                todo_text,
                "",
                "## Files",
                *[f"- {path}" for path in changed_files],
                "",
                "## Commands",
                *[f"- {command}" for command in commands],
                "",
                "## Final",
                final,
            ]
        )
        self.session_memory_path.write_text(content + "\n", encoding="utf-8")
        return self.session_memory_path
