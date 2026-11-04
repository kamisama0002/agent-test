"""Mini Codex 的核心 Harness。

结构对应 Codex 的开源 run_turn 循环：
1. 准备上下文；
2. 规划；
3. 采样模型；
4. 如果模型返回工具调用 → 执行工具 → 把结果放回上下文 → 再次采样；
5. 如果模型只返回 assistant message → 本轮结束；
6. 验证、汇总并写入事件时间线。

这里没有把循环藏进黑盒，而是显式展示每一步，便于学习和调试。
"""

# Codex refs: codex-rs/core/src/session/turn.rs::run_turn; turn_context.rs::TurnContext; protocol/src/protocol.rs::EventMsg
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from langchain_cases.common import build_chat_model, message_text
from .config import HarnessConfig
from .context import ContextManager
from .events import EventBus
from .multi_agent import READ_ONLY_TOOL_NAMES, build_codex_agent_tools
from .state import ChangeTracker, CommandRecord, Plan, PlanState
from .tools import ToolContext, build_tools


@dataclass
class RunResult:
    task: str
    final_answer: str
    plan: PlanState
    changed_files: list[str]
    commands: list[CommandRecord]
    run_dir: Path
    timeline_path: Path
    success: bool
    elapsed_ms: float
    errors: list[str] = field(default_factory=list)


class MiniCodexHarness:
    """开发场景的 LangChain Agent Harness。"""

    def __init__(self, config: HarnessConfig) -> None:
        self.config = config

    def _plan(self, task: str, context: ContextManager, bus: EventBus) -> Plan:
        """规划阶段：先产出可检查的步骤，再开始工具循环。"""

        planner = build_chat_model().with_structured_output(Plan, method="function_calling")
        prompt = [
            SystemMessage(
                content=(
                    "你是开发任务的规划器。根据任务、仓库环境和 AGENTS.md，"
                    "给出 3 到 6 个可执行步骤。不要把执行结果当成事实，"
                    "步骤要围绕检查、修改、验证、总结。"
                )
            ),
            HumanMessage(
                content=(
                    f"任务：\n{task}\n\n"
                    f"仓库环境：\n{context.environment}\n\n"
                    f"AGENTS.md：\n{context.agents_md or '(none)'}\n\n"
                    "可用工具：list_files、read_file、search_text、write_file、"
                    "replace_in_file、run_command、git_status、git_diff、update_plan。"
                )
            ),
        ]
        try:
            result = planner.invoke(prompt)
            if isinstance(result, Plan):
                plan = result
            else:
                plan = Plan.model_validate(result)
            if not plan.items:
                raise ValueError("模型返回了空计划")
            return plan
        except Exception as exc:
            bus.emit("warning", "plan", f"结构化规划失败，使用默认计划：{exc}")
            return Plan(
                summary="先检查仓库，再完成修改，最后运行验证并总结。",
                items=[
                    {"title": "检查仓库和任务相关文件", "status": "pending"},
                    {"title": "实现最小代码修改", "status": "pending"},
                    {"title": "运行测试或验证命令", "status": "pending"},
                    {"title": "检查变更并总结", "status": "pending"},
                ],
            )

    def run(self, task: str) -> RunResult:
        started = time.perf_counter()
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        run_dir = (self.config.trace_root or self.config.workspace / ".mini_codex" / "runs") / run_id
        bus = EventBus(run_dir, console=self.config.console)
        errors: list[str] = []
        plan_state = PlanState()
        changes = ChangeTracker()
        commands: list[CommandRecord] = []
        final_answer = ""
        verification_passed: bool | None = None
        tool_map: dict[str, Any] = {}

        bus.emit("run_started", "bootstrap", f"task={task}", workspace=str(self.config.workspace))

        try:
            with bus.stage("bootstrap", "校验 workspace、模型和运行目录"):
                if not self.config.workspace.exists():
                    raise FileNotFoundError(self.config.workspace)
                bus.emit("workspace_ready", "bootstrap", str(self.config.workspace))

            with bus.stage("context", "加载 AGENTS.md、环境上下文和 token 预算"):
                context = ContextManager(self.config.workspace, self.config.token_budget)
                bus.emit(
                    "context_built",
                    "context",
                    "上下文构建完成",
                    agents_md_chars=len(context.agents_md),
                    environment_chars=len(context.environment),
                    token_budget=self.config.token_budget,
                )

            with bus.stage("plan", "先生成计划，再进入工具循环"):
                plan = self._plan(task, context, bus)
                plan_state.set(plan)
                bus.emit("plan_created", "plan", "计划已生成", plan=plan.model_dump())

            with bus.stage("agent", "模型采样 → 工具执行 → 观察结果 → 继续采样"):
                plan_text = plan_state.to_text()
                messages = context.initial_messages(task, plan_text)
                tool_ctx = ToolContext(
                    workspace=self.config.workspace,
                    plan=plan_state,
                    changes=changes,
                    commands=commands,
                    event_bus=bus,
                    command_timeout=self.config.command_timeout,
                )
                tools = build_tools(tool_ctx)
                if self.config.enable_mcp:
                    from .mcp_client import load_mcp_tools

                    server_script = (
                        self.config.mcp_server_script
                        or Path(__file__).resolve().parent.parent / "claude_harness" / "mcp_server.py"
                    )
                    try:
                        mcp_tools = load_mcp_tools(self.config.workspace, server_script)
                        tools.extend(mcp_tools)
                        bus.emit(
                            "mcp_tools_loaded",
                            "agent",
                            f"loaded {len(mcp_tools)} MCP tools",
                            tools=[item.name for item in mcp_tools],
                        )
                    except Exception as exc:
                        errors.append(f"mcp: {exc}")
                        bus.emit("error", "agent", f"MCP 加载失败：{exc}")
                if self.config.enable_multi_agent:
                    read_only_tools = [
                        item for item in tools if item.name in READ_ONLY_TOOL_NAMES
                    ]
                    tools.extend(
                        build_codex_agent_tools(
                            build_chat_model(), read_only_tools, bus
                        )
                    )
                tool_map = {item.name: item for item in tools}
                model = build_chat_model().bind_tools(tools)
                seen_calls: dict[str, int] = {}

                for step in range(1, self.config.max_steps + 1):
                    messages, removed = context.compact(messages)
                    if removed:
                        bus.emit(
                            "context_compacted",
                            "agent",
                            f"上下文压缩：省略 {removed} 条旧消息",
                            removed=removed,
                            estimated_tokens=ContextManager.estimate_tokens(messages),
                        )

                    bus.emit("model_request", "agent", f"第 {step} 次模型采样", step=step)
                    try:
                        response: AIMessage = model.invoke(messages)
                    except Exception as exc:
                        errors.append(f"model: {exc}")
                        bus.emit("error", "agent", f"模型调用失败：{exc}")
                        break

                    messages.append(response)
                    text = message_text(response)
                    if text:
                        bus.emit("agent_message", "agent", text)
                    usage = getattr(response, "usage_metadata", None) or {}
                    if usage:
                        bus.emit("token_usage", "agent", "token usage", **usage)

                    tool_calls = list(getattr(response, "tool_calls", None) or [])
                    if not tool_calls:
                        final_answer = text or "模型没有返回最终文本。"
                        bus.emit("turn_completed", "agent", "模型完成本轮，无更多工具调用", step=step)
                        break

                    for call in tool_calls:
                        name = call.get("name") or "unknown"
                        args = call.get("args") or {}
                        call_id = call.get("id") or f"call-{uuid.uuid4().hex[:8]}"
                        signature = name + ":" + json.dumps(args, ensure_ascii=False, sort_keys=True)
                        seen_calls[signature] = seen_calls.get(signature, 0) + 1
                        if seen_calls[signature] > 2:
                            errors.append(f"repeated_tool_call:{name}")
                            bus.emit("error", "agent", f"检测到重复工具调用：{name}")
                            final_answer = "停止：模型重复调用同一个工具，需要人工调整提示词或工具结果。"
                            break

                        bus.emit("tool_started", "agent", "", tool=name, args=args, call_id=call_id)
                        tool_started = time.perf_counter()
                        try:
                            target = tool_map.get(name)
                            if target is None:
                                output = f"ERROR: 未知工具 {name}"
                                status = "error"
                            else:
                                output = target.invoke(args)
                                status = "ok"
                        except Exception as exc:
                            output = f"ERROR: {type(exc).__name__}: {exc}"
                            status = "error"
                            errors.append(f"{name}: {exc}")
                        elapsed_ms = (time.perf_counter() - tool_started) * 1000
                        messages.append(
                            ToolMessage(
                                content=str(output),
                                tool_call_id=call_id,
                                name=name,
                                status="success" if status == "ok" else "error",
                            )
                        )
                        bus.emit(
                            "tool_finished",
                            "agent",
                            str(output),
                            tool=name,
                            status=status,
                            elapsed_ms=round(elapsed_ms, 2),
                            call_id=call_id,
                        )
                    if final_answer.startswith("停止："):
                        break

                if not final_answer:
                    final_answer = "达到最大步骤数，尚未得到最终回答。"

            with bus.stage("verify", "检查测试/lint 结果"):
                if self.config.verify_command:
                    existing = next(
                        (item for item in reversed(commands) if item.command == self.config.verify_command),
                        None,
                    )
                    if existing is None:
                        verify_tool = tool_map.get("run_command")
                        if verify_tool is None:
                            raise RuntimeError("run_command 工具未初始化")
                        output = verify_tool.invoke({"command": self.config.verify_command})
                        existing = commands[-1] if commands else None
                    else:
                        output = existing.output
                    verification_passed = bool(existing and existing.returncode == 0)
                    bus.emit(
                        "verification_completed",
                        "verify",
                        f"{self.config.verify_command} → {output[:500]}",
                        returncode=existing.returncode if existing else None,
                    )
                else:
                    bus.emit("verification_skipped", "verify", "未配置 verify_command")

            with bus.stage("finalize", "汇总变更、计划、测试和事件"):
                changed_files = changes.changed_files()
                if changes.records:
                    (run_dir / "changes.diff").write_text(changes.diff_text(), encoding="utf-8")
                summary = [
                    "# Mini Codex Run Summary",
                    "",
                    f"- Task: {task}",
                    f"- Verification: {verification_passed if verification_passed is not None else 'not configured'}",
                    f"- Changed files: {', '.join(changed_files) if changed_files else '(none)'}",
                    "",
                    "## Plan",
                    "",
                    plan_state.to_text(),
                    "",
                    "## Final Answer",
                    "",
                    final_answer,
                    "",
                    "## Commands",
                    "",
                ]
                for command in commands:
                    summary.append(f"- `{command.command}` → exit {command.returncode}")
                (run_dir / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
                bus.emit(
                    "run_completed",
                    "finalize",
                    "运行完成",
                    changed_files=changed_files,
                    verification_passed=verification_passed,
                )

        except Exception as exc:
            errors.append(str(exc))
            bus.emit("error", "harness", f"运行失败：{exc}")
            final_answer = final_answer or f"运行失败：{exc}"
        finally:
            bus.close()

        elapsed_ms = (time.perf_counter() - started) * 1000
        success = bool(final_answer) and (verification_passed is not False)
        return RunResult(
            task=task,
            final_answer=final_answer,
            plan=plan_state,
            changed_files=changes.changed_files(),
            commands=commands,
            run_dir=run_dir,
            timeline_path=run_dir / "timeline.md",
            success=success,
            elapsed_ms=elapsed_ms,
            errors=errors,
        )
