"""案例 13：可观测性（Callbacks）。

对应官方文档：
- Observability: https://docs.langchain.com/oss/python/langchain/observability

LangChain 的所有 Runnable 都支持 callback。生产环境通常接 LangSmith；
本案例用一个最小 CallbackHandler 把“模型开始/结束、工具开始/结束”打印出来，
帮助理解一条请求内部到底发生了哪些步骤。
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.callbacks import BaseCallbackHandler

from .common import build_chat_model, console, message_text, print_panel


class AuditCallbackHandler(BaseCallbackHandler):
    """收集 Agent 执行过程中的关键事件。"""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[str] = []

    def on_chat_model_start(self, serialized: dict[str, Any], messages: list, **kwargs: Any) -> None:
        self.events.append("chat_model.start")

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        self.events.append("chat_model.end")

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, **kwargs: Any) -> None:
        name = serialized.get("name", "unknown_tool")
        self.events.append(f"tool.start:{name}:{input_str}")

    def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        self.events.append(f"tool.end:{str(output)[:80]}")


@tool
def get_weather(city: str) -> str:
    """查询指定城市的示例天气。"""

    return f"{city} 当前 18°C，多云，空气质量良好。"


def run() -> None:
    audit = AuditCallbackHandler()
    agent = create_agent(
        model=build_chat_model(),
        tools=[get_weather],
        system_prompt="天气问题必须调用 get_weather 工具。",
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "北京天气怎么样？"}]},
        # callbacks 可以挂在 invoke config 上，也可以挂到模型/工具构造时。
        config={"callbacks": [audit]},
    )

    console.print("[bold cyan]回调事件序列：[/bold cyan]")
    for index, event in enumerate(audit.events, start=1):
        console.print(f"  {index:02d}. {event}")

    print_panel("最终回答", message_text(result["messages"][-1]), border_style="green")

    console.print(
        "\n[dim]生产环境可设置 LANGSMITH_TRACING=true 与 LANGSMITH_API_KEY，"
        "把同样的调用链上报到 LangSmith 做追踪、评估和回归分析。[/dim]"
    )


if __name__ == "__main__":
    run()
