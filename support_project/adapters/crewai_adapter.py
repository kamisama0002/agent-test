"""CrewAI 版本：角色分工的 Agent 团队。

适合场景：
- 任务适合按“研究、审核、写作、校对”等角色拆分；
- 更关注角色目标和任务产出，而不是手写每个节点；
- 需要快速搭一个可读性强的多 Agent 工作流。

CrewAI 的 Crew 是任务团队抽象，Flow 才是更偏生产编排的显式状态机。
本适配器用 sequential Crew 展示角色协作。
"""

from __future__ import annotations

import time

from crewai import Agent, Crew, LLM, Process, Task
from crewai.tools import tool

from langchain_cases.config import get_settings
from support_project.contracts import FrameworkResult
from support_project.domain import calculate_refund, compact_json, extract_order_id, lookup_order, search_policy


@tool("lookup_order")
def lookup_order_tool(order_id: str) -> str:
    """查询订单详情。"""

    return compact_json(lookup_order(order_id))


@tool("calculate_refund")
def calculate_refund_tool(order_id: str, reason: str) -> str:
    """计算退款结论和金额。"""

    return compact_json(calculate_refund(order_id, reason))


@tool("search_policy")
def search_policy_tool(query: str) -> str:
    """检索售后政策。"""

    return search_policy(query)


def _build_llm() -> LLM:
    settings = get_settings()
    return LLM(
        # CrewAI 通过 LiteLLM 路由；openai/ 前缀表示使用 OpenAI 兼容协议。
        model=f"openai/{settings.chat_model}",
        base_url=settings.base_url,
        api_key=settings.api_key,
        temperature=0,
        max_completion_tokens=900,
        timeout=settings.timeout,
    )


async def run(question: str) -> FrameworkResult:
    started = time.perf_counter()
    llm = _build_llm()
    order_id = extract_order_id(question) or "A1001"

    analyst = Agent(
        role="订单与退款分析员",
        goal="查询订单并计算退款，提供准确业务数据",
        backstory="你熟悉电商售后规则，只依据工具返回的数据工作。",
        tools=[lookup_order_tool, calculate_refund_tool],
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=5,
    )
    auditor = Agent(
        role="售后政策审核员",
        goal="检索政策并审核退款结论是否合规",
        backstory="你负责核对政策依据，指出金额和审批要求。",
        tools=[search_policy_tool],
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=4,
    )
    writer = Agent(
        role="客服回复专员",
        goal="把审核结果写成清晰、礼貌的中文回复",
        backstory="你只根据前两位同事的结论写回复，不添加未证实事实。",
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=3,
    )

    analyze_task = Task(
        description=(
            f"用户问题：{question}\n"
            f"订单号：{order_id}\n"
            "请查询订单并计算退款，输出订单信息、退款金额、退款原因。"
        ),
        expected_output="包含订单、退款金额和退款原因的简洁报告。",
        agent=analyst,
    )
    audit_task = Task(
        description="根据订单分析结果检索相关政策，审核退款结论并说明是否需要主管复核。",
        expected_output="包含政策依据、合规结论、审批要求的审核意见。",
        agent=auditor,
        context=[analyze_task],
    )
    reply_task = Task(
        description="根据前两步结果，写一段面向客户的最终中文回复，包含政策依据和退款金额。",
        expected_output="一段完整、礼貌、可直接发送给客户的回复。",
        agent=writer,
        context=[analyze_task, audit_task],
    )

    crew = Crew(
        agents=[analyst, auditor, writer],
        tasks=[analyze_task, audit_task, reply_task],
        process=Process.sequential,
        verbose=False,
    )
    result = await crew.kickoff_async()
    return FrameworkResult(
        framework="CrewAI",
        answer=str(result.raw),
        elapsed_ms=(time.perf_counter() - started) * 1000,
        strategy="三角色 Crew：订单分析 → 政策审核 → 客服写作",
        trace=["analyst", "auditor", "writer"],
    )
