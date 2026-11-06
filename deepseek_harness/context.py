"""DeepSeek Harness 的上下文组装。

重点还原推理模型编码 Agent 的几层上下文：
- system prompt：行为与安全边界；
- DEEPSEEK.md / AGENTS.md：仓库规则；
- environment：工作区事实；
- session memory：上次运行的稳定结论；
- plan/task：本轮工作状态。
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Iterable

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage


BASE_SYSTEM_PROMPT = """你是 DeepSeek Harness，一个面向软件开发任务的编码 Agent。

工作原则：
1. 先阅读仓库和相关文件，再修改代码；不要凭想象猜文件内容。
2. 只做完成任务所需的最小修改，保持现有风格。
3. 需要事实时必须调用工具，工具结果优先于模型记忆。
4. 修改后运行测试或检查；无法运行时明确说明。
5. 用 update_plan 维护计划进度。
6. 推理内容只用于辅助决策，最终以可验证的工具结果和代码为准。
7. 最终用中文总结：改了什么、验证结果、剩余风险。

安全边界：
- 只能操作 workspace 内的文件。
- 不接受路径穿越、删除工作区、重置 Git 历史等破坏性操作。
- 不声称执行了没有执行过的命令。
"""


def discover_project_instructions(workspace: Path, max_chars: int = 18000) -> str:
    """优先读取 DeepSeek 专属规则，再回退到通用的 AGENTS.md。"""

    candidates = [
        workspace / "DEEPSEEK.override.md",
        workspace / "DEEPSEEK.md",
        workspace / "AGENTS.override.md",
        workspace / "AGENTS.md",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace")[:max_chars]
    return ""


def environment_context(workspace: Path) -> str:
    """收集工作区顶层事实；只列文件名，不读取 .env 或凭据内容。"""

    files: list[str] = []
    skipped = {
        ".git", ".venv", "__pycache__", "node_modules", ".deepseek",
        ".mini_codex", ".claude", ".hermes", ".env", "auth.json",
    }
    for item in sorted(workspace.iterdir(), key=lambda p: p.name.lower())[:40]:
        if item.name in skipped or item.name.lower().startswith(("credential", "secret")):
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
            *[f"- {item}" for item in files],
        ]
    )


class DeepSeekContextManager:
    def __init__(self, workspace: Path, token_budget: int = 12000, model_name: str = "deepseek") -> None:
        self.workspace = workspace
        self.token_budget = token_budget
        self.model_name = model_name
        self.project_instructions = discover_project_instructions(workspace)
        self.environment = environment_context(workspace)
        self.session_memory_path = workspace / ".deepseek" / "session-memory.md"
        self.session_memory = self._load_session_memory()

    def _load_session_memory(self) -> str:
        if not self.session_memory_path.is_file():
            return ""
        return self.session_memory_path.read_text(encoding="utf-8", errors="replace")[:12000]

    def system_context(self, plan_text: str = "") -> str:
        return f"""

# 仓库规则（DEEPSEEK.md / AGENTS.md）
{self.project_instructions or "(未找到项目规则文件)"}

# Session Memory
{self.session_memory or "(empty)"}

# Environment
{self.environment}

# Current Plan
{plan_text or "(尚未生成；使用 update_plan 工具维护)"}
"""

    def initial_messages(self, task: str, plan_text: str) -> list[BaseMessage]:
        return [
            SystemMessage(content=BASE_SYSTEM_PROMPT + self.system_context(plan_text)),
            HumanMessage(content=f"# User Task\n{task}"),
        ]

    def snapshot(self, task: str, plan_text: str = "") -> dict[str, str]:
        return {
            "System Prompt": BASE_SYSTEM_PROMPT,
            "DEEPSEEK.md / AGENTS.md": self.project_instructions or "(未找到项目规则文件)",
            "Session Memory": self.session_memory or "(empty)",
            "Environment": self.environment,
            "Current Plan": plan_text or "(计划尚未生成)",
            "User Task": task,
            "Model": self.model_name,
            "Token Budget": str(self.token_budget),
        }

    def save_session_memory(
        self,
        *,
        task: str,
        final: str,
        plan_text: str,
        changed_files: list[str],
        commands: list[str],
    ) -> Path:
        self.session_memory_path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(
            [
                "# DeepSeek Session Memory",
                "",
                "## Task",
                task,
                "",
                "## Plan",
                plan_text,
                "",
                "## Files",
                *[f"- {item}" for item in changed_files],
                "",
                "## Commands",
                *[f"- {item}" for item in commands],
                "",
                "## Final",
                final,
            ]
        )
        self.session_memory_path.write_text(content + "\n", encoding="utf-8")
        return self.session_memory_path

    @staticmethod
    def estimate_tokens(messages: Iterable[BaseMessage]) -> int:
        text = "\n".join(str(getattr(message, "content", "")) for message in messages)
        return max(1, len(text) // 4)

    def compact(self, messages: list[BaseMessage]) -> tuple[list[BaseMessage], int]:
        """确定性压缩：保留 system、任务、计划附近内容和最近工具结果。"""

        if self.estimate_tokens(messages) <= self.token_budget or len(messages) <= 14:
            return messages, 0
        head = messages[:3]
        tail = messages[-10:]
        while tail and isinstance(tail[0], ToolMessage):
            tail = tail[1:]
        removed = len(messages) - len(head) - len(tail)
        summary = HumanMessage(
            content=(
                f"[DeepSeek context compacted: {removed} older messages omitted. "
                "Keep the task, plan, repository rules and recent tool observations.]"
            )
        )
        normalized: list[BaseMessage] = []
        for message in [*head, summary, *tail]:
            if isinstance(message, ToolMessage) and len(str(message.content)) > 2400:
                message = message.model_copy(
                    update={"content": str(message.content)[:2400] + "\n...[truncated]"}
                )
            normalized.append(message)
        return normalized, removed
