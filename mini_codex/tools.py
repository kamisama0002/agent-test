"""Mini Codex 暴露给模型的开发工具。

对应 Codex 开源实现里的工具面：
- `exec_command` / `write_stdin` → 简化为 `run_command`
- `apply_patch` → 简化为 `write_file` + `replace_in_file`
- `update_plan` → 保留
- 文件浏览/搜索 → `list_files` / `read_file` / `search_text`
- Git 观察 → `git_status` / `git_diff`

这里不暴露 MCP、图片、联网、多 Agent、插件等非本任务范围能力。
"""

# Codex refs: core/src/tools/spec_plan.rs; core/src/tools/handlers/*; plan.rs/apply_patch_spec.rs/shell_spec.rs/unified_exec/
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
from .state import ChangeTracker, CommandRecord, PlanItem, PlanState


@dataclass
class ToolContext:
    workspace: Path
    plan: PlanState
    changes: ChangeTracker
    commands: list[CommandRecord]
    event_bus: EventBus
    command_timeout: int = 60


def _safe_path(ctx: ToolContext, relative: str) -> Path:
    path = (ctx.workspace / relative).resolve()
    root = ctx.workspace.resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"路径越界：{relative}")
    return path


def _skip_path(path: Path) -> bool:
    ignored = {".git", ".venv", "__pycache__", "node_modules", ".mini_codex", ".pytest_cache", ".mypy_cache"}
    return any(part in ignored for part in path.parts)


def _sensitive_path(path: Path) -> bool:
    """阻止模型读取/覆盖常见的本地密钥文件。"""

    name = path.name.lower()
    if name in {".env", ".env.local", ".env.production", ".env.development"}:
        return True
    if name.startswith(".env.") and name != ".env.example":
        return True
    if path.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".jks"}:
        return True
    return any(token in name for token in ("credential", "secret", "id_rsa"))


def _truncate(text: str, limit: int = 8000) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def build_tools(ctx: ToolContext) -> list[Any]:
    """构建工具列表。工具通过闭包共享同一个上下文。"""

    @tool("list_files", description="递归列出 workspace 内的文件，最多 200 个。")
    def list_files(path: str = ".") -> str:
        base = _safe_path(ctx, path)
        if not base.exists():
            return f"ERROR: 路径不存在：{path}"
        if base.is_file():
            return str(base.relative_to(ctx.workspace))

        results: list[str] = []
        for current, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in {".git", ".venv", "__pycache__", "node_modules", ".mini_codex", ".pytest_cache"}]
            for name in files:
                candidate = Path(current) / name
                relative = candidate.relative_to(ctx.workspace)
                if _skip_path(relative) or _sensitive_path(candidate):
                    continue
                results.append(str(relative))
                if len(results) >= 200:
                    break
            if len(results) >= 200:
                break
        return "\n".join(sorted(results)) or "(empty)"

    @tool("read_file", description="读取 workspace 内文件的一段内容，返回带行号的文本。")
    def read_file(path: str, start_line: int = 1, end_line: int = 200) -> str:
        target = _safe_path(ctx, path)
        if _sensitive_path(target):
            return f"ERROR: 安全策略禁止读取敏感文件：{path}"
        if not target.is_file():
            return f"ERROR: 文件不存在：{path}"
        if target.stat().st_size > 500_000:
            return "ERROR: 文件超过 500KB，请用 start_line/end_line 或其他方式分段读取。"
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, start_line)
        end = min(len(lines), max(start, end_line))
        body = "\n".join(f"{number:04d} | {lines[number - 1]}" for number in range(start, end + 1))
        return _truncate(f"{path}（共 {len(lines)} 行）\n{body}")

    @tool("search_text", description="在 workspace 内按正则搜索文本，返回文件:行号:内容。")
    def search_text(query: str, glob: str = "**/*") -> str:
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error as exc:
            return f"ERROR: 正则表达式无效：{exc}"

        matches: list[str] = []
        for target in ctx.workspace.glob(glob):
            if not target.is_file() or _skip_path(target.relative_to(ctx.workspace)) or _sensitive_path(target):
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
                    if len(matches) >= 60:
                        break
            if len(matches) >= 60:
                break
        return "\n".join(matches) or "未找到匹配内容。"

    @tool("write_file", description="创建或整体覆盖 workspace 内文件，自动记录变更。")
    def write_file(path: str, content: str) -> str:
        target = _safe_path(ctx, path)
        if _sensitive_path(target):
            return f"ERROR: 安全策略禁止写入敏感文件：{path}"
        if len(content) > 300_000:
            return "ERROR: 单次写入超过 300KB，请拆分。"
        before = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        ctx.changes.record(str(target.relative_to(ctx.workspace)), "write", before, content)
        return f"已写入 {path}（{len(content)} 字符）"

    @tool("replace_in_file", description="用精确文本替换修改文件；old 必须存在。")
    def replace_in_file(path: str, old: str, new: str, count: int = 1) -> str:
        target = _safe_path(ctx, path)
        if _sensitive_path(target):
            return f"ERROR: 安全策略禁止修改敏感文件：{path}"
        if not target.is_file():
            return f"ERROR: 文件不存在：{path}"
        before = target.read_text(encoding="utf-8", errors="replace")
        if not old:
            return "ERROR: old 不能为空。"
        occurrences = before.count(old)
        if occurrences == 0:
            return "ERROR: 未找到要替换的文本。请先 read_file 确认内容。"
        actual_count = max(1, count)
        after = before.replace(old, new, actual_count)
        target.write_text(after, encoding="utf-8")
        ctx.changes.record(str(target.relative_to(ctx.workspace)), "replace", before, after)
        return f"已替换 {path}（命中 {min(actual_count, occurrences)} 处）"

    @tool("run_command", description="在 workspace 内运行开发命令（测试、lint、git 等），返回退出码和输出。")
    def run_command(command: str, timeout_sec: int = 60) -> str:
        denied_fragments = (
            "rm -rf", "rm -r ", "del /f", "del /s", "format ", "git reset --hard",
            "git clean -fd", "shutdown", "reboot", "taskkill", "remove-item",
            "curl ", "wget ", "powershell", "cmd /c", "reg delete",
        )
        lowered = command.lower()
        if any(fragment in lowered for fragment in denied_fragments):
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
            "python", "python3", "pytest", "uv", "git", "ruff", "mypy",
            "node", "npm", "pnpm", "yarn", "cargo", "go", "dotnet",
            "ls", "dir", "rg", "grep", "find", "cat", "type", "pwd",
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

        output = (result.stdout or "") + (result.stderr or "")
        output = _truncate(output.strip(), 8000)
        ctx.commands.append(CommandRecord(command=command, returncode=result.returncode, output=output))
        return f"exit_code={result.returncode}\n{output or '(no output)'}"

    @tool("git_status", description="查看 workspace 的 git 状态。")
    def git_status() -> str:
        if not (ctx.workspace / ".git").exists():
            return "not a git repository"
        result = subprocess.run(
            ["git", "status", "--short"], cwd=ctx.workspace, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
        )
        return f"exit_code={result.returncode}\n{result.stdout or result.stderr or '(clean)'}"

    @tool("git_diff", description="查看 workspace 的 git diff，可指定路径。")
    def git_diff(path: str = "") -> str:
        if not (ctx.workspace / ".git").exists():
            return "not a git repository"
        args = ["git", "diff", "--"] + ([path] if path else [])
        result = subprocess.run(
            args, cwd=ctx.workspace, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        return _truncate(result.stdout or result.stderr or "(no diff)", 10000)

    @tool("update_plan", description="更新当前开发计划的步骤和状态。")
    def update_plan(explanation: str, items: list[dict[str, Any]]) -> str:
        try:
            # 不同模型有时把步骤字段写成 step，这里兼容 title 别名。
            normalized: list[dict[str, Any]] = []
            for item in items:
                data = dict(item)
                if "title" not in data and "step" in data:
                    data["title"] = data.pop("step")
                normalized.append(data)
            plan_items = [PlanItem.model_validate(item) for item in normalized]
        except Exception as exc:
            return f"ERROR: 计划格式无效：{exc}"
        ctx.plan.update(explanation, plan_items)
        ctx.event_bus.emit("plan_updated", "agent", explanation, items=[item.model_dump() for item in plan_items])
        return "Plan updated\n" + ctx.plan.to_text()

    return [list_files, read_file, search_text, write_file, replace_in_file, run_command, git_status, git_diff, update_plan]
