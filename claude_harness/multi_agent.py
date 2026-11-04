"""Claude Code 风格的简略多 Agent 工具。

对应 Claude Code 的：
- Task / AgentTool：spawn 一个独立上下文的子 Agent；
- SendMessage：向子 Agent 的 pendingMessages 投递消息；
- TaskOutput：等待并读取子 Agent 的结果；
- TaskList：查看 Agent 状态；
- CloseAgent：请求停止子 Agent。

通信不在模型生成过程中直接改上下文，而是在子 Agent 下一轮模型采样前注入，
对应 Claude Code 的 tool-round boundary 语义。
"""

from __future__ import annotations

import json
from typing import Literal

from langchain.tools import tool

from agent_runtime import SubagentRuntime


def build_task_tools(
    model,
    read_only_tools: list,
    event_bus,
) -> list:
    """构建 Task/SendMessage/TaskOutput/TaskList/CloseAgent 工具。"""

    runtime = SubagentRuntime(
        model=model,
        tools=read_only_tools,
        event_bus=event_bus,
        max_steps=8,
    )

    @tool(
        "Task",
        description=(
            "Spawn a read-only subagent with isolated context. "
            "Use subagent_type='explore' for repository discovery or 'plan' for an implementation plan. "
            "Returns an agent_id; call TaskOutput to wait for the result."
        ),
    )
    def task(description: str, subagent_type: Literal["explore", "plan"] = "explore") -> str:
        system_prompt = (
            "你是主 Agent 委派的只读 Explore 子 Agent。"
            "只能读取、搜索和总结仓库，不能写文件或执行命令。"
            "如果收到 Parent message，在下一轮开始时把它纳入分析。"
            "返回文件路径、证据和结论。"
            if subagent_type == "explore"
            else
            "你是主 Agent 委派的只读 Plan 子 Agent。"
            "基于仓库证据输出分步计划、关键文件、风险和验证命令。"
            "不能写文件或执行命令。"
        )
        return json.dumps(
            runtime.spawn(
                name=subagent_type,
                prompt=description,
                system_prompt=system_prompt,
            ),
            ensure_ascii=False,
        )

    @tool("SendMessage", description="向指定子 Agent 的 mailbox 发送后续指令。")
    def send_message(agent_id: str, message: str) -> str:
        return json.dumps(runtime.send_input(agent_id, message), ensure_ascii=False)

    @tool("TaskOutput", description="等待指定子 Agent 完成，并返回其状态和结果。")
    def task_output(agent_id: str, timeout_sec: float = 30.0) -> str:
        return json.dumps(runtime.wait(agent_id, timeout=timeout_sec), ensure_ascii=False)

    @tool("TaskList", description="列出当前子 Agent 的 ID、状态、步骤和结果摘要。")
    def task_list() -> str:
        return json.dumps(runtime.list_agents(), ensure_ascii=False)

    @tool("CloseAgent", description="请求停止指定子 Agent。")
    def close_agent(agent_id: str) -> str:
        return json.dumps(runtime.close(agent_id), ensure_ascii=False)

    return [task, send_message, task_output, task_list, close_agent]
