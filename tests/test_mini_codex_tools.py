"""Mini Codex 工具、上下文和安全边界测试（不调用模型）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from mini_codex.context import ContextManager, discover_agents_md
from mini_codex.events import EventBus
from mini_codex.state import ChangeTracker, PlanState
from mini_codex.tools import ToolContext, build_tools


def make_context(tmp_path: Path) -> tuple[ToolContext, dict]:
    bus = EventBus(tmp_path / "trace", console=False)
    ctx = ToolContext(
        workspace=tmp_path,
        plan=PlanState(),
        changes=ChangeTracker(),
        commands=[],
        event_bus=bus,
    )
    tools = {tool.name: tool for tool in build_tools(ctx)}
    return ctx, tools


def test_file_read_write_replace(tmp_path: Path) -> None:
    ctx, tools = make_context(tmp_path)
    (tmp_path / "sample.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    read = tools["read_file"].invoke({"path": "sample.py"})
    assert "return a - b" in read

    write = tools["write_file"].invoke({"path": "notes.txt", "content": "hello"})
    assert "已写入" in write
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello"

    replace = tools["replace_in_file"].invoke(
        {"path": "sample.py", "old": "return a - b", "new": "return a + b", "count": 1}
    )
    assert "已替换" in replace
    assert "return a + b" in (tmp_path / "sample.py").read_text(encoding="utf-8")
    assert "sample.py" in ctx.changes.changed_files()


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    _, tools = make_context(tmp_path)
    with pytest.raises(ValueError):
        tools["read_file"].invoke({"path": "../outside.txt"})


def test_command_runner_and_policy(tmp_path: Path) -> None:
    ctx, tools = make_context(tmp_path)
    ok = tools["run_command"].invoke({"command": "python -c \"print(1)\""})
    assert "exit_code=0" in ok
    assert "1" in ok
    blocked = tools["run_command"].invoke({"command": "rm -rf /"})
    assert "拒绝" in blocked
    assert ctx.commands


def test_context_compaction(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("test instruction", encoding="utf-8")
    manager = ContextManager(tmp_path, token_budget=80)
    assert "test instruction" in discover_agents_md(tmp_path)

    messages = manager.initial_messages("task", "plan")
    snapshot = manager.snapshot("task", "plan")
    assert "System Prompt" in snapshot
    assert "AGENTS.md / AGENTS.override.md" in snapshot
    assert "test instruction" in snapshot["AGENTS.md / AGENTS.override.md"]
    messages.extend(HumanMessage(content="x" * 500) for _ in range(20))
    compacted, removed = manager.compact(messages)
    assert removed > 0
    assert len(compacted) < len(messages)
    assert any("上下文已压缩" in str(message.content) for message in compacted)


def test_plan_accepts_step_alias(tmp_path: Path) -> None:
    ctx, tools = make_context(tmp_path)
    result = tools["update_plan"].invoke(
        {
            "explanation": "test",
            "items": [{"step": "inspect files", "status": "in_progress"}],
        }
    )
    assert "Plan updated" in result
    assert ctx.plan.items[0].title == "inspect files"


def test_sensitive_files_are_blocked(tmp_path: Path) -> None:
    _, tools = make_context(tmp_path)
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    assert "禁止读取敏感文件" in tools["read_file"].invoke({"path": ".env"})
    assert "禁止写入敏感文件" in tools["write_file"].invoke({"path": ".env", "content": "x"})


def test_codex_multi_agent_tool_names(tmp_path: Path) -> None:
    from mini_codex.multi_agent import build_codex_agent_tools

    ctx, _ = make_context(tmp_path)
    tools = build_codex_agent_tools(FakeModel(), [], ctx.event_bus)
    assert {tool.name for tool in tools} == {
        "spawn_agent", "send_input", "wait_agent", "list_agents", "close_agent"
    }


class FakeModel:
    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages):
        from langchain_core.messages import AIMessage
        return AIMessage(content="ok")
