"""Mini Codex 命令行入口。

示例：
    python -m mini_codex --workspace examples/mini_codex_demo \
      --task "修复 add 函数的 bug，运行测试" \
      --verify-command "python -m pytest -q"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from langchain_cases.common import setup_utf8
from .config import HarnessConfig
from .harness import MiniCodexHarness


def main() -> int:
    setup_utf8()
    console = Console()
    parser = argparse.ArgumentParser(description="Mini Codex：开发场景 LangChain Agent Harness")
    parser.add_argument("--workspace", default=".", help="代码工作区")
    parser.add_argument("--task", required=True, help="开发任务")
    parser.add_argument("--max-steps", type=int, default=10, help="最多模型采样轮数")
    parser.add_argument("--token-budget", type=int, default=12000, help="触发上下文压缩的近似 token 预算")
    parser.add_argument("--command-timeout", type=int, default=60, help="单条命令超时秒数")
    parser.add_argument("--verify-command", default=None, help="运行结束后的验证命令，例如 python -m pytest -q")
    parser.add_argument("--trace-root", default=None, help="事件和摘要目录；默认 workspace/.mini_codex/runs")
    parser.add_argument("--no-console", action="store_true", help="只写事件文件，不实时打印")
    parser.add_argument("--enable-multi-agent", action="store_true", help="加载 spawn/send/wait 子 Agent 工具")
    parser.add_argument("--enable-mcp", action="store_true", help="加载只读 MCP 工具")
    parser.add_argument("--mcp-server-script", default=None, help="MCP server Python 文件")
    args = parser.parse_args()

    config = HarnessConfig(
        workspace=Path(args.workspace),
        max_steps=args.max_steps,
        token_budget=args.token_budget,
        command_timeout=args.command_timeout,
        verify_command=args.verify_command,
        trace_root=Path(args.trace_root) if args.trace_root else None,
        console=not args.no_console,
        enable_multi_agent=args.enable_multi_agent,
        enable_mcp=args.enable_mcp,
        mcp_server_script=Path(args.mcp_server_script) if args.mcp_server_script else None,
    )
    result = MiniCodexHarness(config).run(args.task)

    console.rule("[bold green]Mini Codex Result")
    console.print(Panel(result.final_answer, title="最终回答", border_style="green"))
    console.print(f"success: {result.success}")
    console.print(f"changed files: {', '.join(result.changed_files) if result.changed_files else '(none)'}")
    console.print(f"trace: {result.run_dir}")
    console.print(f"timeline: {result.timeline_path}")
    if result.errors:
        console.print(f"[yellow]errors: {result.errors}[/yellow]")
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
