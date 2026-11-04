"""Simplified multi-Agent mailbox runtime.

对应两类生产实现：
- Codex：spawn_agent / send_input / wait_agent / close_agent / list_agents
- Claude Code：Task / SendMessage / TaskOutput / TaskList

核心语义一致：子 Agent 有独立上下文和 thread，父 Agent 通过 mailbox 发消息，
子 Agent 在模型步骤边界消费消息；父 Agent 通过 wait/output 获取最终结果。
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from langchain_cases.common import message_text


@dataclass
class AgentRecord:
    agent_id: str
    name: str
    prompt: str
    status: str = "running"
    result: str = ""
    error: str = ""
    messages: list[Any] = field(default_factory=list)
    inbox: list[str] = field(default_factory=list)
    steps: int = 0
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    def snapshot(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "inbox": list(self.inbox),
            "steps": self.steps,
        }


class SubagentRuntime:
    """在独立线程运行只读/受限工具子 Agent。"""

    def __init__(
        self,
        model,
        tools: list,
        *,
        event_bus=None,
        max_steps: int = 8,
    ) -> None:
        self.model = model
        self.tools = tools
        self.tool_map = {item.name: item for item in tools}
        self.event_bus = event_bus
        self.max_steps = max_steps
        self._records: dict[str, AgentRecord] = {}
        self._lock = threading.Lock()

    def _emit(self, event: str, message: str = "", **data) -> None:
        if self.event_bus is not None:
            self.event_bus.emit(event, "subagent", message, **data)

    def spawn(
        self,
        name: str,
        prompt: str,
        system_prompt: str,
        tools: list | None = None,
    ) -> dict:
        """启动子 Agent，立即返回 agent_id，不阻塞父 Agent。"""

        agent_id = f"{name}-{uuid.uuid4().hex[:8]}"
        record = AgentRecord(agent_id=agent_id, name=name, prompt=prompt)
        with self._lock:
            self._records[agent_id] = record
        self._emit("subagent_spawned", agent_id, agent_id=agent_id, name=name)
        record.thread = threading.Thread(
            target=self._run,
            args=(record, system_prompt, tools or self.tools),
            name=agent_id,
            daemon=True,
        )
        record.thread.start()
        return record.snapshot()

    def _run(self, record: AgentRecord, system_prompt: str, tools: list) -> None:
        messages: list[Any] = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=record.prompt),
        ]
        bound = self.model.bind_tools(tools) if tools else self.model
        try:
            for step in range(1, self.max_steps + 1):
                if record.stop_event.is_set():
                    record.status = "killed"
                    self._emit("subagent_closed", record.agent_id, agent_id=record.agent_id)
                    return
                # Claude pendingMessages / Codex mailbox 的消费点：
                # 不在模型生成中修改上下文，而是在下一轮采样前注入。
                with self._lock:
                    incoming, record.inbox = record.inbox, []
                for item in incoming:
                    messages.append(HumanMessage(content=f"[Parent message]\n{item}"))
                    self._emit("subagent_message_consumed", item, agent_id=record.agent_id)

                record.steps = step
                self._emit("subagent_model", f"step {step}", agent_id=record.agent_id)
                response = bound.invoke(messages)
                messages.append(response)
                calls = list(getattr(response, "tool_calls", None) or [])
                if not calls:
                    record.result = message_text(response)
                    record.status = "completed"
                    record.messages = messages
                    self._emit("subagent_completed", record.result[:300], agent_id=record.agent_id)
                    return
                for call in calls:
                    name = call.get("name", "unknown")
                    args = call.get("args", {})
                    call_id = call.get("id", uuid.uuid4().hex[:8])
                    tool = self.tool_map.get(name)
                    self._emit("subagent_tool_started", name, agent_id=record.agent_id, tool=name)
                    try:
                        output = str(tool.invoke(args)) if tool else f"ERROR: unknown tool {name}"
                    except Exception as exc:
                        output = f"ERROR: {type(exc).__name__}: {exc}"
                    messages.append(ToolMessage(content=output, tool_call_id=call_id, name=name))
                    self._emit("subagent_tool_finished", output[:200], agent_id=record.agent_id, tool=name)
            record.status = "failed"
            record.error = "max_steps reached"
            record.messages = messages
            self._emit("subagent_failed", record.error, agent_id=record.agent_id)
        except Exception as exc:
            record.status = "failed"
            record.error = f"{type(exc).__name__}: {exc}"
            record.messages = messages
            self._emit("subagent_failed", record.error, agent_id=record.agent_id)

    def send_input(self, agent_id: str, message: str) -> dict:
        """向子 Agent mailbox 投递消息，不直接修改正在进行的模型调用。"""

        with self._lock:
            record = self._records.get(agent_id)
            if record is None:
                return {"error": f"unknown agent: {agent_id}"}
            record.inbox.append(message)
        self._emit("subagent_message_queued", message[:200], agent_id=agent_id)
        return record.snapshot()

    def wait(self, agent_id: str, timeout: float | None = None) -> dict:
        with self._lock:
            record = self._records.get(agent_id)
        if record is None:
            return {"error": f"unknown agent: {agent_id}"}
        if record.thread is not None:
            record.thread.join(timeout=timeout)
        return record.snapshot()

    def list_agents(self) -> list[dict]:
        with self._lock:
            return [record.snapshot() for record in self._records.values()]

    def close(self, agent_id: str) -> dict:
        with self._lock:
            record = self._records.get(agent_id)
            if record is None:
                return {"error": f"unknown agent: {agent_id}"}
            record.stop_event.set()
        self._emit("subagent_close_requested", agent_id, agent_id=agent_id)
        return record.snapshot()
