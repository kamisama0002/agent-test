"""LangGraph 版本：显式状态、固定节点和条件路由。

适合场景：
- 流程步骤必须可控、可审计；
- 需要在任意步骤暂停/恢复（HITL）；
- 需要 checkpoint、失败重试、时间旅行和并行分支。

本实现用确定性节点完成查询、政策检索和退款计算，只在最终回复节点调用一次模型，
因此比“让模型自己决定步骤”的 Agent 更稳定，也更容易画出流程图。
"""

from __future__ import annotations

import json
import operator
import time
from typing import Annotated, Literal, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from langchain_cases.common import build_chat_model
from support_project.contracts import FrameworkResult
from support_project.domain import calculate_refund, extract_order_id, lookup_order, search_policy


class RefundState(TypedDict):
    question: str
    order_id: str | None
    order: dict
    policy: str
    refund: dict
    answer: str
    trace: Annotated[list[str], operator.add]


def extract_node(state: RefundState) -> dict:
    order_id = extract_order_id(state["question"])
    return {"order_id": order_id, "trace": [f"extract_order → {order_id}"]}


def route_order(state: RefundState) -> Literal["lookup", "not_found"]:
    return "lookup" if state.get("order_id") else "not_found"


def lookup_node(state: RefundState) -> dict:
    order = lookup_order(state["order_id"] or "")
    return {"order": order, "trace": ["lookup_order → done"]}


def policy_node(state: RefundState) -> dict:
    policy = search_policy(state["question"])
    return {"policy": policy, "trace": ["search_policy → done"]}


def refund_node(state: RefundState) -> dict:
    refund = calculate_refund(state["order_id"] or "", state["question"])
    return {"refund": refund, "trace": ["calculate_refund → done"]}


def compose_node(state: RefundState) -> dict:
    prompt = (
        "你是售后客服。根据以下已核验数据生成最终回复，不要编造数据。\n"
        f"订单：{json.dumps(state['order'], ensure_ascii=False)}\n"
        f"政策：{state['policy']}\n"
        f"退款计算：{json.dumps(state['refund'], ensure_ascii=False)}\n"
        "请说明政策依据、退款金额，并明确是否需要主管复核。"
    )
    response = build_chat_model().invoke(
        [
            {"role": "system", "content": "回答简洁、准确，使用中文。"},
            {"role": "user", "content": prompt},
        ]
    )
    return {"answer": str(response.content), "trace": ["compose_answer → LLM done"]}


def not_found_node(state: RefundState) -> dict:
    return {
        "answer": "没有识别到有效订单号，请提供形如 A1001 的订单编号后再试。",
        "trace": ["not_found → answer"],
    }


def build_graph():
    builder = StateGraph(RefundState)
    builder.add_node("extract", extract_node)
    builder.add_node("lookup", lookup_node)
    builder.add_node("policy", policy_node)
    builder.add_node("refund", refund_node)
    builder.add_node("compose", compose_node)
    builder.add_node("not_found", not_found_node)

    builder.add_edge(START, "extract")
    builder.add_conditional_edges(
        "extract",
        route_order,
        {"lookup": "lookup", "not_found": "not_found"},
    )
    builder.add_edge("lookup", "policy")
    builder.add_edge("policy", "refund")
    builder.add_edge("refund", "compose")
    builder.add_edge("compose", END)
    builder.add_edge("not_found", END)
    # checkpointer 让同一 thread_id 的状态可以被恢复，也是 HITL 的基础。
    return builder.compile(checkpointer=InMemorySaver())


def run(question: str) -> FrameworkResult:
    started = time.perf_counter()
    graph = build_graph()
    result = graph.invoke(
        {"question": question, "trace": []},
        config={"configurable": {"thread_id": "support-langgraph-demo"}},
    )
    return FrameworkResult(
        framework="LangGraph",
        answer=result["answer"],
        elapsed_ms=(time.perf_counter() - started) * 1000,
        strategy="显式状态图：extract → lookup → policy → refund → LLM compose",
        trace=result["trace"],
    )
