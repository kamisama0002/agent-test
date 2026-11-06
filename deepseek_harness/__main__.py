"""DeepSeek Harness 命令行入口。"""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from .config import DeepSeekHarnessConfig
from .harness import DeepSeekHarness


def main() -> int:
    parser = argparse.ArgumentParser(description="DeepSeek Harness")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--verify-command", default=None)
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--model", default=None, help="覆盖默认的 DeepSeek 模型名")
    parser.add_argument("--approval-mode", choices=["auto", "ask", "deny"], default="auto")
    parser.add_argument("--plugin-dir", action="append", default=[])
    parser.add_argument("--enable-mcp", action="store_true")
    parser.add_argument("--enable-multi-agent", action="store_true")
    parser.add_argument("--no-console", action="store_true")
    args = parser.parse_args()

    config = DeepSeekHarnessConfig(
        workspace=Path(args.workspace),
        max_steps=args.max_steps,
        verify_command=args.verify_command,
        model_name=args.model,
        approval_mode=args.approval_mode,
        plugin_dirs=tuple(Path(item) for item in args.plugin_dir),
        enable_mcp=args.enable_mcp,
        enable_multi_agent=args.enable_multi_agent,
        console=not args.no_console,
    )
    result = DeepSeekHarness(config).run(args.task)
    Console().print(Panel(result.final_answer, title="DeepSeek Harness", border_style="green"))
    print(f"run_dir={result.run_dir}")
    print(f"checkpoints={result.checkpoints} retries={result.retries}")
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
