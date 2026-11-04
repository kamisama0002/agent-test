"""官方单元测试示例：用 Fake Model 测出完整的工具调用循环。

这类测试不访问网络、不消耗 API Key，适合放进 CI。
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain.messages import AIMessage, HumanMessage, ToolCall
from langchain.tools import tool
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel


class FakeToolCallingModel(GenericFakeChatModel):
    """GenericFakeChatModel 默认没有 bind_tools，这里补一个空实现。"""

    def bind_tools(self, tools, **kwargs):
        return self


@tool
def get_weather(city: str) -> str:
    """查询城市天气。"""

    return f"{city} 18°C，多云"


def test_agent_calls_tool_then_answers() -> None:
    model = FakeToolCallingModel(
        messages=iter(
            [
                # 第一轮：脚本化地“决定”调用工具。
                AIMessage(
                    content="",
                    tool_calls=[ToolCall(name="get_weather", args={"city": "北京"}, id="call_1")],
                ),
                # 第二轮：拿到 ToolMessage 后给出最终答案。
                AIMessage(content="北京当前 18°C，多云。"),
            ]
        )
    )
    agent = create_agent(model, tools=[get_weather])

    result = agent.invoke(
        {"messages": [HumanMessage(content="北京天气怎么样？")]}
    )

    tool_call_messages = [
        message
        for message in result["messages"]
        if isinstance(message, AIMessage) and message.tool_calls
    ]
    assert len(tool_call_messages) == 1
    assert tool_call_messages[0].tool_calls[0]["name"] == "get_weather"
    assert "18°C" in result["messages"][-1].text
