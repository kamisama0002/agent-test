"""Claude Code 风格的工具权限判断。

Claude Code 用 permission mode + tool metadata + 规则共同决定工具是否能执行。
这里实现一个最小版本：
- 只读工具直接允许；
- plan 模式禁止写文件和执行命令；
- acceptEdits 自动允许编辑，但命令必须通过安全命令判断；
- dontAsk 将需要询问的操作直接拒绝；
- bypassPermissions 允许全部操作。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from .config import PermissionMode


@dataclass(frozen=True)
class ToolPermission:
    name: str
    read_only: bool
    concurrency_safe: bool = False
    destructive: bool = False


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    reason: str
    behavior: str


SAFE_COMMAND_PREFIXES = {
    "python",
    "python3",
    "pytest",
    "uv",
    "git",
    "ruff",
    "mypy",
    "node",
    "npm",
    "pnpm",
    "yarn",
    "cargo",
    "go",
    "dotnet",
    "ls",
    "dir",
    "rg",
    "grep",
    "find",
    "cat",
    "type",
    "pwd",
    "head",
    "tail",
}

DENIED_COMMAND_FRAGMENTS = (
    "rm -rf",
    "rm -r ",
    "del /f",
    "del /s",
    "format ",
    "git reset --hard",
    "git clean -fd",
    "shutdown",
    "reboot",
    "taskkill",
    "remove-item",
    "curl ",
    "wget ",
    "powershell",
    "cmd /c",
    "reg delete",
)


def is_safe_command(command: str) -> bool:
    """判断命令是否适合非交互自动执行。"""

    lowered = command.lower()
    if any(fragment in lowered for fragment in DENIED_COMMAND_FRAGMENTS):
        return False
    if any(operator in command for operator in (";", "&&", "||", "|", ">", "<", "`", "$(")):
        return False
    match = re.match(r"^\s*([^\s]+)", command)
    if not match:
        return False
    executable = match.group(1).replace("\\", "/").rsplit("/", 1)[-1].lower()
    return executable in SAFE_COMMAND_PREFIXES


class PermissionManager:
    """按权限模式决定工具调用是否执行。"""

    def __init__(
        self,
        mode: PermissionMode,
        *,
        auto_approve: bool = False,
        approval_callback: Callable[[str, dict], bool] | None = None,
    ) -> None:
        self.mode = mode
        self.auto_approve = auto_approve
        self.approval_callback = approval_callback

    def decide(self, tool: ToolPermission, args: dict) -> PermissionDecision:
        if tool.read_only:
            return PermissionDecision(True, "read-only tool", "allow")

        # TodoWrite 只修改内存中的任务清单，不触碰文件系统。
        if tool.name == "TodoWrite":
            return PermissionDecision(True, "in-memory todo update", "allow")

        if self.mode == "plan":
            return PermissionDecision(False, "plan mode only permits read-only tools", "deny")

        if self.mode == "bypassPermissions":
            return PermissionDecision(True, "bypassPermissions mode", "allow")

        if self.mode == "dontAsk":
            return PermissionDecision(False, "dontAsk mode denies operations that require a prompt", "deny")

        if self.mode == "acceptEdits":
            if tool.name in {"Write", "Edit"}:
                return PermissionDecision(True, "acceptEdits mode", "allow")
            if tool.name == "Bash":
                command = str(args.get("command", ""))
                if is_safe_command(command):
                    return PermissionDecision(True, "command matched the safe allowlist", "allow")
                return PermissionDecision(False, "command requires approval", "deny")

        if self.auto_approve:
            return PermissionDecision(True, "auto_approve enabled", "allow")

        if self.approval_callback is not None:
            approved = self.approval_callback(tool.name, args)
            return PermissionDecision(
                approved,
                "approved by callback" if approved else "rejected by callback",
                "allow" if approved else "deny",
            )

        return PermissionDecision(False, "operation requires approval", "ask")


def permission_for_tool(name: str) -> ToolPermission:
    """工具元数据，模仿 Claude Code Tool 的只读/并发安全标注。"""

    if name in {
        "Read", "Glob", "Grep", "Explore", "GitStatus", "GitDiff",
        "Task", "SendMessage", "TaskOutput", "TaskList", "CloseAgent",
    }:
        return ToolPermission(name=name, read_only=True, concurrency_safe=True)
    if name in {"Write", "Edit"}:
        return ToolPermission(name=name, read_only=False, destructive=False)
    if name == "Bash":
        return ToolPermission(name=name, read_only=False, destructive=False)
    return ToolPermission(name=name, read_only=False)
