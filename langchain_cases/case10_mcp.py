"""案例 10：连接 MCP Server 并把 MCP 工具交给 Agent。

对应官方文档：
- MCP: https://docs.langchain.com/oss/python/langchain/mcp
- MCP tools: https://docs.langchain.com/oss/python/langchain/mcp/tools

本案例启动同目录下的 ``mcp_server.py``（stdio 子进程），发现两个 MCP 工具，
再转换成 LangChain 工具。

版本说明：为了和 CrewAI 共存，本项目使用 ``langchain-mcp-adapters`` 的稳定 API。
它要求 mcp<2；LangChain 最新 ``langchain.mcp`` beta 适配器要求 fastmcp>=4，
两者不能同时安装。这里的取舍是保证 5 个框架能在同一虚拟环境中跑通。
"""

from __future__ import annotations

import sys
from pathlib import Path

from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from .common import build_chat_model, console, message_text, print_panel


async def run() -> None:
    server_script = Path(__file__).with_name("mcp_server.py")

    # 用当前 Python 解释器启动 stdio 子进程，确保子进程与主进程使用同一个虚拟环境。
    client = MultiServerMCPClient(
        {
            "demo": {
                "command": sys.executable,
                "args": [str(server_script)],
                "transport": "stdio",
            }
        }
    )
    # 在一个 session 内完成“发现工具 + Agent 调用”，避免每次工具调用都重启 server。
    async with client.session("demo") as session:
        tools = await load_mcp_tools(session)

        console.print("[bold cyan]发现 MCP 工具：[/bold cyan]")
        for item in tools:
            console.print(f"  - {item.name}: {item.description}")

        agent = create_agent(
            model=build_chat_model(),
            tools=tools,
            system_prompt=(
                "你是 HR 助手。查询员工、计算奖金时必须使用 MCP 工具，"
                "不能自行编造员工数据。"
            ),
        )

        result = await agent.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "查一下员工 E1001 的部门和基本工资，再按绩效 88 分计算奖金。",
                    }
                ]
            }
        )

    print_panel("MCP Agent 最终回答", message_text(result["messages"][-1]), border_style="green")
    console.print("\n[dim]MCP 的关键价值是协议标准化：同一批工具可以被不同模型应用复用。[/dim]")


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
