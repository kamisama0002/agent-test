"""DeepSeek Harness 主循环。

这不是简单复制 Codex：DeepSeek 套件额外展示推理模型常见的三件事：

1. 将 reasoning_content 与最终正文分开记录；
2. 对模型调用做有限重试，并把重试决策写入事件流；
3. 每个模型/工具步骤写 checkpoint，失败时能从证据链定位断点。

工具、审批、插件、MCP 和多 Agent 复用 agent_runtime 与 mini_codex 的
共享实现，保证四套 Harness 的边界一致、对比公平。
"""

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
from agent_runtime.approval import ApprovalManager
from agent_runtime.observability import serialize_messages
from agent_runtime.plugins import PluginRegistry
from mini_codex.events import EventBus
from mini_codex.multi_agent import READ_ONLY_TOOL_NAMES, build_codex_agent_tools
from mini_codex.state import ChangeTracker, CommandRecord, Plan, PlanState
from mini_codex.tools import ToolContext, build_tools
from .config import DeepSeekHarnessConfig
from .context import DeepSeekContextManager


@dataclass
class DeepSeekRunResult:
    task: str
    final_answer: str
    plan: PlanState
    changed_files: list[str]
    commands: list[CommandRecord]
    run_dir: Path
    timeline_path: Path
    success: bool
    elapsed_ms: float
    checkpoints: int = 0
    retries: int = 0
    errors: list[str] = field(default_factory=list)


class DeepSeekHarness:
    """带推理内容记录、重试和 checkpoint 的 DeepSeek 编码 Harness。"""

    def __init__(
        self,
        config: DeepSeekHarnessConfig,
        *,
        model: Any | None = None,
        planner: Any | None = None,
    ) -> None:
        self.config = config
        self.model = model or build_chat_model(
            **( {"model": config.model_name} if config.model_name else {} )
        )
        self.planner = planner
        self.checkpoints = 0
        self.retries = 0

    @staticmethod
    def _reasoning_text(response: Any) -> str:
        """兼容不同 DashScope/OpenAI 兼容层的推理字段位置。"""

        additional = getattr(response, "additional_kwargs", None) or {}
        metadata = getattr(response, "response_metadata", None) or {}
        for source in (additional, metadata):
            value = source.get("reasoning_content") or source.get("reasoning")
            if isinstance(value, str) and value.strip():
                return value
        content = getattr(response, "content", None)
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") in {"reasoning", "thinking"}:
                        value = block.get("reasoning") or block.get("text")
                        if isinstance(value, str):
                            parts.append(value)
            return "\n".join(parts)
        return ""

    def _invoke_model(
        self,
        model: Any,
        messages: list[Any],
        bus: EventBus,
        *,
        step: int,
    ) -> Any | None:
        total_attempts = self.config.max_model_retries + 1
        for attempt in range(1, total_attempts + 1):
            try:
                response = model.invoke(messages)
                if attempt > 1:
                    bus.emit(
                        "retry_succeeded",
                        "agent",
                        f"第 {step} 步模型调用在第 {attempt} 次尝试成功",
                        step=step,
                        attempt=attempt,
                    )
                return response
            except Exception as exc:
                errors_text = f"{type(exc).__name__}: {exc}"
                if attempt < total_attempts:
                    self.retries += 1
                    bus.emit("error", "agent", f"模型调用失败：{errors_text}")
                    bus.emit(
                        "retry_scheduled",
                        "agent",
                        f"模型调用失败，{self.config.retry_delay_seconds}s 后重试",
                        step=step,
                        attempt=attempt,
                        max_attempts=total_attempts,
                        error=errors_text,
                    )
                    if self.config.retry_delay_seconds > 0:
                        time.sleep(self.config.retry_delay_seconds)
                    continue
                bus.emit("error", "agent", f"模型调用失败：{errors_text}")
                bus.emit(
                    "failure_summary",
                    "agent",
                    "模型在有限重试后仍失败，安全终止",
                    component="model",
                    strategy="return_failure_answer_after_retries",
                    attempts=attempt,
                    error=errors_text,
                )
                return None
        return None

    def _save_checkpoint(
        self,
        run_dir: Path,
        bus: EventBus,
        *,
        step: int,
        phase: str,
        messages: list[Any],
        plan_state: PlanState,
        changes: ChangeTracker,
        commands: list[CommandRecord],
    ) -> None:
        self.checkpoints += 1
        path = run_dir / "checkpoint.json"
        payload = {
            "step": step,
            "phase": phase,
            "plan": plan_state.to_text(),
            "messages": serialize_messages(messages),
            "changed_files": changes.changed_files(),
            "commands": [
                {"command": item.command, "returncode": item.returncode}
                for item in commands
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        bus.emit(
            "checkpoint_saved",
            "agent",
            f"checkpoint: step={step} phase={phase}",
            step=step,
            phase=phase,
            path=str(path),
        )

    def _plan(self, task: str, context: DeepSeekContextManager, bus: EventBus) -> Plan:
        prompt = [
            SystemMessage(
                content=(
                    "你是 DeepSeek 编码任务规划器。根据任务、项目规则和环境，"
                    "给出 3 到 6 个可执行步骤。步骤必须围绕检查、修改、验证、总结。"
                )
            ),
            HumanMessage(
                content=(
                    f"任务：\n{task}\n\n"
                    f"环境：\n{context.environment}\n\n"
                    f"项目规则：\n{context.project_instructions or '(none)'}"
                )
            ),
        ]
        try:
            planner = self.planner
            if planner is None:
                planner = self.model.with_structured_output(Plan, method="function_calling")
            result = planner.invoke(prompt)
            plan = result if isinstance(result, Plan) else Plan.model_validate(result)
            if not plan.items:
                raise ValueError("模型返回空计划")
            return plan
        except Exception as exc:
            bus.emit("warning", "plan", f"结构化规划失败，使用默认计划：{exc}")
            bus.emit(
                "fallback_applied",
                "plan",
                "规划失败，已切换到确定性的默认计划",
                component="planner",
                strategy="use_default_plan",
                error=str(exc),
            )
            return Plan(
                summary="先检查仓库，再实现最小修改，最后验证并总结。",
                items=[
                    {"title": "检查仓库和任务相关文件", "status": "pending"},
                    {"title": "实现最小代码修改", "status": "pending"},
                    {"title": "运行测试或验证命令", "status": "pending"},
                    {"title": "检查变更并总结", "status": "pending"},
                ],
            )

    def run(self, task: str) -> DeepSeekRunResult:
        started = time.perf_counter()
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        run_dir = (self.config.trace_root or self.config.workspace / ".deepseek" / "runs") / run_id
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

            with bus.stage("context", "加载 DEEPSEEK.md/AGENTS.md、session memory 和环境"):
                context = DeepSeekContextManager(
                    self.config.workspace,
                    self.config.token_budget,
                    self.config.model_name or "config-default",
                )
                bus.emit(
                    "context_built",
                    "context",
                    "DeepSeek 上下文构建完成",
                    message_count=0,
                    token_budget=self.config.token_budget,
                    context_snapshot=context.snapshot(task),
                )

            with bus.stage("plan", "先用结构化输出生成计划，再进入工具循环"):
                plan = self._plan(task, context, bus)
                plan_state.set(plan)
                bus.emit("plan_created", "plan", "计划已生成", plan=plan.model_dump())

            with bus.stage("agent", "模型推理 → 工具执行 → 观察 → 再推理"):
                plan_text = plan_state.to_text()
                messages = context.initial_messages(task, plan_text)
                bus.emit(
                    "context_assembled",
                    "agent",
                    "完整 DeepSeek 上下文已装配为模型消息",
                    message_count=len(messages),
                    context_snapshot=context.snapshot(task, plan_text),
                    messages=serialize_messages(messages),
                )

                tool_ctx = ToolContext(
                    workspace=self.config.workspace,
                    plan=plan_state,
                    changes=changes,
                    commands=commands,
                    event_bus=bus,
                    command_timeout=self.config.command_timeout,
                    approval=ApprovalManager(self.config.approval_mode),
                )
                tools = build_tools(tool_ctx)

                plugin_registry = PluginRegistry(self.config.plugin_dirs, event_bus=bus)
                try:
                    plugin_tools = plugin_registry.load()
                except Exception as exc:
                    plugin_tools = []
                    errors.append(f"plugins: {exc}")
                    bus.emit("error", "agent", f"插件加载失败：{exc}")
                    bus.emit(
                        "fallback_applied",
                        "agent",
                        "插件加载失败，继续使用内置工具",
                        component="plugins",
                        strategy="continue_without_plugins",
                        error=str(exc),
                    )
                if plugin_tools:
                    tools.extend(plugin_tools)
                    bus.emit(
                        "plugin_tools_loaded",
                        "agent",
                        f"loaded {len(plugin_tools)} plugin tools",
                        tools=[item.name for item in plugin_tools],
                    )

                if self.config.enable_mcp:
                    from mini_codex.mcp_client import load_mcp_tools

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
                        bus.emit(
                            "fallback_applied",
                            "agent",
                            "MCP 不可用，继续使用内置/插件工具",
                            component="mcp",
                            strategy="continue_without_mcp",
                            error=str(exc),
                        )

                if self.config.enable_multi_agent:
                    read_only_tools = [item for item in tools if item.name in READ_ONLY_TOOL_NAMES]
                    agent_tools = build_codex_agent_tools(self.model, read_only_tools, bus)
                    tools.extend(agent_tools)
                    bus.emit(
                        "multi_agent_tools_loaded",
                        "agent",
                        f"loaded {len(agent_tools)} multi-agent tools",
                        tools=[item.name for item in agent_tools],
                    )

                tool_map = {item.name: item for item in tools}
                model = self.model.bind_tools(tools)
                seen_calls: dict[str, int] = {}

                for step in range(1, self.config.max_steps + 1):
                    messages, removed = context.compact(messages)
                    if removed:
                        bus.emit(
                            "context_compacted",
                            "agent",
                            f"上下文压缩：省略 {removed} 条旧消息",
                            removed=removed,
                            estimated_tokens=DeepSeekContextManager.estimate_tokens(messages),
                        )
                    bus.emit("model_request", "agent", f"第 {step} 次模型推理", step=step)
                    response = self._invoke_model(model, messages, bus, step=step)
                    if response is None:
                        final_answer = "运行失败：模型在有限重试后仍不可用。"
                        break

                    messages.append(response)
                    reasoning = self._reasoning_text(response)
                    if reasoning:
                        bus.emit(
                            "reasoning_content",
                            "agent",
                            reasoning,
                            step=step,
                            chars=len(reasoning),
                        )
                    text = message_text(response)
                    if text:
                        bus.emit("agent_message", "agent", text)
                    usage = getattr(response, "usage_metadata", None) or {}
                    if usage:
                        bus.emit("token_usage", "agent", "token usage", **usage)

                    self._save_checkpoint(
                        run_dir, bus, step=step, phase="model",
                        messages=messages, plan_state=plan_state, changes=changes, commands=commands,
                    )

                    tool_calls = list(getattr(response, "tool_calls", None) or [])
                    if not tool_calls:
                        final_answer = text or "模型没有返回最终文本。"
                        bus.emit("turn_completed", "agent", "模型完成本轮，无更多工具调用", step=step)
                        break

                    stopped = False
                    for call in tool_calls:
                        name = call.get("name") or "unknown"
                        args = call.get("args") or {}
                        call_id = call.get("id") or f"call-{uuid.uuid4().hex[:8]}"
                        signature = name + ":" + json.dumps(args, ensure_ascii=False, sort_keys=True)
                        seen_calls[signature] = seen_calls.get(signature, 0) + 1
                        if seen_calls[signature] > 2:
                            errors.append(f"repeated_tool_call:{name}")
                            bus.emit("error", "agent", f"检测到重复工具调用：{name}")
                            bus.emit(
                                "failure_summary",
                                "检测到重复工具调用，停止循环",
                                component="model",
                                strategy="stop_on_repeated_tool_call",
                                tool=name,
                            )
                            final_answer = "停止：模型重复调用同一个工具，需要人工调整提示词或工具结果。"
                            stopped = True
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
                        if status == "error":
                            bus.emit(
                                "fallback_applied",
                                "agent",
                                "工具错误已转成 ToolMessage，交回模型决定下一步",
                                component="tool",
                                strategy="return_tool_error_to_model",
                                tool=name,
                                call_id=call_id,
                            )

                    self._save_checkpoint(
                        run_dir, bus, step=step, phase="tools",
                        messages=messages, plan_state=plan_state, changes=changes, commands=commands,
                    )
                    if stopped:
                        break
                else:
                    bus.emit(
                        "limit_reached",
                        "agent",
                        "达到最大模型步数，返回部分结果",
                        component="loop",
                        strategy="stop_at_max_steps",
                        max_steps=self.config.max_steps,
                    )
                    final_answer = "达到最大步骤数，尚未得到最终回答。"

            with bus.stage("verify", "检查测试或 lint 结果"):
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
                        f"{self.config.verify_command} → {str(output)[:500]}",
                        returncode=existing.returncode if existing else None,
                    )
                    if verification_passed is False:
                        bus.emit(
                            "failure_summary",
                            "verify",
                            "验证命令未通过，结果标记为失败",
                            component="verify",
                            strategy="mark_run_failed",
                            returncode=existing.returncode if existing else None,
                        )
                else:
                    bus.emit("verification_skipped", "verify", "未配置 verify_command")

            with bus.stage("finalize", "保存 session memory、变更、checkpoint 和摘要"):
                changed_files = changes.changed_files()
                if changes.records:
                    (run_dir / "changes.diff").write_text(changes.diff_text(), encoding="utf-8")
                context.save_session_memory(
                    task=task,
                    final=final_answer,
                    plan_text=plan_state.to_text(),
                    changed_files=changed_files,
                    commands=[item.command for item in commands],
                )
                summary = [
                    "# DeepSeek Harness Run Summary",
                    "",
                    f"- Task: {task}",
                    f"- Verification: {verification_passed if verification_passed is not None else 'not configured'}",
                    f"- Changed files: {', '.join(changed_files) if changed_files else '(none)'}",
                    f"- Checkpoints: {self.checkpoints}",
                    f"- Retries: {self.retries}",
                    "",
                    "## Plan",
                    "",
                    plan_state.to_text(),
                    "",
                    "## Final Answer",
                    "",
                    final_answer,
                ]
                (run_dir / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
                bus.emit(
                    "run_completed",
                    "finalize",
                    "运行完成",
                    changed_files=changed_files,
                    verification_passed=verification_passed,
                    checkpoints=self.checkpoints,
                    retries=self.retries,
                )
        except Exception as exc:
            errors.append(str(exc))
            bus.emit("error", "harness", f"运行失败：{exc}")
            bus.emit(
                "failure_summary",
                "harness",
                "Harness 外层异常，已保存可诊断结果",
                component="harness",
                strategy="return_failure_result",
                error=str(exc),
            )
            final_answer = final_answer or f"运行失败：{exc}"
        finally:
            bus.close()

        elapsed_ms = (time.perf_counter() - started) * 1000
        success = bool(final_answer) and not final_answer.startswith("运行失败") and verification_passed is not False
        return DeepSeekRunResult(
            task=task,
            final_answer=final_answer,
            plan=plan_state,
            changed_files=changes.changed_files(),
            commands=commands,
            run_dir=run_dir,
            timeline_path=run_dir / "timeline.md",
            success=success,
            elapsed_ms=elapsed_ms,
            checkpoints=self.checkpoints,
            retries=self.retries,
            errors=errors,
        )
