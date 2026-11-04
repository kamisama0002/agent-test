"""Claude-style Harness 的离线测试：权限、CLAUDE.md、工具和压缩。"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from claude_harness.context import ClaudeContextManager, discover_claude_md
from claude_harness.events import EventBus
from claude_harness.hooks import HookManager
from claude_harness.permissions import PermissionManager, permission_for_tool
from claude_harness.state import ChangeTracker, TodoState
from claude_harness.tools import ToolContext, build_tools


def _tool_context(tmp_path: Path, mode: str = "acceptEdits") -> ToolContext:
    bus = EventBus(tmp_path / "trace", console=False)
    return ToolContext(
        workspace=tmp_path,
        todos=TodoState(),
        changes=ChangeTracker(),
        commands=[],
        permissions=PermissionManager(mode),
        hooks=HookManager(),
        event_bus=bus,
    )


def test_claude_md_layers(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("root rules", encoding="utf-8")
    rules = tmp_path / ".claude" / "rules"
    rules.mkdir(parents=True)
    (rules / "testing.md").write_text("test rules", encoding="utf-8")
    text = discover_claude_md(tmp_path)
    assert "root rules" in text
    assert "test rules" in text


def test_permission_modes(tmp_path: Path) -> None:
    write = permission_for_tool("Write")
    bash = permission_for_tool("Bash")
    plan = PermissionManager("plan").decide(write, {"path": "a.py"})
    assert plan.allowed is False
    accept = PermissionManager("acceptEdits").decide(write, {"path": "a.py"})
    assert accept.allowed is True
    safe_bash = PermissionManager("acceptEdits").decide(bash, {"command": "python -m pytest -q"})
    assert safe_bash.allowed is True
    default = PermissionManager("default").decide(write, {"path": "a.py"})
    assert default.allowed is False
    bypass = PermissionManager("bypassPermissions").decide(write, {"path": "a.py"})
    assert bypass.allowed is True


def test_tools_todo_and_edit(tmp_path: Path) -> None:
    ctx = _tool_context(tmp_path)
    tools = {item.name: item for item in build_tools(ctx)[0]}
    (tmp_path / "sample.py").write_text("value = 1\n", encoding="utf-8")

    assert "已替换" in tools["Edit"].invoke(
        {"path": "sample.py", "old": "value = 1", "new": "value = 2"}
    )
    assert (tmp_path / "sample.py").read_text(encoding="utf-8") == "value = 2\n"
    assert "Todo updated" in tools["TodoWrite"].invoke(
        {"summary": "demo", "items": [{"content": "fix bug", "status": "in_progress"}]}
    )
    assert ctx.todos.items[0].content == "fix bug"


def test_microcompact_clears_old_tool_results(tmp_path: Path) -> None:
    ctx = ClaudeContextManager(tmp_path, token_budget=100, compact_threshold=80)
    messages = [SystemMessage(content="system"), HumanMessage(content="task")]
    for i in range(6):
        messages.append(
            ToolMessage(content=f"result-{i}", tool_call_id=f"call-{i}", name="Read")
        )
    compacted, removed = ctx.microcompact(messages, keep_recent=2)
    assert removed == 4
    assert "content cleared" in str(compacted[2].content)
    assert str(compacted[-1].content) == "result-5"


def test_claude_multi_agent_tool_names(tmp_path: Path) -> None:
    from claude_harness.multi_agent import build_task_tools

    ctx = _tool_context(tmp_path)
    tools, meta = build_tools(ctx)
    read_only = [tool for tool in tools if meta[tool.name].read_only]
    task_tools = build_task_tools(FakeModel(), read_only, ctx.event_bus)
    assert {tool.name for tool in task_tools} == {
        "Task", "SendMessage", "TaskOutput", "TaskList", "CloseAgent"
    }


class FakeModel:
    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages):
        from langchain_core.messages import AIMessage
        return AIMessage(content="ok")
