"""统一启动 Codex / Claude / Hermes / DeepSeek 四套 mini Harness。

示例：

    uv run python main_mini.py --system codex --workspace $env:TEMP/mini_codex_demo
    uv run python main_mini.py --system hermes --workspace $env:TEMP/hermes_harness_demo --task "总结项目"

Viewer 会跟随该 workspace 下最新的 run；每次对话产生的新 run 会自动出现在
实时图中。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel

from langchain_cases.common import setup_utf8


SYSTEMS = {
    "codex": {"label": "Mini Codex", "demo": "mini_codex_demo", "internal": "mini_codex"},
    "claude": {"label": "Claude mini", "demo": "claude_harness_demo", "internal": "claude_harness"},
    "hermes": {"label": "Hermes mini", "demo": "hermes_harness_demo", "internal": "hermes_harness"},
    "deepseek": {"label": "DeepSeek Harness", "demo": "deepseek_harness_demo", "internal": "deepseek_harness"},
}


def make_demo_workspace(system: str) -> Path:
    root = Path(__file__).resolve().parent
    source = root / "examples" / SYSTEMS[system]["demo"]
    target = Path(tempfile.mkdtemp(prefix=f"mini-{system}-"))
    shutil.copytree(source, target, dirs_exist_ok=True)
    return target


def start_viewer(system: str, workspace: Path, port: int, open_browser: bool) -> subprocess.Popen | None:
    root = Path(__file__).resolve().parent
    script = root / "docs" / "system-maps" / "live_viewer.py"
    process = subprocess.Popen(
        [sys.executable, str(script), "--system", SYSTEMS[system]["internal"], "--workspace", str(workspace), "--port", str(port)],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.8)
    if process.poll() is not None:
        print(f"实时 Viewer 启动失败，可手动运行：python {script}")
        return None
    url = f"http://127.0.0.1:{port}/"
    print(f"实时 Viewer: {url}")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    return process


def build_task_history(history: list[tuple[str, str]], task: str) -> str:
    if not history:
        return task
    lines = ["# 之前对话（仅作为上下文，不要逐字复述）"]
    for role, text in history[-8:]:
        lines.append(f"{role}: {text}")
    lines.extend(["", "# 当前用户消息", task])
    return "\n".join(lines)

def run_task(args: argparse.Namespace, workspace: Path, task: str) -> Any:
    plugins = tuple(Path(item) for item in args.plugin_dir)
    if args.system == "codex":
        from mini_codex.config import HarnessConfig
        from mini_codex.harness import MiniCodexHarness

        config = HarnessConfig(
            workspace=workspace,
            max_steps=args.max_turns,
            verify_command=args.verify_command,
            console=not args.no_console,
            enable_multi_agent=args.enable_multi_agent,
            enable_mcp=args.enable_mcp,
            plugin_dirs=plugins,
            approval_mode=args.approval_mode,
            engine=args.engine,
        )
        return MiniCodexHarness(config).run(task)

    if args.system == "claude":
        from claude_harness.config import ClaudeHarnessConfig
        from claude_harness.harness import ClaudeHarness

        config = ClaudeHarnessConfig(
            workspace=workspace,
            permission_mode=args.permission_mode,
            auto_approve=args.auto_approve,
            max_turns=args.max_turns,
            verify_command=args.verify_command,
            console=not args.no_console,
            enable_mcp=args.enable_mcp,
            plugin_dirs=plugins,
        )
        return ClaudeHarness(config).run(task)

    if args.system == "deepseek":
        from deepseek_harness.config import DeepSeekHarnessConfig
        from deepseek_harness.harness import DeepSeekHarness

        config = DeepSeekHarnessConfig(
            workspace=workspace,
            max_steps=args.max_turns,
            verify_command=args.verify_command,
            console=not args.no_console,
            model_name=args.model,
            enable_multi_agent=args.enable_multi_agent,
            enable_mcp=args.enable_mcp,
            plugin_dirs=plugins,
            approval_mode=args.approval_mode,
        )
        return DeepSeekHarness(config).run(task)

    from hermes_harness.config import HermesHarnessConfig
    from hermes_harness.harness import HermesHarness

    config = HermesHarnessConfig(
        workspace=workspace,
        max_turns=args.max_turns,
        toolsets=tuple(item.strip() for item in args.toolsets.split(",") if item.strip()),
        verify_command=args.verify_command,
        console=not args.no_console,
        enable_background_review=not args.no_review,
        enable_multi_agent=args.enable_multi_agent,
        enable_mcp=args.enable_mcp,
        plugin_dirs=plugins,
        approval_mode=args.approval_mode,
    )
    harness = HermesHarness(config)
    try:
        return harness.run(task)
    finally:
        harness.close()

def main() -> int:
    setup_utf8()
    console = Console()
    parser = argparse.ArgumentParser(description="统一交互入口：Codex / Claude / Hermes / DeepSeek mini")
    parser.add_argument("--system", choices=sorted(SYSTEMS), default="hermes")
    parser.add_argument("--workspace", default=None, help="工作区；不传则复制对应 demo 到临时目录")
    parser.add_argument("--task", default=None, help="只运行一个任务；不传则进入交互模式")
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--verify-command", default=None)
    parser.add_argument("--toolsets", default="hermes", help="Hermes toolset，逗号分隔")
    parser.add_argument("--permission-mode", default="acceptEdits", choices=["default", "plan", "acceptEdits", "bypassPermissions", "dontAsk"])
    parser.add_argument("--auto-approve", action="store_true")
    parser.add_argument("--approval-mode", choices=["auto", "ask", "deny"], default="auto")
    parser.add_argument("--engine", choices=["langgraph", "loop"], default="langgraph")
    parser.add_argument("--enable-multi-agent", action="store_true")
    parser.add_argument("--enable-mcp", action="store_true")
    parser.add_argument("--plugin-dir", action="append", default=[], help="本地插件目录，可重复传入")
    parser.add_argument("--model", default=None, help="覆盖 DeepSeek 模型名")
    parser.add_argument("--no-review", action="store_true")
    parser.add_argument("--no-console", action="store_true")
    parser.add_argument("--no-viewer", action="store_true")
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve() if args.workspace else make_demo_workspace(args.system)
    if not workspace.is_dir():
        console.print(f"[red]workspace 不存在：{workspace}[/red]")
        return 2

    viewer = None
    if not args.no_viewer:
        viewer = start_viewer(args.system, workspace, args.port, not args.no_open)

    history: list[tuple[str, str]] = []
    console.print(Panel(
        f"system: {SYSTEMS[args.system]['label']}\nworkspace: {workspace}\n"
        "输入 /exit 退出，/clear 清空对话历史",
        title="Mini Harness Chat",
        border_style="cyan",
    ))
    try:
        if args.task:
            result = run_task(args, workspace, args.task)
            console.print(Panel(str(getattr(result, "final_answer", result)), title="最终回答", border_style="green"))
            return 0 if getattr(result, "success", True) else 1

        while True:
            try:
                text = input("\nYou> ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\nbye")
                break
            if not text:
                continue
            if text in {"/exit", "/quit"}:
                break
            if text == "/clear":
                history.clear()
                console.print("对话历史已清空；Hermes 的磁盘记忆不会自动删除。")
                continue
            if text == "/help":
                console.print("/exit 退出；/clear 清空本轮历史；其他输入会运行一次 Harness。")
                continue
            try:
                result = run_task(args, workspace, build_task_history(history, text))
                answer = str(getattr(result, "final_answer", result))
                console.print(Panel(answer, title="Agent", border_style="green"))
                history.append(("user", text))
                history.append(("assistant", answer))
            except Exception as exc:
                console.print(f"[red]运行失败：{type(exc).__name__}: {exc}[/red]")
    finally:
        if viewer is not None and viewer.poll() is None:
            viewer.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
