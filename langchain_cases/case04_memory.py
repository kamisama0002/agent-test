"""案例 04：短期记忆（Thread-level Memory）。

对应官方文档：
- Short-term memory: https://docs.langchain.com/oss/python/langchain/short-term-memory

短期记忆的本质不是“把历史消息手动拼起来”，而是：
- Agent 状态由 checkpointer 持久化；
- 同一个 ``thread_id`` 的多次 invoke 会自动接续历史；
- 不同 thread_id 之间彼此隔离。

本项目使用 InMemorySaver 做演示。进程退出后数据会消失；
生产环境应换成 Postgres/Mongo/Redis 等持久化 checkpointer。
"""

from __future__ import annotations

from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver

from .common import build_chat_model, console, message_text, print_panel


def run() -> None:
    model = build_chat_model()

    # checkpointer 保存每个 thread 的 AgentState。
    checkpointer = InMemorySaver()
    agent = create_agent(
        model=model,
        tools=[],
        system_prompt="你是一名耐心的学习助手，回答简洁。",
        checkpointer=checkpointer,
    )

    # 同一个 thread_id 代表同一段会话。
    config = {"configurable": {"thread_id": "langchain-demo-user-001"}}

    first = agent.invoke(
        {"messages": [{"role": "user", "content": "我叫林舟，正在学习 LangChain 的 Agent。"}]},
        config=config,
    )
    print_panel("第 1 轮", message_text(first["messages"][-1]))

    # 第二轮只发送新问题，不需要再次附上“我叫林舟”。checkpointer 会恢复历史。
    second = agent.invoke(
        {"messages": [{"role": "user", "content": "我叫什么？我正在学什么？"}]},
        config=config,
    )
    print_panel("第 2 轮（考察记忆）", message_text(second["messages"][-1]), border_style="green")

    console.print(f"\n[dim]当前 thread 内的消息数：{len(second['messages'])}。"
                  "如果换一个 thread_id，模型就不会知道你的名字。[/dim]")


if __name__ == "__main__":
    run()
