"""跨 Harness 的源码不变量测试。

这些测试不是 UI 测试，而是锁定几个上游源码里最关键、最容易在重构中
丢失的机制：Codex 工具别名、Claude permission/tool surface、Hermes
memory 预算与围栏，以及 DeepSeek session/agent-loop 事件顺序。
"""

from __future__ import annotations

from pathlib import Path

from claude_harness.events import EventBus as ClaudeEventBus
from claude_harness.hooks import HookManager
from claude_harness.permissions import PermissionManager, permission_for_tool
from claude_harness.state import ChangeTracker, TodoState
from claude_harness.tools import ToolContext as ClaudeToolContext, build_tools as build_claude_tools
from hermes_harness.memory import MemoryStore
from mini_codex.events import EventBus as CodexEventBus
from agent_runtime.sandbox_sim import SandboxSimulator, sandbox_mode_for_approval, sandbox_mode_for_permission
from mini_codex.state import ChangeTracker as CodexChangeTracker, PlanState
from mini_codex.tools import ToolContext as CodexToolContext, build_tools as build_codex_tools


def test_codex_tool_router_keeps_source_aliases(tmp_path: Path) -> None:
    ctx = CodexToolContext(
        workspace=tmp_path,
        plan=PlanState(),
        changes=CodexChangeTracker(),
        commands=[],
        event_bus=CodexEventBus(tmp_path / "codex-trace", console=False),
    )
    names = {tool.name for tool in build_codex_tools(ctx)}
    assert {"exec_command", "apply_patch", "request_permissions"} <= names
    assert {"read_file", "search_text", "run_command"} <= names


def test_claude_tool_surface_and_permission_modes(tmp_path: Path) -> None:
    ctx = ClaudeToolContext(
        workspace=tmp_path,
        todos=TodoState(),
        changes=ChangeTracker(),
        commands=[],
        permissions=PermissionManager("default"),
        hooks=HookManager(),
        event_bus=ClaudeEventBus(tmp_path / "claude-trace", console=False),
    )
    tools, meta = build_claude_tools(ctx)
    names = {tool.name for tool in tools}
    assert {"Read", "Glob", "Grep", "Edit", "Write", "Bash", "TodoWrite"} <= names
    assert permission_for_tool("Read").read_only is True
    assert PermissionManager("plan").decide(permission_for_tool("Write"), {"path": "a.py"}).allowed is False
    assert PermissionManager("acceptEdits").decide(permission_for_tool("Write"), {"path": "a.py"}).allowed is True


def test_sandbox_simulation_emits_start_and_stop_events(tmp_path: Path) -> None:
    sandbox = SandboxSimulator("deepseek", mode=sandbox_mode_for_approval("auto"))
    bus = CodexEventBus(tmp_path / "sandbox-trace", console=False)
    profile = sandbox.start(bus, workspace=tmp_path, approval_mode="auto")
    assert profile.backend == "dsh-sandbox-local"
    assert sandbox_mode_for_approval("deny") == "read-only"
    assert sandbox_mode_for_permission("plan") == "read-only"
    sandbox.stop(bus, reason="test")
    bus.close()
    event_types = []
    for line in (tmp_path / "sandbox-trace" / "events.jsonl").read_text(encoding="utf-8").splitlines():
        import json
        event_types.append(json.loads(line)["type"])
    assert "sandbox/requested" in event_types
    assert "sandbox/started" in event_types
    assert "sandbox/stopped" in event_types


def test_hermes_memory_defaults_and_fence(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    assert store.limits["memory"] == 2200
    assert store.limits["user"] == 1375
    store.add("memory", "项目使用 uv。")
    block = store.context_block()
    assert "<memory-context>" in block
    assert "not new user input" in block
