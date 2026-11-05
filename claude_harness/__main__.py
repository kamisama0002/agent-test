"""Claude-style Harness 命令行入口。

示例：
    python -m claude_harness --workspace examples/claude_harness_demo \
      --task "修复 add 的 bug 并运行测试" \
      --permission-mode acceptEdits --auto-approve \
      --verify-command "python -m pytest -q"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from langchain_cases.common import setup_utf8
from .config import ClaudeHarnessConfig
from .harness import ClaudeHarness


def main() -> int:
    setup_utf8()
    console = Console()
    parser = argparse.ArgumentParser(description="Claude Code-style LangGraph Harness")
    parser.add_argument("--workspace", default=".", help="代码工作区")
    parser.add_argument("--task", required=True, help="开发任务")
    parser.add_argument(
        "--permission-mode",
        default="default",
        choices=["default", "plan", "acceptEdits", "bypassPermissions", "dontAsk"],
    )
    parser.add_argument("--auto-approve", action="store_true", help="自动批准需要询问的工具操作")
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument("--token-budget", type=int, default=14000)
    parser.add_argument("--compact-threshold", type=int, default=10000)
    parser.add_argument("--command-timeout", type=int, default=60)
    parser.add_argument("--verify-command", default=None)
    parser.add_argument("--trace-root", default=None)
    parser.add_argument("--no-console", action="store_true")
    parser.add_argument("--enable-mcp", action="store_true", help="加载本地只读 MCP 工具")
    parser.add_argument("--mcp-server-script", default=None, help="MCP server Python 文件")
    parser.add_argument("--plugin-dir", action="append", default=[], help="本地插件目录，可重复传入")
    args = parser.parse_args()

    config = ClaudeHarnessConfig(
        workspace=Path(args.workspace),
        permission_mode=args.permission_mode,
        auto_approve=args.auto_approve,
        max_turns=args.max_turns,
        token_budget=args.token_budget,
        compact_threshold=args.compact_threshold,
        command_timeout=args.command_timeout,
        verify_command=args.verify_command,
        trace_root=Path(args.trace_root) if args.trace_root else None,
        console=not args.no_console,
        enable_mcp=args.enable_mcp,
        mcp_server_script=Path(args.mcp_server_script) if args.mcp_server_script else None,
        plugin_dirs=tuple(Path(item) for item in args.plugin_dir),
    )
    result = ClaudeHarness(config).run(args.task)

    console.rule("[bold green]Claude-Style Result")
    console.print(Panel(result.final_answer, title="最终回答", border_style="green"))
    console.print(f"success: {result.success}")
    console.print(f"changed files: {', '.join(result.changed_files) if result.changed_files else '(none)'}")
    console.print(f"compactions: {result.compactions}")
    console.print(f"trace: {result.run_dir}")
    console.print(f"timeline: {result.timeline_path}")
    if result.errors:
        console.print(f"[yellow]errors: {result.errors}[/yellow]")
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
