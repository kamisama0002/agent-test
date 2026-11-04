"""统一运行 5 个框架适配器，并打印对比结果。

用法：
    python -m support_project.runner --list
    python -m support_project.runner --framework langchain
    python -m support_project.runner --framework llamaindex
    python -m support_project.runner --all
    python -m support_project.runner --all --full
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
import time

from rich.console import Console
from rich.table import Table

from langchain_cases.common import setup_utf8
from support_project.contracts import FrameworkResult

setup_utf8()
console = Console()

DEFAULT_QUESTION = "订单 A1001 的降噪耳机坏了，想退款，是否符合政策？"

# 框架名 -> (显示名，模块路径，一句话定位)
FRAMEWORKS: dict[str, tuple[str, str, str]] = {
    "langchain": ("LangChain", "support_project.adapters.langchain_adapter", "通用 Agent + 工具"),
    "langgraph": ("LangGraph", "support_project.adapters.langgraph_adapter", "显式状态图 + 可控流程"),
    "crewai": ("CrewAI", "support_project.adapters.crewai_adapter", "角色团队 + 任务协作"),
    "llamaindex": ("LlamaIndex", "support_project.adapters.llamaindex_adapter", "文档索引 + RAG"),
    "openai_agents": ("OpenAI Agents SDK", "support_project.adapters.openai_agents_adapter", "Handoff + Guardrails/Tracing"),
}


def list_frameworks() -> None:
    table = Table(title="售后工单小项目：框架适配器")
    table.add_column("key", style="cyan")
    table.add_column("框架", style="bold")
    table.add_column("定位")
    for key, (name, _, positioning) in FRAMEWORKS.items():
        table.add_row(key, name, positioning)
    console.print(table)
    console.print("\n运行：python -m support_project.runner --framework <key>")
    console.print("全部：python -m support_project.runner --all\n")


async def run_one(key: str, question: str = DEFAULT_QUESTION) -> FrameworkResult:
    """动态加载单个框架，避免运行一个框架时导入全部重依赖。"""

    if key not in FRAMEWORKS:
        raise ValueError(f"未知框架：{key}，可选：{', '.join(FRAMEWORKS)}")

    _, module_path, _ = FRAMEWORKS[key]
    module = importlib.import_module(module_path)
    result = module.run(question)
    if inspect.isawaitable(result):
        result = await result
    return result


async def run_all(question: str = DEFAULT_QUESTION) -> list[FrameworkResult]:
    results: list[FrameworkResult] = []
    for key in FRAMEWORKS:
        console.rule(f"[bold cyan]运行 {FRAMEWORKS[key][0]}")
        result = await run_one(key, question)
        console.print(f"[green]完成[/green] {result.framework}，{result.elapsed_ms / 1000:.2f}s")
        results.append(result)
    return results


def print_results(results: list[FrameworkResult], full: bool = False) -> None:
    table = Table(title="同一售后问题的框架结果对比", show_lines=True)
    table.add_column("框架", style="bold cyan", no_wrap=True)
    table.add_column("耗时", justify="right")
    table.add_column("编排策略")
    table.add_column("回答", overflow="fold")
    for result in results:
        answer = result.answer if full else result.answer[:220].replace("\n", " ") + "..."
        table.add_row(
            result.framework,
            f"{result.elapsed_ms / 1000:.2f}s",
            result.strategy,
            answer,
        )
    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(description="售后工单框架对比小项目")
    parser.add_argument("--framework", choices=list(FRAMEWORKS), help="只运行一个框架")
    parser.add_argument("--all", action="store_true", help="依次运行全部框架")
    parser.add_argument("--question", default=DEFAULT_QUESTION, help="自定义售后问题")
    parser.add_argument("--full", action="store_true", help="对比表显示完整回答")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果，便于二次处理")
    parser.add_argument("--list", action="store_true", help="列出框架 key")
    args = parser.parse_args()

    if args.list:
        list_frameworks()
        return

    if args.all:
        results = asyncio.run(run_all(args.question))
    elif args.framework:
        results = [asyncio.run(run_one(args.framework, args.question))]
    else:
        parser.print_help()
        return

    if args.json:
        payload = [
            {
                "framework": item.framework,
                "answer": item.answer,
                "elapsed_ms": round(item.elapsed_ms, 2),
                "strategy": item.strategy,
                "trace": item.trace,
                "metadata": item.metadata,
            }
            for item in results
        ]
        console.print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_results(results, full=args.full)


if __name__ == "__main__":
    main()
