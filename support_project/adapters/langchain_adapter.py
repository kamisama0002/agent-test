"""LangChain 版本：单 Agent + 多工具 + 工具循环。

适合场景：
- 一个助手需要调用多个业务 API；
- 希望快速接入不同模型供应商；
- 需要 middleware、结构化输出、短期记忆等通用能力。

不擅长：需要严格固定步骤、复杂分支、持久化暂停的流程（用 LangGraph）。
"""

from __future__ import annotations

import time

from langchain.agents import create_agent
from langchain.tools import tool

from langchain_cases.common import build_chat_model, message_text
from support_project.contracts import FrameworkResult
from support_project.domain import calculate_refund, compact_json, lookup_order, search_policy


@tool
def lookup_order_tool(order_id: str) -> str:
    """查询订单详情，包括商品、金额、状态和签收天数。"""

    return compact_json(lookup_order(order_id))


@tool
def calculate_refund_tool(order_id: str, reason: str) -> str:
    """根据订单和退款原因计算退款金额与审批要求。"""

    return compact_json(calculate_refund(order_id, reason))


@tool
def search_policy_tool(query: str) -> str:
    """检索售后政策，返回最相关的政策条款。"""

    return search_policy(query)


def run(question: str) -> FrameworkResult:
    started = time.perf_counter()
    agent = create_agent(
        model=build_chat_model(),
        tools=[lookup_order_tool, calculate_refund_tool, search_policy_tool],
        system_prompt=(
            "你是售后客服。必须先查询订单、检索政策并计算退款，再回答。"
            "回答中要包含订单、政策依据、退款结论、金额和是否需要主管复核。"
        ),
    )
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    trace = [f"{message.type}:{message_text(message)[:100]}" for message in result["messages"]]
    return FrameworkResult(
        framework="LangChain",
        answer=message_text(result["messages"][-1]),
        elapsed_ms=(time.perf_counter() - started) * 1000,
        strategy="单 Agent + 三个工具，由模型自主决定调用顺序",
        trace=trace,
    )
