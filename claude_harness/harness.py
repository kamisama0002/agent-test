"""Claude Code 风格的 LangGraph queryLoop。

对应 Claude Code 源码研究中的 `src/query.ts::queryLoop`：
模型采样 → tool_use → 工具结果 → 下一轮采样，直到 assistant 只返回文本。
本实现把这条循环显式拆成 LangGraph 节点，便于观察和扩展。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from langchain_cases.common import build_chat_model, message_text
from agent_runtime.observability import serialize_messages
from agent_runtime.plugins import PluginRegistry
from .config import ClaudeHarnessConfig
from .context import ClaudeContextManager
from .events import EventBus
from .hooks import HookDecision, HookManager
from .mcp_client import load_mcp_tools
from .multi_agent import build_task_tools
from .permissions import PermissionManager, ToolPermission, permission_for_tool
from .state import ChangeTracker, CommandRecord, TodoItem, TodoPlan, TodoState
from .tools import ToolContext, build_tools


class ClaudeState(TypedDict):
    task: str
    messages: list[Any]
    todos: list[TodoItem]
    final: str
    turn: int
    compactions: int
    done: bool


@dataclass
class ClaudeRunResult:
    task: str
    final_answer: str
    todos: TodoState
    changed_files: list[str]
    commands: list[CommandRecord]
    run_dir: Path
    timeline_path: Path
    success: bool
    elapsed_ms: float
    compactions: int = 0
    errors: list[str] = field(default_factory=list)


class ClaudeHarness:
    """用 LangGraph 表达 Claude Code-style queryLoop。"""

    def __init__(self, config: ClaudeHarnessConfig) -> None:
        self.config = config

    def run(self, task: str) -> ClaudeRunResult:
        started = time.perf_counter()
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        run_dir = (self.config.trace_root or self.config.workspace / ".claude" / "runs") / run_id
        bus = EventBus(run_dir, console=self.config.console)
        context = ClaudeContextManager(
            self.config.workspace,
            token_budget=self.config.token_budget,
            compact_threshold=self.config.compact_threshold,
        )
        todos = TodoState()
        changes = ChangeTracker()
        commands: list[CommandRecord] = []
        errors: list[str] = []
        compactions = 0

        def pre_tool_hook(name: str, args: dict) -> HookDecision:
            bus.emit("hook_pre_tool", "tools", f"pre-hook: {name}", tool=name, args=args)
            return HookDecision()

        def post_tool_hook(name: str, args: dict, output: str) -> None:
            bus.emit("hook_post_tool", "tools", f"post-hook: {name}", tool=name, output=output[:300])

        tool_ctx = ToolContext(
            workspace=self.config.workspace,
            todos=todos,
            changes=changes,
            commands=commands,
            permissions=PermissionManager(
                self.config.permission_mode,
                auto_approve=self.config.auto_approve,
            ),
            hooks=HookManager(pre_tool=pre_tool_hook, post_tool=post_tool_hook),
            event_bus=bus,
            command_timeout=self.config.command_timeout,
        )
        tools, tool_meta = build_tools(tool_ctx)
        plugin_registry = PluginRegistry(self.config.plugin_dirs, event_bus=bus)
        try:
            plugin_tools = plugin_registry.load()
        except Exception as exc:
            plugin_tools = []
            errors.append(f"plugins: {exc}")
            bus.emit("error", "prepare", f"插件加载失败：{exc}")
            bus.emit(
                "fallback_applied",
                "prepare",
                "插件加载失败，继续使用内置工具",
                component="plugins",
                strategy="continue_without_plugins",
                error=str(exc),
            )
        for item in plugin_tools:
            tools.append(item)
            spec = plugin_registry.metadata(item.name)
            tool_meta[item.name] = ToolPermission(
                name=item.name,
                read_only=bool(spec and spec.read_only),
                destructive=bool(spec and spec.destructive),
            )
        if plugin_tools:
            bus.emit(
                "plugin_tools_loaded",
                "prepare",
                f"loaded {len(plugin_tools)} plugin tools",
                tools=[item.name for item in plugin_tools],
            )
        raw_model = build_chat_model()

        # 可选 MCP：动态发现只读工具并合入同一个 Tool 池。
        if self.config.enable_mcp:
            server_script = self.config.mcp_server_script or Path(__file__).with_name("mcp_server.py")
            try:
                mcp_tools = load_mcp_tools(self.config.workspace, server_script)
                for item in mcp_tools:
                    tools.append(item)
                    # 本 demo 的 MCP server 只暴露只读工具。
                    tool_meta[item.name] = ToolPermission(
                        name=item.name, read_only=True, concurrency_safe=True
                    )
                bus.emit(
                    "mcp_tools_loaded",
                    "prepare",
                    f"loaded {len(mcp_tools)} MCP tools",
                    tools=[item.name for item in mcp_tools],
                )
            except Exception as exc:
                errors.append(f"mcp: {exc}")
                bus.emit("error", "prepare", f"MCP 加载失败，继续无 MCP 运行：{exc}")
                bus.emit(
                    "fallback_applied",
                    "prepare",
                    "MCP 不可用，继续使用内置/插件工具",
                    component="mcp",
                    strategy="continue_without_mcp",
                    error=str(exc),
                )

        # Claude Code 的 AgentTool/Task：只读子 Agent，拥有隔离上下文。
        # MCP 放在这里之前，让子 Agent 也能使用已发现的只读 MCP 工具。
        read_only_tools = [
            item for item in tools if tool_meta[item.name].read_only
        ]
        task_tools = build_task_tools(raw_model, read_only_tools, bus)
        for item in task_tools:
            tools.append(item)
            tool_meta[item.name] = permission_for_tool(item.name)

        tool_map = {item.name: item for item in tools}
        model = raw_model.bind_tools(tools)
        planner = build_chat_model().with_structured_output(TodoPlan, method="function_calling")

        def prepare_node(state: ClaudeState) -> dict:
            with bus.stage("prepare", "读取 CLAUDE.md、session memory 和环境"):
                messages = context.initial_messages(state["task"], todos.to_text())
                bus.emit(
                    "context_prepared",
                    "prepare",
                    "上下文已构建",
                    claude_md_chars=len(context.claude_md),
                    session_memory_chars=len(context.session_memory),
                    message_count=len(messages),
                    context_snapshot=context.snapshot(state["task"], todos.to_text()),
                    messages=serialize_messages(messages),
                )
                return {"messages": messages}

        def plan_node(state: ClaudeState) -> dict:
            with bus.stage("plan", "生成 TodoWrite 计划"):
                prompt = [
                    SystemMessage(
                        content=(
                            "你是 Claude Code 的规划器。根据任务、CLAUDE.md 和环境，"
                            "用 TodoWrite 风格给出 3 到 6 个可执行步骤。"
                        )
                    ),
                    HumanMessage(
                        content=f"任务：\n{state['task']}\n\nCLAUDE.md：\n{context.claude_md}\n\n环境：\n{context.environment}"
                    ),
                ]
                try:
                    plan = planner.invoke(prompt)
                    if not isinstance(plan, TodoPlan):
                        plan = TodoPlan.model_validate(plan)
                    if not plan.items:
                        raise ValueError("空计划")
                except Exception as exc:
                    errors.append(f"planner: {exc}")
                    bus.emit(
                        "fallback_applied",
                        "plan",
                        "自动规划失败，使用确定性的默认 Todo",
                        component="planner",
                        strategy="use_default_todo",
                        error=str(exc),
                    )
                    plan = TodoPlan(
                        summary="先探索、再修改、最后验证并更新 Todo。",
                        items=[
                            TodoItem(content="探索相关文件并确认问题"),
                            TodoItem(content="做最小代码修改"),
                            TodoItem(content="运行测试并更新 Todo"),
                        ],
                    )
                todos.set(plan)
                bus.emit("todo_created", "plan", "Todo 已创建", plan=plan.model_dump())
                plan_message = HumanMessage(content=f"# Current Todo\n{todos.to_text()}")
                messages = [*state["messages"], plan_message]
                bus.emit(
                    "context_assembled",
                    "plan",
                    "完整上下文（含 Todo）已装配为模型消息",
                    message_count=len(messages),
                    context_snapshot=context.snapshot(state["task"], todos.to_text()),
                    messages=serialize_messages(messages),
                )
                return {"todos": todos.items, "messages": messages}

        def model_node(state: ClaudeState) -> dict:
            with bus.stage("model", f"第 {state['turn'] + 1} 次模型采样"):
                compacted = context.maybe_compact(state["messages"])
                if compacted.method != "none":
                    bus.emit(
                        "context_compacted",
                        "model",
                        f"{compacted.method}: {compacted.removed} messages",
                        method=compacted.method,
                        before_tokens=compacted.before_tokens,
                        after_tokens=compacted.after_tokens,
                    )
                bus.emit("model_request", "model", "request", turn=state["turn"] + 1)
                try:
                    response = model.invoke(compacted.messages)
                except Exception as exc:
                    errors.append(f"model: {exc}")
                    bus.emit("error", "model", f"模型调用失败：{exc}")
                    bus.emit(
                        "failure_summary",
                        "模型调用失败，转入 finalize 返回失败答案",
                        component="model",
                        strategy="return_failure_answer",
                        error=str(exc),
                    )
                    response = AIMessage(content=f"运行失败：{exc}")
                text = message_text(response)
                if text:
                    bus.emit("agent_message", "model", text)
                usage = getattr(response, "usage_metadata", None) or {}
                if usage:
                    bus.emit("token_usage", "model", "token usage", **usage)
                return {
                    "messages": [*compacted.messages, response],
                    "turn": state["turn"] + 1,
                }

        def route_after_model(state: ClaudeState) -> Literal["tools", "finalize"]:
            last = state["messages"][-1] if state["messages"] else None
            return "tools" if getattr(last, "tool_calls", None) else "finalize"

        def tools_node(state: ClaudeState) -> dict:
            with bus.stage("tools", "执行 tool_use 并回填 tool_result"):
                last = state["messages"][-1]
                tool_messages: list[ToolMessage] = []
                for call in getattr(last, "tool_calls", None) or []:
                    name = call.get("name", "unknown")
                    args = call.get("args", {})
                    call_id = call.get("id", f"call-{uuid.uuid4().hex[:8]}")
                    meta = tool_meta.get(name)
                    decision = (
                        tool_ctx.permissions.decide(meta, args)
                        if meta is not None
                        else None
                    )
                    bus.emit(
                        "permission_decision",
                        "tools",
                        f"{name}: {decision.behavior}" if decision else f"{name}: unknown tool",
                        tool=name,
                        behavior=decision.behavior if decision else "deny",
                        reason=decision.reason if decision else "unknown tool",
                    )
                    if decision is None or not decision.allowed:
                        output = f"ERROR: permission denied — {decision.reason if decision else 'unknown tool'}"
                        tool_messages.append(
                            ToolMessage(content=output, tool_call_id=call_id, name=name, status="error")
                        )
                        bus.emit(
                            "fallback_applied",
                            "tools",
                            "权限拒绝已作为工具错误回填给模型",
                            component="permission",
                            strategy="return_permission_denial_to_model",
                            tool=name,
                            call_id=call_id,
                        )
                        continue

                    hook = tool_ctx.hooks.before(name, args)
                    if not hook.allow:
                        output = f"ERROR: blocked by pre-tool hook — {hook.reason}"
                        tool_messages.append(
                            ToolMessage(content=output, tool_call_id=call_id, name=name, status="error")
                        )
                        bus.emit(
                            "fallback_applied",
                            "tools",
                            "前置 Hook 阻止了工具执行，错误已回填给模型",
                            component="hook",
                            strategy="return_hook_denial_to_model",
                            tool=name,
                            call_id=call_id,
                        )
                        continue
                    actual_args = hook.updated_args or args
                    bus.emit("tool_started", "tools", "", tool=name, args=actual_args, call_id=call_id)
                    tool_started = time.perf_counter()
                    try:
                        target = tool_map.get(name)
                        if target is None:
                            output, status = f"ERROR: unknown tool {name}", "error"
                        else:
                            output, status = str(target.invoke(actual_args)), "success"
                    except Exception as exc:
                        output, status = f"ERROR: {type(exc).__name__}: {exc}", "error"
                        errors.append(f"{name}: {exc}")
                    tool_ctx.hooks.after(name, actual_args, output)
                    bus.emit(
                        "tool_finished",
                        "tools",
                        output,
                        tool=name,
                        status=status,
                        elapsed_ms=round((time.perf_counter() - tool_started) * 1000, 2),
                        call_id=call_id,
                    )
                    if status == "error":
                        bus.emit(
                            "fallback_applied",
                            "tools",
                            "工具错误已转成 ToolMessage，交回模型决定下一步",
                            component="tool",
                            strategy="return_tool_error_to_model",
                            tool=name,
                            call_id=call_id,
                        )
                    tool_messages.append(
                        ToolMessage(content=output, tool_call_id=call_id, name=name, status=status)
                    )
                return {
                    "messages": [*state["messages"], *tool_messages],
                    "todos": todos.items,
                }

        def route_after_tools(state: ClaudeState) -> Literal["compact", "finalize"]:
            return "compact" if state["turn"] < self.config.max_turns else "finalize"

        def compact_node(state: ClaudeState) -> dict:
            with bus.stage("compact", "检查上下文预算并压缩"):
                result = context.maybe_compact(state["messages"])
                if result.method != "none":
                    bus.emit(
                        "context_compacted",
                        "compact",
                        result.method,
                        method=result.method,
                        before_tokens=result.before_tokens,
                        after_tokens=result.after_tokens,
                    )
                return {
                    "messages": result.messages,
                    "compactions": state["compactions"] + (1 if result.method != "none" else 0),
                }

        def finalize_node(state: ClaudeState) -> dict:
            with bus.stage("finalize", "保存 session memory 并生成最终结果"):
                last = state["messages"][-1] if state["messages"] else None
                final = message_text(last) if last is not None else ""
                if not final:
                    bus.emit(
                        "limit_reached",
                        "finalize",
                        "达到最大模型轮数，返回部分结果",
                        component="loop",
                        strategy="stop_at_max_turns",
                        max_turns=self.config.max_turns,
                    )
                    final = "达到最大模型轮数，尚未得到最终 assistant message。"
                context.save_session_memory(
                    task=state["task"],
                    todo_text=todos.to_text(),
                    final=final,
                    changed_files=changes.changed_files(),
                    commands=[item.command for item in commands],
                )
                bus.emit("query_completed", "finalize", final)
                return {"final": final, "done": True}

        builder = StateGraph(ClaudeState)
        builder.add_node("prepare", prepare_node)
        builder.add_node("plan", plan_node)
        builder.add_node("model", model_node)
        builder.add_node("tools", tools_node)
        builder.add_node("compact", compact_node)
        builder.add_node("finalize", finalize_node)
        builder.add_edge(START, "prepare")
        builder.add_edge("prepare", "plan")
        builder.add_edge("plan", "model")
        builder.add_conditional_edges(
            "model",
            route_after_model,
            {"tools": "tools", "finalize": "finalize"},
        )
        builder.add_conditional_edges(
            "tools",
            route_after_tools,
            {"compact": "compact", "finalize": "finalize"},
        )
        builder.add_edge("compact", "model")
        builder.add_edge("finalize", END)
        graph = builder.compile(checkpointer=InMemorySaver())

        state: ClaudeState = {
            "task": task,
            "messages": [],
            "todos": [],
            "final": "",
            "turn": 0,
            "compactions": 0,
            "done": False,
        }
        verification_passed: bool | None = None
        try:
            result = graph.invoke(
                state,
                config={"configurable": {"thread_id": f"claude-{run_id}"}},
            )
            final = result.get("final", "")
            compactions = int(result.get("compactions", 0))

            if self.config.verify_command:
                with bus.stage("verify", "执行最终验证命令"):
                    existing = next(
                        (item for item in reversed(commands) if item.command == self.config.verify_command),
                        None,
                    )
                    if existing is None:
                        bash_meta = tool_meta.get("Bash")
                        decision = (
                            tool_ctx.permissions.decide(bash_meta, {"command": self.config.verify_command})
                            if bash_meta is not None
                            else None
                        )
                        if decision is None or not decision.allowed:
                            verification_passed = False
                            bus.emit(
                                "permission_decision",
                                "verify",
                                f"verification denied: {decision.reason if decision else 'missing Bash tool'}",
                                tool="Bash",
                                behavior="deny",
                            )
                        else:
                            bash_tool = tool_map.get("Bash")
                            if bash_tool is not None:
                                bash_tool.invoke({"command": self.config.verify_command})
                                existing = commands[-1] if commands else None
                    verification_passed = bool(existing and existing.returncode == 0)
                    bus.emit(
                        "verification_completed",
                        "verify",
                        f"{self.config.verify_command} → exit {existing.returncode if existing else 'n/a'}",
                        returncode=existing.returncode if existing else None,
                    )
        except Exception as exc:
            errors.append(str(exc))
            bus.emit("error", "harness", f"运行失败：{exc}")
            final = f"运行失败：{exc}"
        finally:
            bus.close()

        if changes.records:
            (run_dir / "changes.diff").write_text(changes.diff_text(), encoding="utf-8")
        (run_dir / "summary.md").write_text(
            "\n".join(
                [
                    "# Claude-Style Run Summary",
                    "",
                    f"- Task: {task}",
                    f"- Verification: {verification_passed if verification_passed is not None else 'not configured'}",
                    f"- Changed files: {', '.join(changes.changed_files()) if changes.changed_files() else '(none)'}",
                    "",
                    "## Todo",
                    todos.to_text(),
                    "",
                    "## Final Answer",
                    final,
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        success = bool(final) and verification_passed is not False
        return ClaudeRunResult(
            task=task,
            final_answer=final,
            todos=todos,
            changed_files=changes.changed_files(),
            commands=commands,
            run_dir=run_dir,
            timeline_path=run_dir / "timeline.md",
            success=success,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            compactions=compactions,
            errors=errors,
        )
