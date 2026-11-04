"""OpenAI Agents SDK 版本：Triage Agent + Handoff + Function Tools。

适合场景：
- 使用 OpenAI 模型生态，或需要 OpenAI 兼容的轻量 Agent Runtime；
- 需要 handoff（分流给专家）、guardrails、tracing；
- 希望 API 尽量少，快速搭一个可上线的最小 Agent。

注意：当前网关使用 Chat Completions，而不是 OpenAI Responses API，
所以显式使用 OpenAIChatCompletionsModel，并关闭需要 OpenAI 平台的 tracing。
"""

from __future__ import annotations

import time

from agents import (
    Agent,
    AsyncOpenAI,
    OpenAIChatCompletionsModel,
    Runner,
    function_tool,
    set_tracing_disabled,
)

from langchain_cases.config import get_settings
from support_project.contracts import FrameworkResult
from support_project.domain import calculate_refund, compact_json, lookup_order, search_policy

set_tracing_disabled(True)


@function_tool
def lookup_order_tool(order_id: str) -> str:
    """查询订单详情。"""

    return compact_json(lookup_order(order_id))


@function_tool
def calculate_refund_tool(order_id: str, reason: str) -> str:
    """计算退款结论和金额。"""

    return compact_json(calculate_refund(order_id, reason))


@function_tool
def search_policy_tool(query: str) -> str:
    """检索售后政策。"""

    return search_policy(query)


def _build_model() -> OpenAIChatCompletionsModel:
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url)
    return OpenAIChatCompletionsModel(model=settings.chat_model, openai_client=client)


async def run(question: str) -> FrameworkResult:
    started = time.perf_counter()
    model = _build_model()

    refund_agent = Agent(
        name="Refund Specialist",
        instructions=(
            "你是售后退款专家。先查询订单、检索政策并计算退款，再回答。"
            "回答要说明政策依据、退款金额和是否需要主管复核。"
        ),
        model=model,
        tools=[lookup_order_tool, calculate_refund_tool, search_policy_tool],
    )
    general_agent = Agent(
        name="General Support",
        instructions="你是通用客服，处理非退款问题；不确定时建议用户提供订单号。",
        model=model,
    )
    triage_agent = Agent(
        name="Triage Agent",
        instructions="根据用户意图分流：退款/订单/金额问题交给 Refund Specialist，其余交给 General Support。",
        model=model,
        handoffs=[refund_agent, general_agent],
    )

    result = await Runner.run(triage_agent, question)
    return FrameworkResult(
        framework="OpenAI Agents SDK",
        answer=str(result.final_output),
        elapsed_ms=(time.perf_counter() - started) * 1000,
        strategy="Triage Agent → Handoff → Refund Specialist + Function Tools",
        trace=[f"last_agent={result.last_agent.name}"],
        metadata={"last_agent": result.last_agent.name},
    )
