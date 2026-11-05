"""Hermes mini 命令行入口。

示例：
    uv run python -m hermes_harness --workspace examples/hermes_harness_demo \
      --task "总结这份项目并记住我的汇报偏好" --toolsets hermes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from langchain_cases.common import setup_utf8
from .config import HermesHarnessConfig
from .harness import HermesHarness


def main() -> int:
    setup_utf8()
    console = Console()
    parser = argparse.ArgumentParser(description="Hermes mini：带记忆、技能和后台复盘的通用 Agent")
    parser.add_argument("--workspace", default=".", help="任务工作区")
    parser.add_argument("--task", required=True, help="用户任务")
    parser.add_argument("--hermes-home", default=None, help="持久层目录；默认 workspace/.hermes")
    parser.add_argument("--max-turns", type=int, default=8, help="最多模型采样轮数")
    parser.add_argument("--token-budget", type=int, default=14000, help="上下文预算")
    parser.add_argument("--toolsets", default="hermes", help="逗号分隔的 toolset，例如 hermes 或 file,terminal")
    parser.add_argument("--verify-command", default=None, help="可选最终验证命令")
    parser.add_argument("--no-console", action="store_true", help="不打印实时事件")
    parser.add_argument("--no-review", action="store_true", help="关闭后台记忆/技能复盘")
    parser.add_argument("--review-max-turns", type=int, default=6, help="复盘模型最多轮数")
    args = parser.parse_args()

    config = HermesHarnessConfig(
        workspace=Path(args.workspace),
        hermes_home=Path(args.hermes_home) if args.hermes_home else None,
        max_turns=args.max_turns,
        token_budget=args.token_budget,
        toolsets=tuple(item.strip() for item in args.toolsets.split(",") if item.strip()),
        verify_command=args.verify_command,
        console=not args.no_console,
        enable_background_review=not args.no_review,
        review_max_turns=args.review_max_turns,
    )
    harness = HermesHarness(config)
    try:
        result = harness.run(args.task)
    finally:
        harness.close()

    console.rule("[bold green]Hermes Mini Result")
    console.print(Panel(result.final_answer, title="最终回答", border_style="green"))
    console.print(f"success: {result.success}")
    console.print(f"session: {result.session_id}")
    console.print(f"turns: {result.turns}")
    console.print(f"memory: {result.memory_stats}")
    console.print(f"skills used: {', '.join(result.skills_used) if result.skills_used else '(none)'}")
    console.print(f"trace: {result.run_dir}")
    if result.review:
        console.print(f"review: {result.review.final or '(no text)'}")
    if result.errors:
        console.print(f"[yellow]errors: {result.errors}[/yellow]")
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
