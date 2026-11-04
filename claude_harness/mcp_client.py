"""把 MCP Server 的只读工具接入 Claude-style Harness。

使用项目已经锁定的 langchain-mcp-adapters + fastmcp 2.x 组合，避免与
CrewAI 的 mcp<2 依赖冲突。
"""

from __future__ import annotations

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.tools import StructuredTool


async def _load_tools(workspace: Path, server_script: Path):
    client = MultiServerMCPClient(
        {
            "claude_harness": {
                "command": sys.executable,
                "args": [str(server_script)],
                "transport": "stdio",
                "env": {"CLAUDE_WORKSPACE": str(workspace)},
            }
        }
    )
    return await client.get_tools()


def load_mcp_tools(workspace: Path, server_script: Path):
    """同步加载 MCP 工具，兼容 CLI 和 Jupyter 已有事件循环。"""

    def runner():
        return asyncio.run(_load_tools(workspace, server_script))

    try:
        has_running_loop = asyncio.get_running_loop() is not None
    except RuntimeError:
        has_running_loop = False

    if has_running_loop:
        # Jupyter 中已有事件循环，放到独立线程运行，避免 asyncio.run 嵌套。
        with ThreadPoolExecutor(max_workers=1) as pool:
            async_tools = pool.submit(runner).result()
    else:
        async_tools = runner()

    def sync_tool(tool):
        """MCP 适配器返回 async StructuredTool；为同步 LangGraph 节点加 sync 包装。"""

        def call(**kwargs):
            async def invoke():
                return await tool.ainvoke(kwargs)

            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(invoke())
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(lambda: asyncio.run(invoke())).result()

        return StructuredTool(
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema,
            func=call,
            handle_tool_error=True,
        )

    return [sync_tool(tool) for tool in async_tools]
