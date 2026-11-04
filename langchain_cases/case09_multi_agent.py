"""案例 09：多 Agent 协作（Subagents as tools）。

对应官方文档：
- Multi-agent overview: https://docs.langchain.com/oss/python/langchain/multi-agent
- Subagents: https://docs.langchain.com/oss/python/langchain/multi-agent/subagents

常见模式是把专门 Agent 包装成普通工具：
- 主 Agent 负责理解目标、拆分任务、选择专家、汇总结果；
- 子 Agent 各自拥有独立 system prompt 和上下文窗口；
- 对主 Agent 而言，调用子 Agent 与调用普通 Python 工具没有区别。

这种模式适合“研究 + 写作”“检索 + 审校”“数据分析 + 汇报”等分工明确的场景。
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain.tools import tool

from .common import build_chat_model, console, message_text, print_messages, print_panel


def run() -> None:
    model = build_chat_model()

    # 子 Agent 1：专注计算，不负责润色。
    math_agent = create_agent(
        model=model,
        tools=[],
        system_prompt="你是严谨的数学计算专家。只给出计算过程和最终数值，不要寒暄。",
    )

    # 子 Agent 2：专注中文表达，不负责计算。
    writer_agent = create_agent(
        model=model,
        tools=[],
        system_prompt="你是中文技术编辑。把输入内容改写成一句清晰、自然的中文摘要。",
    )

    # 注意：子 Agent 返回的最终消息 content 才是工具结果。
    @tool("math_specialist", description="处理算术、比例、单位换算等计算任务。")
    def math_specialist(query: str) -> str:
        result = math_agent.invoke({"messages": [{"role": "user", "content": query}]})
        return message_text(result["messages"][-1])

    @tool("writing_specialist", description="把事实或计算结果润色成简洁中文句子。")
    def writing_specialist(query: str) -> str:
        result = writer_agent.invoke({"messages": [{"role": "user", "content": query}]})
        return message_text(result["messages"][-1])

    # 主 Agent（协调者）只看到两个“专家工具”，不直接承担专家工作。
    coordinator = create_agent(
        model=model,
        tools=[math_specialist, writing_specialist],
        system_prompt=(
            "你是协调者。必须依次调用 math_specialist 和 writing_specialist："
            "先算 128 的 37.5%，再把结果交给写作专家生成一句摘要。"
        ),
    )

    result = coordinator.invoke(
        {
            "messages": [
                {"role": "user", "content": "计算 128 的 37.5%，并把结果写成一句中文摘要。"}
            ]
        }
    )

    print_messages(result["messages"], "多 Agent 调用轨迹")
    print_panel("协调者最终输出", message_text(result["messages"][-1]), border_style="green")


if __name__ == "__main__":
    run()
