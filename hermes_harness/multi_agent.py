"""Hermes 风格的简略多 Agent 工具。

真实 Hermes 的 delegate_task 会为子 Agent 建立独立 conversation、toolset
和终端会话，并把最终摘要返回父 Agent。这里复用项目的 SubagentRuntime，
做一个只读、单进程、可观察的最小版：

- delegate_task：启动一个只读研究子 Agent；
- send_input：向子 Agent mailbox 投递后续消息；
- wait_agent：等待并读取结果；
- list_agents / close_agent：查看和清理生命周期。
"""

from __future__ import annotations

import json

from langchain.tools import tool

from agent_runtime import SubagentRuntime


HERMES_READ_ONLY_TOOL_NAMES = {
    "read_file",
    "search_files",
    "skills_list",
    "skill_view",
    "session_search",
}


def build_hermes_agent_tools(model, read_only_tools: list, event_bus) -> list:
    runtime = SubagentRuntime(
        model=model,
        tools=read_only_tools,
        event_bus=event_bus,
        max_steps=8,
    )

    @tool("delegate_task", description="Spawn a read-only Hermes research subagent and return its agent_id.")
    def delegate_task(description: str, role: str = "researcher") -> str:
        system_prompt = (
            "你是主 Agent 委派的只读 Hermes 子 Agent。"
            "只能读取、搜索、查看技能或检索历史；不能写文件、执行命令或修改记忆。"
            "返回结论、文件/技能证据和不确定性。"
        )
        snapshot = runtime.spawn(
            name=role,
            prompt=description,
            system_prompt=system_prompt,
        )
        return json.dumps(snapshot, ensure_ascii=False)

    @tool("send_input", description="Queue a message to a running Hermes subagent.")
    def send_input(agent_id: str, message: str) -> str:
        return json.dumps(runtime.send_input(agent_id, message), ensure_ascii=False)

    @tool("wait_agent", description="Wait for a Hermes subagent and return status/result.")
    def wait_agent(agent_id: str, timeout_sec: float = 30.0) -> str:
        return json.dumps(runtime.wait(agent_id, timeout=timeout_sec), ensure_ascii=False)

    @tool("list_agents", description="List Hermes subagents and their status.")
    def list_agents() -> str:
        return json.dumps(runtime.list_agents(), ensure_ascii=False)

    @tool("close_agent", description="Request a Hermes subagent to stop.")
    def close_agent(agent_id: str) -> str:
        return json.dumps(runtime.close(agent_id), ensure_ascii=False)

    return [delegate_task, send_input, wait_agent, list_agents, close_agent]
