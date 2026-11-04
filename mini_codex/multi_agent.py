"""Codex 风格的简略多 Agent 工具。

对应 openai/codex 的：
- spawn_agent；
- send_input；
- wait_agent；
- list_agents；
- close_agent。

子 Agent 使用独立上下文和只读工具；父 Agent 通过 agent_id 通信。
"""

from __future__ import annotations

import json

from langchain.tools import tool

from agent_runtime import SubagentRuntime


READ_ONLY_TOOL_NAMES = {
    "list_files",
    "read_file",
    "search_text",
    "git_status",
    "git_diff",
}


def build_codex_agent_tools(model, read_only_tools: list, event_bus) -> list:
    """构建 spawn_agent/send_input/wait_agent/list_agents/close_agent。"""

    runtime = SubagentRuntime(
        model=model,
        tools=read_only_tools,
        event_bus=event_bus,
        max_steps=8,
    )

    @tool("spawn_agent", description="Spawn a read-only Codex-style subagent and return its agent_id.")
    def spawn_agent(description: str, role: str = "explore") -> str:
        system_prompt = (
            "你是一个只读 Codex 子 Agent，负责探索仓库并返回证据。"
            "不能写文件或执行命令；如果收到父 Agent 消息，在下一轮开始时纳入分析。"
        )
        snapshot = runtime.spawn(
            name=role,
            prompt=description,
            system_prompt=system_prompt,
        )
        return json.dumps(snapshot, ensure_ascii=False)

    @tool("send_input", description="Queue a message to a running subagent mailbox.")
    def send_input(agent_id: str, message: str) -> str:
        return json.dumps(runtime.send_input(agent_id, message), ensure_ascii=False)

    @tool("wait_agent", description="Wait for a subagent and return its status/result.")
    def wait_agent(agent_id: str, timeout_sec: float = 30.0) -> str:
        return json.dumps(runtime.wait(agent_id, timeout=timeout_sec), ensure_ascii=False)

    @tool("list_agents", description="List subagents and their status.")
    def list_agents() -> str:
        return json.dumps(runtime.list_agents(), ensure_ascii=False)

    @tool("close_agent", description="Request a subagent to stop.")
    def close_agent(agent_id: str) -> str:
        return json.dumps(runtime.close(agent_id), ensure_ascii=False)

    return [spawn_agent, send_input, wait_agent, list_agents, close_agent]
