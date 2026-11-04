"""案例 01：模型调用、消息类型、PromptTemplate 与 LCEL。

对应官方文档：
- Models: https://docs.langchain.com/oss/python/langchain/models
- Messages: https://docs.langchain.com/oss/python/langchain/messages

LangChain 最基础的两层抽象：
1. ChatModel 接收“消息列表”，返回一条 AIMessage；
2. Runnable/LCEL 用 ``|`` 把 Prompt、模型、输出解析器串成可复用链。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from .common import build_chat_model, console, message_text, print_panel


def run() -> None:
    model = build_chat_model()

    # ------------------------------------------------------------------
    # 1. 直接调用模型：显式构造 System / Human / AI 消息。
    #
    # SystemMessage：设定角色和行为边界；
    # HumanMessage：用户输入；
    # AIMessage：历史中模型之前的回复。
    #
    # 把历史消息一起传入，模型才能理解“那它呢？”这种依赖上下文的追问。
    # ------------------------------------------------------------------
    messages = [
        SystemMessage(content="你是一名简洁的技术讲师，回答不超过 120 字。"),
        HumanMessage(content="LangChain 的 create_agent 是什么？"),
        AIMessage(content="它是 LangChain 提供的高层 Agent 构造器，负责模型、工具与中间件的循环编排。"),
        HumanMessage(content="那它和 LangGraph 的区别呢？"),
    ]

    response = model.invoke(messages)
    print_panel("直接调用 ChatModel", message_text(response))

    # ------------------------------------------------------------------
    # 2. 使用 ChatPromptTemplate + LCEL。
    #
    # MessagesPlaceholder 适合放动态历史消息；变量 ``{question}`` 在 invoke
    # 时填充。``prompt | model | parser`` 的返回值本身也是一个 Runnable，
    # 可以继续 batch、stream、retry 或作为其他链的一环。
    # ------------------------------------------------------------------
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "你是一名 LangChain 助教。请用两点回答，每点一句话。"),
            MessagesPlaceholder("history"),
            ("human", "{question}"),
        ]
    )
    chain = prompt | model | StrOutputParser()

    answer = chain.invoke(
        {
            "history": [
                HumanMessage(content="我正在学习 LangChain。"),
                AIMessage(content="很好，建议先掌握模型、消息、工具和 Agent。"),
            ],
            "question": "为什么说 Agent 是“模型 + 工具 + 循环”？",
        }
    )
    print_panel("PromptTemplate + LCEL 链", answer, border_style="green")

    console.print(
        "\n[dim]观察点：直接调用和 LCEL 链使用的是同一个 ChatOpenAI；"
        "链式写法只是把输入转换、模型调用和输出解析组合起来。[/dim]"
    )


if __name__ == "__main__":
    run()
