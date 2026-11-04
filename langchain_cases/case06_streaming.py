"""案例 06：流式输出。

对应官方文档：
- Streaming: https://docs.langchain.com/oss/python/langchain/streaming

两种流式粒度：
1. ``model.stream()``：直接拿到 token/chunk，适合打字机效果；
2. ``agent.stream(stream_mode="updates")``：每个 Agent 步骤完成后发一个事件，
   适合展示“模型思考/工具调用/最终回答”的 UI 进度。

如果只需要 Agent 的文本 token，可用 ``stream_mode="messages"``；
本案例用 updates 是为了把节点和工具轨迹看得更清楚。
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain.tools import tool

from .common import build_chat_model, console, message_text, print_message


@tool
def get_server_time(timezone: str) -> str:
    """返回示例服务器的固定时间，用于演示流式工具调用。"""

    return f"{timezone} 示例服务器时间：2026-11-04 14:30:00"


def run() -> None:
    model = build_chat_model()

    # ------------------------------------------------------------------
    # 1. 模型级流式：每得到一个 AIMessageChunk 就立即输出。
    # 真实 Web 服务中通常把这些增量通过 SSE / WebSocket 推给前端。
    # ------------------------------------------------------------------
    console.print("[bold cyan]1. 模型 token 流[/bold cyan]")
    for chunk in model.stream("请用三句话解释 LangChain Agent 的工作原理。"):
        text = message_text(chunk)
        if text:
            console.print(text, end="", soft_wrap=True)
    console.print("\n")

    # ------------------------------------------------------------------
    # 2. Agent 级流式：stream_mode="updates" 会在 LangGraph 每个节点后返回事件。
    # 这里可以看到 model 节点与 tools 节点的交替执行。
    # ------------------------------------------------------------------
    agent = create_agent(
        model=model,
        tools=[get_server_time],
        system_prompt="需要时间信息时调用工具。",
    )

    console.print("[bold cyan]2. Agent 步骤流[/bold cyan]")
    stream = agent.stream(
        {"messages": [{"role": "user", "content": "请调用工具查一下北京服务器时间，再简短告诉我。"}]},
        stream_mode="updates",
        version="v2",
    )

    for event in stream:
        if event.get("type") != "updates":
            continue
        for node_name, update in event.get("data", {}).items():
            console.print(f"\n[yellow]节点：{node_name}[/yellow]")
            if not isinstance(update, dict):
                continue
            for message in update.get("messages", []):
                print_message(message)

    console.print(
        "\n[dim]以上事件来自同一次 agent.stream() 调用；"
        "UI 可据此实时显示“正在调用工具 / 工具已完成 / 正在生成回答”。[/dim]"
    )


if __name__ == "__main__":
    run()
