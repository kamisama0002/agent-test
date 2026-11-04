"""Claude Code 风格的开发工具。

对应 Claude Code 的 Tool 接口和工具目录：
- Read / Glob / Grep / Explore：只读探索；
- Write / Edit：文件修改；
- Bash：命令执行；
- TodoWrite：任务清单。

工具本身只负责执行，权限和 hooks 在 Harness 层统一处理。
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from .events import EventBus
from .hooks import HookManager
from .permissions import PermissionManager, ToolPermission, permission_for_tool
from .state import ChangeTracker, CommandRecord, TodoItem, TodoState


@dataclass
class ToolContext:
    workspace: Path
    todos: TodoState
    changes: ChangeTracker
    commands: list[CommandRecord]
    permissions: PermissionManager
    hooks: HookManager
    event_bus: EventBus
    command_timeout: int = 60


def _safe_path(ctx: ToolContext, relative: str) -> Path:
    path = (ctx.workspace / relative).resolve()
    root = ctx.workspace.resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"路径越界：{relative}")
    return path


def _sensitive(path: Path) -> bool:
    name = path.name.lower()
    if name in {".env", ".env.local", ".env.production", ".env.development"}:
        return True
    if name.startswith(".env.") and name != ".env.example":
        return True
    if path.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".jks"}:
        return True
    return any(token in name for token in ("credential", "secret", "id_rsa"))


def _skip(path: Path) -> bool:
    ignored = {".git", ".venv", "__pycache__", "node_modules", ".claude", ".pytest_cache", ".mypy_cache"}
    return any(part in ignored for part in path.parts)


def _truncate(text: str, limit: int = 8000) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def build_tools(ctx: ToolContext) -> tuple[list[Any], dict[str, ToolPermission]]:
    """构建工具列表和权限元数据。"""

    @tool("Read", description="读取 workspace 内文件，返回带行号的文本。")
    def read_file(path: str, start_line: int = 1, end_line: int = 200) -> str:
        target = _safe_path(ctx, path)
        if _sensitive(target):
            return f"ERROR: 安全策略禁止读取敏感文件：{path}"
        if not target.is_file():
            return f"ERROR: 文件不存在：{path}"
        if target.stat().st_size > 500_000:
            return "ERROR: 文件超过 500KB，请分段读取。"
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, start_line)
        end = min(len(lines), max(start, end_line))
        body = "\n".join(f"{number:04d} | {lines[number - 1]}" for number in range(start, end + 1))
        return _truncate(f"{path}（共 {len(lines)} 行）\n{body}")

    @tool("Glob", description="用 glob 模式查找 workspace 内的文件。")
    def glob(pattern: str = "**/*") -> str:
        results = []
        for target in ctx.workspace.glob(pattern):
            if not target.is_file() or _skip(target.relative_to(ctx.workspace)) or _sensitive(target):
                continue
            results.append(str(target.relative_to(ctx.workspace)))
            if len(results) >= 200:
                break
        return "\n".join(sorted(results)) or "(no matches)"

    @tool("Grep", description="在 workspace 内按正则搜索文本，返回文件:行号:内容。")
    def grep(pattern: str, glob: str = "**/*") -> str:
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return f"ERROR: 正则表达式无效：{exc}"
        matches: list[str] = []
        for target in ctx.workspace.glob(glob):
            if not target.is_file() or _skip(target.relative_to(ctx.workspace)) or _sensitive(target):
                continue
            if target.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".pyc"}:
                continue
            try:
                lines = target.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, start=1):
                if regex.search(line):
                    matches.append(f"{target.relative_to(ctx.workspace)}:{number}: {line[:240]}")
                    if len(matches) >= 60:
                        break
            if len(matches) >= 60:
                break
        return "\n".join(matches) or "未找到匹配内容。"

    @tool("Explore", description="只读探索仓库，返回相关文件和代码片段，不修改任何文件。")
    def explore(query: str, glob: str = "**/*") -> str:
        # 这是一个确定性的只读 explorer，等价于 Claude Code Explore Agent 的最小能力。
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        matches: list[str] = []
        for target in ctx.workspace.glob(glob):
            if not target.is_file() or _skip(target.relative_to(ctx.workspace)) or _sensitive(target):
                continue
            if target.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".pyc"}:
                continue
            try:
                lines = target.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, start=1):
                if pattern.search(line):
                    matches.append(f"{target.relative_to(ctx.workspace)}:{number}: {line[:240]}")
                    break
            if len(matches) >= 30:
                break
        return "\n".join(matches) or "未找到相关代码。"

    @tool("Write", description="创建或整体覆盖 workspace 内文件，并记录变更。")
    def write_file(path: str, content: str) -> str:
        target = _safe_path(ctx, path)
        if _sensitive(target):
            return f"ERROR: 安全策略禁止写入敏感文件：{path}"
        if len(content) > 300_000:
            return "ERROR: 单次写入超过 300KB。"
        before = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        ctx.changes.record(str(target.relative_to(ctx.workspace)), "write", before, content)
        return f"已写入 {path}（{len(content)} 字符）"

    @tool("Edit", description="用精确文本替换修改文件；old 必须存在。")
    def edit_file(path: str, old: str, new: str, count: int = 1) -> str:
        target = _safe_path(ctx, path)
        if _sensitive(target):
            return f"ERROR: 安全策略禁止修改敏感文件：{path}"
        if not target.is_file():
            return f"ERROR: 文件不存在：{path}"
        before = target.read_text(encoding="utf-8", errors="replace")
        if not old:
            return "ERROR: old 不能为空。"
        occurrences = before.count(old)
        if occurrences == 0:
            return "ERROR: 未找到要替换的文本，请先 Read 确认内容。"
        actual = max(1, count)
        after = before.replace(old, new, actual)
        target.write_text(after, encoding="utf-8")
        ctx.changes.record(str(target.relative_to(ctx.workspace)), "edit", before, after)
        return f"已替换 {path}（命中 {min(actual, occurrences)} 处）"

    @tool("Bash", description="在 workspace 内执行开发命令，返回退出码和输出。")
    def bash(command: str, timeout_sec: int = 60) -> str:
        denied = (
            "rm -rf", "rm -r ", "del /f", "del /s", "format ", "git reset --hard",
            "git clean -fd", "shutdown", "reboot", "taskkill", "remove-item",
            "curl ", "wget ", "powershell", "cmd /c", "reg delete",
        )
        lowered = command.lower()
        if any(item in lowered for item in denied):
            return "ERROR: 命令被安全策略拒绝。"
        if any(operator in command for operator in (";", "&&", "||", "|", ">", "<", "`", "$(")):
            return "ERROR: 简单版不允许 shell 组合符。"
        try:
            argv = shlex.split(command, posix=True)
        except ValueError as exc:
            return f"ERROR: 命令解析失败：{exc}"
        if not argv:
            return "ERROR: 命令为空。"
        executable = Path(argv[0]).name.lower()
        if executable not in {
            "python", "python3", "pytest", "uv", "git", "ruff", "mypy",
            "node", "npm", "pnpm", "yarn", "cargo", "go", "dotnet",
            "ls", "dir", "rg", "grep", "find", "cat", "type", "pwd", "head", "tail",
        }:
            return f"ERROR: 不允许执行命令：{argv[0]}"
        argv[0] = sys.executable if executable in {"python", "python3"} else argv[0]
        limit = max(1, min(timeout_sec, ctx.command_timeout))
        try:
            result = subprocess.run(
                argv, cwd=ctx.workspace, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=limit,
            )
        except subprocess.TimeoutExpired:
            return f"ERROR: 命令超时（{limit}s）。"
        except OSError as exc:
            return f"ERROR: 命令启动失败：{exc}"
        output = _truncate(((result.stdout or "") + (result.stderr or "")).strip())
        ctx.commands.append(CommandRecord(command, result.returncode, output))
        return f"exit_code={result.returncode}\n{output or '(no output)'}"

    @tool("GitStatus", description="查看 workspace 的 git status。")
    def git_status() -> str:
        if not (ctx.workspace / ".git").exists():
            return "not a git repository"
        result = subprocess.run(
            ["git", "status", "--short"], cwd=ctx.workspace,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return f"exit_code={result.returncode}\n{result.stdout or result.stderr or '(clean)'}"

    @tool("GitDiff", description="查看 workspace 的 git diff。")
    def git_diff(path: str = "") -> str:
        if not (ctx.workspace / ".git").exists():
            return "not a git repository"
        args = ["git", "diff", "--"] + ([path] if path else [])
        result = subprocess.run(
            args, cwd=ctx.workspace, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        return _truncate(result.stdout or result.stderr or "(no diff)", 10000)

    @tool("TodoWrite", description="更新当前开发任务的 Todo 清单和状态。")
    def todo_write(items: list[dict[str, Any]], summary: str = "") -> str:
        try:
            normalized = []
            for item in items:
                data = dict(item)
                if "content" not in data:
                    data["content"] = data.get("title") or data.get("step") or "untitled"
                normalized.append(data)
            todo_items = [TodoItem.model_validate(item) for item in normalized]
        except Exception as exc:
            return f"ERROR: Todo 格式无效：{exc}"
        ctx.todos.update(summary, todo_items)
        ctx.event_bus.emit("todo_updated", "tools", "Todo updated", items=[item.model_dump() for item in todo_items])
        return "Todo updated\n" + ctx.todos.to_text()

    tools = [read_file, glob, grep, explore, write_file, edit_file, bash, git_status, git_diff, todo_write]
    return tools, {item.name: permission_for_tool(item.name) for item in tools}
