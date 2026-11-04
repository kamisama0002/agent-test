"""共享多 Agent mailbox 运行时测试（不调用真实模型）。"""

from __future__ import annotations

import threading

from langchain_core.messages import AIMessage
from langchain.tools import tool

from agent_runtime import SubagentRuntime


class FakeModel:
    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages):
        return AIMessage(content="subagent finished")


@tool("dummy_probe")
def dummy_probe() -> str:
    """A tool used to force a second subagent model turn."""
    return "probe"


class MailboxModel:
    def __init__(self) -> None:
        self.first_turn = threading.Event()
        self.allow_second_turn = threading.Event()
        self.calls = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            self.first_turn.set()
            return AIMessage(
                content="",
                tool_calls=[{"name": "dummy_probe", "args": {}, "id": "call-1"}],
            )
        self.allow_second_turn.wait(timeout=3)
        assert any("[Parent message]" in str(getattr(message, "content", "")) for message in messages)
        return AIMessage(content="parent message observed")


def test_spawn_wait_and_mailbox() -> None:
    runtime = SubagentRuntime(FakeModel(), [], max_steps=2)
    spawned = runtime.spawn(
        name="explore",
        prompt="inspect repo",
        system_prompt="read only",
    )
    agent_id = spawned["agent_id"]
    result = runtime.wait(agent_id, timeout=3)
    assert result["status"] == "completed"
    assert "finished" in result["result"]
    queued = runtime.send_input(agent_id, "follow-up")
    assert queued["inbox"] == ["follow-up"]
    assert runtime.list_agents()[0]["agent_id"] == agent_id
    assert runtime.close(agent_id)["agent_id"] == agent_id


def test_mailbox_is_consumed_between_model_steps() -> None:
    model = MailboxModel()
    runtime = SubagentRuntime(model, [dummy_probe], max_steps=4)
    spawned = runtime.spawn("worker", "start", "test")
    agent_id = spawned["agent_id"]
    assert model.first_turn.wait(timeout=3)
    runtime.send_input(agent_id, "look at the second file")
    model.allow_second_turn.set()
    result = runtime.wait(agent_id, timeout=3)
    assert result["status"] == "completed"
    assert "parent message" in result["result"]
