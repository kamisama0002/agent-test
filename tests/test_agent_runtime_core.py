"""共享 runtime、LangGraph 工具循环、插件和审批的离线测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from agent_runtime.approval import ApprovalManager
from agent_runtime.plugins import PluginRegistry
from agent_runtime.tool_loop import LangGraphToolLoop


class FakeModel:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.bound: list[Any] = []

    def bind_tools(self, tools, **kwargs):
        self.bound = list(tools)
        return self

    def invoke(self, messages):
        if not self.responses:
            raise RuntimeError("no fake response")
        return self.responses.pop(0)


def test_approval_boundaries() -> None:
    deny = ApprovalManager("deny")
    assert deny.decide("write_file", {"path": "x"}).allowed is False
    assert deny.decide("read_file", {}, read_only=True).allowed is True
    auto = ApprovalManager("auto")
    assert auto.decide("write_file", {}).allowed is True
    ask = ApprovalManager("ask")
    assert ask.decide("write_file", {}).behavior == "ask"


def test_langgraph_tool_loop_executes_tool_then_returns_final() -> None:
    @tool("echo_text", description="echo text")
    def echo_text(text: str) -> str:
        return f"echo:{text}"

    model = FakeModel(
        [
            AIMessage(content="", tool_calls=[{"name": "echo_text", "args": {"text": "hi"}, "id": "c1"}]),
            AIMessage(content="final"),
        ]
    )
    loop = LangGraphToolLoop(model, {"echo_text": echo_text}, None, max_steps=4)
    result = loop.run([AIMessage(content="start")])
    assert result.final_answer == "final"
    assert any(getattr(message, "name", None) == "echo_text" for message in result.messages)
    assert any(getattr(message, "content", "") == "echo:hi" for message in result.messages)


def test_plugin_registry_loads_manifest_tool() -> None:
    root = Path(__file__).resolve().parents[1] / "examples" / "plugins"
    registry = PluginRegistry((root,))
    tools = registry.load()
    by_name = {tool.name: tool for tool in tools}
    assert "word_count" in by_name
    assert "words=2" in by_name["word_count"].invoke({"text": "hello world"})
    assert registry.metadata("word_count") is not None
    assert registry.metadata("word_count").read_only is True


def test_mini_codex_graph_harness_loads_plugin() -> None:
    from mini_codex.config import HarnessConfig
    from mini_codex.harness import MiniCodexHarness

    root = Path(__file__).resolve().parents[1]
    workspace = root / "examples" / "mini_codex_demo"
    model = FakeModel(
        [
            AIMessage(content="", tool_calls=[{"name": "word_count", "args": {"text": "a b"}, "id": "c2"}]),
            AIMessage(content="plugin done"),
        ]
    )
    config = HarnessConfig(
        workspace=workspace,
        plugin_dirs=(root / "examples" / "plugins",),
        engine="langgraph",
        console=False,
        max_steps=4,
    )
    result = MiniCodexHarness(config, model=model).run("统计两个词")
    assert result.success is True
    assert result.final_answer == "plugin done"
    assert any(tool.name == "word_count" for tool in model.bound)


def test_hermes_runtime_loads_plugins_and_multi_agent() -> None:
    from hermes_harness.config import HermesHarnessConfig
    from hermes_harness.harness import HermesHarness

    class HermesFake:
        def __init__(self):
            self.responses = [AIMessage(content="done")]

        def bind_tools(self, tools, **kwargs):
            self.bound = list(tools)
            return self

        def invoke(self, messages):
            return self.responses.pop(0)

    root = Path(__file__).resolve().parents[1]
    workspace = Path(__file__).resolve().parents[1] / "examples" / "hermes_harness_demo"
    model = HermesFake()
    config = HermesHarnessConfig(
        workspace=workspace,
        plugin_dirs=(root / "examples" / "plugins",),
        enable_multi_agent=True,
        enable_background_review=False,
        console=False,
    )
    harness = HermesHarness(config, model=model)
    try:
        result = harness.run("检查扩展工具")
    finally:
        harness.close()
    names = {tool.name for tool in model.bound}
    assert result.success is True
    assert "word_count" in names
    assert "delegate_task" in names
    assert "send_input" in names
