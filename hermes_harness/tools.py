"""Hermes mini 暴露给模型的工具。

工具执行层只负责“在明确边界内做动作”，权限、上下文和后台复盘由
Harness 负责。这里保留 Hermes 的通用工具面：

read/write/patch/search/terminal/todo
memory / skills_list / skill_view / skill_manage
session_search

针对学习项目，文件工具和 Hermes home 做了隔离；模型不能通过 read_file
读取 .env、密钥文件或 .hermes 下的运行数据。
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from .memory import MemoryStore
from .sessions import SessionStore
from .skills import SkillStore
from .toolsets import TOOLSETS, resolve_toolsets


@dataclass
class ToolContext:
    workspace: Path
    home: Path
    memory: MemoryStore
    skills: SkillStore
    sessions: SessionStore
    event_bus: Any = None
    command_timeout: int = 60
    todos: list[dict[str, Any]] = field(default_factory=list)
    viewed_skills: set[str] = field(default_factory=set)


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _truncate(text: str, limit: int = 8000) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def _safe_workspace_path(ctx: ToolContext, relative: str) -> Path:
    target = (ctx.workspace / relative).resolve()
    root = ctx.workspace.resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"路径越界：{relative}")
    return target


def _is_sensitive(path: Path) -> bool:
    name = path.name.lower()
    if name in {".env", ".env.local", ".env.production", ".env.development"}:
        return True
    if name.startswith(".env.") and name != ".env.example":
        return True
    if path.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".jks"}:
        return True
    return any(token in name for token in ("credential", "secret", "id_rsa"))


def _skip_path(path: Path) -> bool:
    ignored = {
        ".git", ".venv", "__pycache__", "node_modules", ".pytest_cache", ".mypy_cache",
        ".hermes", ".mini_codex", ".claude", ".archify", ".ipynb_checkpoints",
    }
    return any(part in ignored for part in path.parts)


def _emit(ctx: ToolContext, event: str, message: str = "", **data: Any) -> None:
    if ctx.event_bus is not None:
        ctx.event_bus.emit(event, "tools", message, **data)


def _build_memory_tool(ctx: ToolContext):
    @tool(
        "memory",
        description=(
            "维护跨会话的 MEMORY.md / USER.md。target=memory 存环境事实，"
            "target=user 存用户画像和稳定偏好。action 支持 add/patch/remove/batch。"
        ),
    )
    def memory(
        action: str,
        target: str = "memory",
        content: str = "",
        old_text: str = "",
        new_text: str = "",
        operations: list[dict[str, Any]] | None = None,
    ) -> str:
        try:
            if action == "add":
                result = ctx.memory.add(target, content)
            elif action == "patch":
                result = ctx.memory.patch(target, old_text, new_text)
            elif action == "remove":
                result = ctx.memory.remove(target, old_text)
            elif action == "batch":
                result = ctx.memory.apply_batch(target, operations or [])
            else:
                return f"ERROR: 未知 memory action：{action}"
            _emit(ctx, "memory_changed", action, target=target, result=result)
            return _json({"success": True, "result": result, "snapshot": ctx.memory.snapshot()})
        except Exception as exc:
            return f"ERROR: {exc}"

    return memory


def _build_todo_tool(ctx: ToolContext):
    @tool("todo_list", description="更新并查看当前任务的 Todo 清单。")
    def todo_list(items: list[dict[str, Any]] | None = None, summary: str = "") -> str:
        if items is not None:
            ctx.todos = [dict(item) for item in items]
            _emit(ctx, "todo_updated", summary or "todo updated", items=ctx.todos)
        return _json({"summary": summary, "items": ctx.todos})

    return todo_list


def _build_skill_tools(ctx: ToolContext):
    @tool("skills_list", description="列出技能的 name、description、category；不加载技能正文。")
    def skills_list() -> str:
        return ctx.skills.index_text()

    @tool("skill_view", description="查看一个技能的完整 SKILL.md 或它的 references/templates/scripts 文件。")
    def skill_view(name: str, file_path: str = "") -> str:
        try:
            result = ctx.skills.view(name, file_path or None)
            ctx.viewed_skills.add(name)
            _emit(ctx, "skill_viewed", name, files=result.support_files)
            return _json({"name": result.name, "content": result.content, "support_files": result.support_files})
        except Exception as exc:
            return f"ERROR: {exc}"

    @tool(
        "skill_manage",
        description=(
            "创建或修改类级别技能。action=create/patch/add_file/remove_file/pin/archive。"
            "修改已有技能前必须先 skill_view；不要把单次故障写成窄技能。"
        ),
    )
    def skill_manage(
        action: str,
        name: str,
        description: str = "",
        body: str = "",
        category: str = "",
        file_path: str = "",
        content: str = "",
        update: bool = True,
        tags: list[str] | None = None,
    ) -> str:
        existing = ctx.skills.find(name)
        if existing is not None and action in {"patch", "add_file", "remove_file"} and name not in ctx.viewed_skills:
            return "ERROR: 修改已有技能前必须先调用 skill_view(name)"
        try:
            if action in {"create", "patch"}:
                path = ctx.skills.save(
                    name=name,
                    description=description or (existing.description if existing else ""),
                    body=body,
                    category=category or (existing.category if existing else ""),
                    created_by="agent",
                    tags=tags,
                    update=(action == "patch") or update,
                )
                result: Any = {"path": str(path)}
            elif action == "add_file":
                result = {"path": str(ctx.skills.add_file(name, file_path, content))}
            elif action == "remove_file":
                result = {"result": ctx.skills.remove_file(name, file_path)}
            elif action == "pin":
                result = ctx.skills.set_pinned(name, True)
            elif action == "archive":
                result = {"path": str(ctx.skills.archive(name))}
            else:
                return f"ERROR: 未知 skill action：{action}"
            _emit(ctx, "skill_changed", action, name=name, result=result)
            return _json({"success": True, "action": action, "result": result})
        except Exception as exc:
            return f"ERROR: {exc}"

    return skills_list, skill_view, skill_manage


def build_tools(ctx: ToolContext, tool_names: tuple[str, ...] | list[str] | None = None) -> list[Any]:
    """按 toolset 解析结果构建 LangChain Tool 列表。"""
    requested = tuple(tool_names or ("hermes",))
    enabled: set[str] = set()
    for item in requested:
        if item == "all" or item in TOOLSETS:
            enabled.update(resolve_toolsets((item,)))
        else:
            enabled.add(item)


    @tool("read_file", description="读取 workspace 内的文本文件，返回带行号的内容。")
    def read_file(path: str, start_line: int = 1, end_line: int = 200) -> str:
        target = _safe_workspace_path(ctx, path)
        if _is_sensitive(target):
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

    @tool("write_file", description="向 workspace 写入文本文件；只用于创建或覆盖明确内容。")
    def write_file(path: str, content: str) -> str:
        target = _safe_workspace_path(ctx, path)
        if _is_sensitive(target) or ".hermes" in target.parts:
            return f"ERROR: 安全策略禁止写入敏感文件：{path}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        _emit(ctx, "file_written", path)
        return f"已写入 {path}（{len(content)} chars）"

    @tool("patch", description="在 workspace 文件中替换唯一一段文本，成功后返回命中次数。")
    def patch(path: str, old: str, new: str, count: int = 1) -> str:
        target = _safe_workspace_path(ctx, path)
        if _is_sensitive(target) or ".hermes" in target.parts:
            return f"ERROR: 安全策略禁止修改敏感文件：{path}"
        if not target.is_file():
            return f"ERROR: 文件不存在：{path}"
        before = target.read_text(encoding="utf-8", errors="replace")
        occurrences = before.count(old)
        if not old or occurrences == 0:
            return "ERROR: 未找到要替换的文本。请先 read_file 确认内容。"
        after = before.replace(old, new, max(1, count))
        target.write_text(after, encoding="utf-8")
        _emit(ctx, "file_patched", path, count=min(max(1, count), occurrences))
        return f"已替换 {path}（命中 {min(max(1, count), occurrences)} 处）"

    @tool("search_files", description="在 workspace 内按 glob 查找文件，并按正则搜索文本。")
    def search_files(pattern: str = "**/*", regex: str = "") -> str:
        matches: list[str] = []
        try:
            regex_obj = re.compile(regex, re.IGNORECASE) if regex else None
        except re.error as exc:
            return f"ERROR: 正则表达式无效：{exc}"
        for target in sorted(ctx.workspace.glob(pattern)):
            if not target.is_file() or _skip_path(target.relative_to(ctx.workspace)) or _is_sensitive(target):
                continue
            relative = str(target.relative_to(ctx.workspace))
            if regex_obj is None:
                matches.append(relative)
            else:
                try:
                    for line_no, line in enumerate(target.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                        if regex_obj.search(line):
                            matches.append(f"{relative}:{line_no}: {line[:300]}")
                except OSError:
                    continue
            if len(matches) >= 200:
                break
        return _truncate("\n".join(matches) or "(no matches)")

    @tool("terminal", description="在 workspace 内执行单个受限的开发命令，返回 exit_code 和输出。")
    def terminal(command: str, timeout_sec: int = 60) -> str:
        denied = (
            "rm -rf", "rm -r ", "del /f", "del /s", "format ", "git reset --hard",
            "git clean -fd", "shutdown", "reboot", "taskkill", "remove-item",
            "curl ", "wget ", "powershell", "cmd /c", "reg delete",
        )
        lowered = command.lower()
        if any(fragment in lowered for fragment in denied):
            return "ERROR: 命令被安全策略拒绝。"
        if any(operator in command for operator in (";", "&&", "||", "|", ">", "<", "`", "$(")):
            return "ERROR: 简单版不允许 shell 组合符；请一次运行一个命令。"
        try:
            argv = shlex.split(command, posix=True)
        except ValueError as exc:
            return f"ERROR: 命令解析失败：{exc}"
        if not argv:
            return "ERROR: 命令为空。"
        allowed = {
            "python", "python3", "pytest", "uv", "git", "ruff", "mypy", "node", "npm",
            "pnpm", "yarn", "cargo", "go", "dotnet", "ls", "dir", "rg", "grep", "find",
            "cat", "type", "pwd", "head", "tail",
        }
        executable = Path(argv[0]).name.lower()
        if executable not in allowed:
            return f"ERROR: 不允许执行命令：{argv[0]}"
        argv[0] = sys.executable if executable in {"python", "python3"} else argv[0]
        limit = max(1, min(timeout_sec, ctx.command_timeout))
        try:
            result = subprocess.run(
                argv,
                cwd=ctx.workspace,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=limit,
            )
        except subprocess.TimeoutExpired:
            return f"ERROR: 命令超时（{limit}s）。"
        except OSError as exc:
            return f"ERROR: 命令启动失败：{exc}"
        output = _truncate(((result.stdout or "") + (result.stderr or "")).strip(), 8000)
        _emit(ctx, "terminal_finished", command, returncode=result.returncode, output=output[:500])
        return f"exit_code={result.returncode}\n{output or '(no output)'}"

    @tool("session_search", description="检索过去的会话消息，返回 session_id、role 和 snippet。")
    def session_search(query: str, limit: int = 8, session_id: str = "", role: str = "") -> str:
        try:
            rows = ctx.sessions.search(query, limit, session_id=session_id or None, role=role or None)
            return _json({"query": query, "results": rows})
        except Exception as exc:
            return f"ERROR: {exc}"

    memory_tool = _build_memory_tool(ctx)
    todo_tool = _build_todo_tool(ctx)
    skills_tools = _build_skill_tools(ctx)
    registry: dict[str, Any] = {
        "read_file": read_file,
        "write_file": write_file,
        "patch": patch,
        "search_files": search_files,
        "terminal": terminal,
        "todo_list": todo_tool,
        "memory": memory_tool,
        "skills_list": skills_tools[0],
        "skill_view": skills_tools[1],
        "skill_manage": skills_tools[2],
        "session_search": session_search,
    }
    return [registry[name] for name in registry if name in enabled]


def build_review_tools(ctx: ToolContext) -> list[Any]:
    """后台复盘只允许写声明性记忆和技能，不能改 workspace。"""

    return [item for item in build_tools(ctx, ("memory", "skills"))]

