"""LangChain 官方核心用法示例集的统一入口。

这个文件只负责两件事：
1. 展示示例菜单；
2. 根据编号加载对应的案例模块并执行。

每个案例都放在 ``langchain_cases`` 包中，可以单独运行，也可以从这里批量运行。
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
from dataclasses import dataclass

from langchain_cases.common import console, setup_utf8


@dataclass(frozen=True)
class Case:
    """示例元数据：编号、菜单标题、Python 模块名和一句话说明。"""

    number: int
    title: str
    module: str
    description: str


CASES: tuple[Case, ...] = (
    Case(1, "模型、消息与 LCEL", "case01_models_messages", "ChatOpenAI、消息类型、Prompt 与可组合链"),
    Case(2, "结构化输出", "case02_structured_output", "Pydantic 模型 + function calling 解析"),
    Case(3, "工具与 Agent", "case03_tools_agent", "定义工具，让模型自主规划并调用"),
    Case(4, "短期记忆", "case04_memory", "checkpointer + thread_id 的多轮对话"),
    Case(5, "RAG 知识库问答", "case05_rag", "文档切分、向量检索、检索工具与回答"),
    Case(6, "流式输出", "case06_streaming", "Token 级输出与 Agent 步骤级事件"),
    Case(7, "中间件", "case07_middleware", "自定义耗时统计 + 模型调用上限"),
    Case(8, "人机协同 HITL", "case08_hitl", "工具执行前暂停、审批、恢复"),
    Case(9, "多 Agent 协作", "case09_multi_agent", "把子 Agent 包装成工具供主 Agent 调度"),
    Case(10, "MCP 工具", "case10_mcp", "本地 MCP Server 与 LangChain 客户端"),
    Case(11, "LangGraph 工作流", "case11_langgraph", "确定性流程 + 条件路由 + 模型节点"),
    Case(12, "安全护栏", "case12_guardrails", "内容过滤与 PII 脱敏"),
    Case(13, "可观测性", "case13_observability", "Callback 记录模型与工具事件"),
    Case(14, "长期记忆", "case14_long_term_memory", "跨线程用户画像存储与读取"),
    Case(15, "SQL 数据 Agent", "case15_sql_agent", "只读 SQLite 工具与自然语言查询"),
)


def print_menu() -> None:
    """打印所有案例，方便首次使用者挑选。"""

    console.rule("[bold cyan]LangChain 官方核心用法示例")
    for case in CASES:
        console.print(f"[cyan]{case.number:>2}[/cyan]. [bold]{case.title}[/bold] - {case.description}")
    console.print("\n运行单个：python main.py 3")
    console.print("运行多个：python main.py 1,3,5")
    console.print("运行全部：python main.py --all")
    console.print("环境检查：python main.py --check\n")


def run_case(case: Case) -> None:
    """动态加载案例并执行 ``run()``。

    动态导入有两个好处：
    - 用户只运行某一个案例时，不会提前加载 MCP、SQLite 等其他依赖；
    - 新增案例时，只需在 ``CASES`` 中登记，不需要修改调度逻辑。
    """

    console.rule(f"[bold green]{case.number:02d} · {case.title}")
    module = importlib.import_module(f"langchain_cases.{case.module}")
    result = module.run()

    # MCP 案例是 async 函数，其余案例是普通函数。
    # 统一在这里判断返回值，调用方就不需要关心同步/异步差异。
    if inspect.isawaitable(result):
        asyncio.run(result)


def check_environment() -> None:
    """只做导入和环境检查，不调用任何大模型接口，因此不会产生费用。"""

    from langchain_cases.config import get_settings

    settings = get_settings()
    console.print("[green]配置读取成功[/green]")
    console.print(f"  模型：{settings.chat_model}")
    console.print(f"  网关：{settings.base_url}")
    console.print(f"  API Key：{settings.api_key[:8]}...{settings.api_key[-4:]}")

    # 逐个导入案例，提前发现语法错误、缺失依赖或导入路径问题。
    for case in CASES:
        importlib.import_module(f"langchain_cases.{case.module}")
        console.print(f"  [green]✓[/green] {case.number:02d} {case.title}")

    console.print("\n[bold green]全部模块导入成功。[/bold green]")


def parse_numbers(raw: str) -> list[int]:
    """解析 ``1,3,5`` 这种输入，并拒绝不存在的编号。"""

    numbers: list[int] = []
    for part in raw.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ValueError(f"无法识别的编号：{part}")
        numbers.append(int(part))

    valid = {case.number for case in CASES}
    invalid = sorted(set(numbers) - valid)
    if invalid:
        raise ValueError(f"编号不存在：{invalid}，可用编号为 1-{len(CASES)}")
    return numbers


def main() -> None:
    setup_utf8()
    parser = argparse.ArgumentParser(description="LangChain 官方核心用法示例集")
    parser.add_argument("numbers", nargs="?", help="要运行的案例编号，如 1 或 1,3,5")
    parser.add_argument("--list", action="store_true", help="只列出案例")
    parser.add_argument("--all", action="store_true", help="依次运行全部案例")
    parser.add_argument("--check", action="store_true", help="检查配置与模块导入，不调用模型")
    args = parser.parse_args()

    # --check 和 --list 都是无副作用命令，优先处理。
    if args.check:
        check_environment()
        return
    if args.list:
        print_menu()
        return

    print_menu()
    if args.all:
        selected = list(CASES)
    elif args.numbers:
        numbers = parse_numbers(args.numbers)
        selected = [case for case in CASES if case.number in numbers]
    else:
        raw = input("请输入案例编号（直接回车退出）：").strip()
        if not raw:
            return
        numbers = parse_numbers(raw)
        selected = [case for case in CASES if case.number in numbers]

    for case in selected:
        run_case(case)


if __name__ == "__main__":
    main()
