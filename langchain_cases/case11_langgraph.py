"""案例 11：用 LangGraph 组装确定性工作流。

对应官方文档：
- LangGraph overview: https://docs.langchain.com/oss/python/langgraph/overview
- Graph API quickstart: https://docs.langchain.com/oss/python/langgraph/quickstart

LangChain 的 create_agent 本身就是一个预构建的 LangGraph。
当流程里有明确的分支、并行步骤、人工节点或复杂状态时，可以直接使用 StateGraph：
- Node：处理状态的普通函数；
- Edge：固定流转；
- Conditional Edge：运行时决定下一节点；
- State：节点之间共享的数据结构。
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from .common import build_chat_model, console, print_panel


class WorkflowState(TypedDict):
    question: str
    category: str
    answer: str
    # Annotated + operator.add 表示多个节点返回的 trace 会追加而不是覆盖。
    trace: Annotated[list[str], operator.add]


def classify_node(state: WorkflowState) -> dict:
    """一个完全确定性的节点：用关键词做路由，不消耗模型 Token。"""

    text = state["question"].lower()
    technical_words = ("agent", "langchain", "langgraph", "middleware", "create_agent", "代码")
    category = "technical" if any(word in text for word in technical_words) else "general"
    return {"category": category, "trace": [f"classify → {category}"]}


def build_answer_node(style: str):
    """工厂函数：生成不同提示词的模型节点。"""

    model = build_chat_model()

    def answer_node(state: WorkflowState) -> dict:
        if style == "technical":
            system = "你是 LangChain 技术专家，用两点回答，术语准确，控制在 160 字内。"
        else:
            system = "你是通俗易懂的科普讲师，用一个类比回答，控制在 160 字内。"

        response = model.invoke(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": state["question"]},
            ]
        )
        return {"answer": response.content, "trace": [f"answer-{style} → completed"]}

    return answer_node


def build_graph():
    """显式声明节点和边的拓扑。"""

    builder = StateGraph(WorkflowState)
    builder.add_node("classify", classify_node)
    builder.add_node("technical_answer", build_answer_node("technical"))
    builder.add_node("general_answer", build_answer_node("general"))

    builder.add_edge(START, "classify")
    # 路由函数只返回 key，映射表把 key 对应到实际节点名。
    builder.add_conditional_edges(
        "classify",
        lambda state: state["category"],
        {"technical": "technical_answer", "general": "general_answer"},
    )
    builder.add_edge("technical_answer", END)
    builder.add_edge("general_answer", END)
    return builder.compile()


def run() -> None:
    graph = build_graph()
    result = graph.invoke(
        {
            "question": "create_agent 和 LangGraph 在架构上是什么关系？请用两点说明。",
            "trace": [],
        }
    )

    console.print("[bold cyan]执行轨迹：[/bold cyan]")
    for item in result["trace"]:
        console.print(f"  - {item}")

    print_panel("工作流最终回答", result["answer"], border_style="green")
    console.print("\n[dim]如果流程拓扑是核心复杂度，优先用 LangGraph；常规工具循环先用 create_agent。[/dim]")


if __name__ == "__main__":
    run()
