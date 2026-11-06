"""DeepSeek Harness 主循环（按官方源码重构的 mini 版）。

主要源码映射：
- packages/core/agent-loop/src/agent.ts::ReactLoopAgent.turn / step
- packages/core/agent-loop/src/tool-calls.ts::executeToolCalls
- packages/core/session/src/types.ts::SessionEventMap
- packages/core/session/src/index.ts::Session.append / deriveMessages
- packages/llm/llm-retry/src/index.ts::backoff / recover
- packages/compaction/compaction-basic/src/region.ts
- packages/compaction/compaction-tool-result-pruner/src/index.ts
- packages/session/session-checkpoint-policy/src/index.ts

本实现保留源码的核心不变量：
1. session event 是唯一真源，模型消息从 session 派生；
2. 一次 turn 由多个 step 组成，每个 step 一次模型请求加其工具调用；
3. tool/call 先持久化，再审批/执行，tool/result 以同一 callId 回填；
4. 重试属于打开的 step，先记录 llm/retry，再等待，再记录 llm/retry-started；
5. 压缩按 compaction/start -> prune -> summary -> end 记录；
6. 工具正文前、模型请求前、step 边界执行 session flush。

为保持教学项目可运行，省略 Cordis 插件树、完整 projection、
并行工具调度、AbortSignal、持久化 generation 与 subagent 的完整 seam。
"""

from __future__ import annotations

import json
import random
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
from agent_runtime.sandbox_sim import SandboxSimulator, sandbox_mode_for_approval
from mini_codex.events import EventBus
from mini_codex.multi_agent import READ_ONLY_TOOL_NAMES, build_codex_agent_tools
from mini_codex.state import ChangeTracker, CommandRecord, PlanState
from mini_codex.tools import ToolContext, build_tools
from .config import DeepSeekHarnessConfig
from .context import DeepSeekContextManager
from .session import DeepSeekSession
from .tool_pipeline import DeepSeekToolPipeline


READ_ONLY_TOOLS = set(READ_ONLY_TOOL_NAMES) | {
    "read_file", "list_files", "search_text", "git_status", "git_diff",
}


@dataclass
class DeepSeekRunResult:
    task: str
    final_answer: str
    plan: PlanState
    changed_files: list[str]
    commands: list[CommandRecord]
    run_dir: Path
    timeline_path: Path
    session_path: Path
    success: bool
    elapsed_ms: float
    turns: int = 1
    steps: int = 0
    flushes: int = 0
    retries: int = 0
    errors: list[str] = field(default_factory=list)


class DeepSeekHarness:
    """按 dsh session/agent-loop/tool-pipeline 复刻的 mini Harness。"""

    def __init__(
        self,
        config: DeepSeekHarnessConfig,
        *,
        model: Any | None = None,
    ) -> None:
        self.config = config
        self.model = model or build_chat_model(
            **({"model": config.model_name} if config.model_name else {})
        )
        self.resolved_model_name = (
            config.model_name
            or getattr(self.model, "model_name", None)
            or getattr(self.model, "model", None)
            or "config-default"
        )
        self.flushes = 0
        self.retries = 0
        self._fault_announced = False
        self._tool_fault_injected = False

    def _announce_fault(self, bus: EventBus, component: str, message: str) -> None:
        if self._fault_announced:
            return
        self._fault_announced = True
        bus.emit(
            "fault_injected",
            "agent" if component != "planner" else "plan",
            message,
            component=component,
            mode=self.config.fault_mode,
        )

    @staticmethod
    def _reasoning_text(response: Any) -> str:
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
                if isinstance(block, dict) and block.get("type") in {"reasoning", "thinking"}:
                    value = block.get("reasoning") or block.get("text")
                    if isinstance(value, str):
                        parts.append(value)
            return "\n".join(parts)
        return ""

    @staticmethod
    def _failure_code(exc: Exception) -> str:
        text = f"{type(exc).__name__}: {exc}".lower()
        if "timeout" in text or "timed out" in text:
            return "TIMEOUT"
        if "rate" in text and "limit" in text:
            return "RATE_LIMIT"
        if "connection" in text or "transport" in text:
            return "TRANSPORT"
        return "SERVER"

    def _retry_delay_ms(self, retry: int) -> int:
        exponent = min(retry - 1, 16)
        raw = min(
            self.config.retry_initial_delay_ms * (2 ** exponent),
            self.config.retry_max_delay_ms,
        )
        jitter = 1 - self.config.retry_jitter_ratio + 2 * self.config.retry_jitter_ratio * random.random()
        return int(min(raw * jitter, self.config.retry_max_delay_ms))

    def _invoke_model(
        self,
        model: Any,
        messages: list[Any],
        *,
        session: DeepSeekSession,
        turn: int,
        step: int,
    ) -> tuple[Any | None, dict[str, Any] | None]:
        total_attempts = self.config.max_model_retries + 1
        failure: dict[str, Any] | None = None
        for attempt in range(1, total_attempts + 1):
            try:
                if self.config.fault_mode == "model_error" and step == 1:
                    self._announce_fault(session.bus, "model", "已注入模型调用故障，用于观察 llm/retry")
                    raise RuntimeError("simulated model failure")
                return model.invoke(messages), None
            except Exception as exc:
                failure = {
                    "code": self._failure_code(exc),
                    "message": f"{type(exc).__name__}: {exc}",
                }
                if attempt >= total_attempts:
                    break
                self.retries += 1
                retry_id = uuid.uuid4().hex
                delay_ms = self._retry_delay_ms(attempt)
                session.append(
                    "llm/retry",
                    stage="agent",
                    message=f"model retry {attempt} scheduled in {delay_ms}ms",
                    data={
                        "retryId": retry_id,
                        "turn": turn,
                        "step": step,
                        "provider": "deepseek",
                        "mode": "normal",
                        "policyKey": f"deepseek:{self.config.max_model_retries}",
                        "retry": attempt,
                        "maxRetries": self.config.max_model_retries,
                        "delayMs": delay_ms,
                        "failure": failure,
                    },
                    bus_data={"turn": turn, "step": step, "retry": attempt, "delay_ms": delay_ms, "failure": failure},
                )
                if delay_ms > 0:
                    time.sleep(delay_ms / 1000)
                session.append(
                    "llm/retry-started",
                    stage="agent",
                    message=f"model retry {attempt} started",
                    data={"retryId": retry_id, "turn": turn, "step": step, "retry": attempt},
                    bus_data={"turn": turn, "step": step, "retry": attempt},
                )
        session.bus.emit(
            "failure_summary",
            "agent",
            "模型重试耗尽，step 以 error 结束",
            component="model",
            strategy="turn_end_error",
            attempts=total_attempts,
            failure=failure,
        )
        return None, failure

    def _maybe_compact(
        self,
        session: DeepSeekSession,
        messages: list[Any],
        *,
        turn: int,
        step: int,
    ) -> list[Any]:
        before = DeepSeekContextManager.estimate_tokens(messages)
        if before <= self.config.compact_threshold or len(messages) <= 10:
            return messages
        message_events = session.message_events()
        victims = message_events[:-6]
        if not victims:
            return messages
        shadowed_seqs = [event.seq for event in victims]
        start_seq = min(shadowed_seqs)
        end_seq = max(shadowed_seqs)
        compaction_id = uuid.uuid4().hex
        lifecycle = {"compactionId": compaction_id, "turn": turn}
        session.append(
            "compaction/start",
            stage="compaction",
            message=f"compaction started for {len(victims)} events",
            data=lifecycle,
            bus_data={**lifecycle, "step": step, "beforeTokens": before},
        )
        prunable = [event.seq for event in victims if event.type == "tool/result"]
        if prunable:
            session.append(
                "compaction/prune",
                stage="compaction",
                message=f"pruned {len(prunable)} tool results",
                data={
                    "compactionId": compaction_id,
                    "turn": turn,
                    "shadowedSeqs": prunable,
                },
                bus_data={"pruned": len(prunable), "shadowedSeqs": prunable},
            )
        summary = (
            f"[DeepSeek compaction] {len(victims)} 条较早事件已被摘要替换。"
            "继续遵守当前任务、plan、工具结果和 workspace 边界。"
        )
        summary_event = session.append(
            "compaction/summary",
            stage="compaction",
            message=summary,
            data={
                "compactionId": compaction_id,
                "turn": turn,
                "summary": summary,
                "shadowedRange": {"start": start_seq, "end": end_seq},
                "shadowedSeqs": shadowed_seqs,
                "shadowedTokenCount": before,
                "provider": "deepseek",
                "model": self.resolved_model_name,
            },
            bus_data={"shadowed": len(shadowed_seqs), "beforeTokens": before},
            source_event_seqs=shadowed_seqs,
        )
        session.append(
            "user/message",
            stage="compaction",
            message="compaction checkpoint injected",
            data={
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": summary}],
                    "source": {"kind": "compaction", "compactionId": compaction_id},
                }
            },
            bus_data={"summary": summary},
            surface_op={"op": "replace", "start": start_seq, "end": end_seq},
            source_event_seqs=[*shadowed_seqs, summary_event.seq],
        )
        session.append(
            "compaction/end",
            stage="compaction",
            message="compaction completed",
            data=lifecycle,
            bus_data={**lifecycle, "step": step, "afterTokens": before},
        )
        return session.derive_messages()

    def _system_prompt(self, context: DeepSeekContextManager, plan_state: PlanState) -> str:
        from .context import BASE_SYSTEM_PROMPT

        return BASE_SYSTEM_PROMPT + context.system_context(plan_state.to_text())

    def run(self, task: str) -> DeepSeekRunResult:
        started = time.perf_counter()
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        run_dir = (self.config.trace_root or self.config.workspace / ".deepseek" / "runs") / run_id
        bus = EventBus(run_dir, console=self.config.console)
        session = DeepSeekSession(run_dir, bus)
        sandbox = SandboxSimulator("deepseek", mode=sandbox_mode_for_approval(self.config.approval_mode))
        errors: list[str] = []
        plan_state = PlanState()
        changes = ChangeTracker()
        commands: list[CommandRecord] = []
        final_answer = ""
        verification_passed: bool | None = None
        steps = 0
        turn_end_reason: dict[str, Any] = {"kind": "completed"}

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
                    self.resolved_model_name,
                )
                bus.emit(
                    "context_built",
                    "context",
                    "DeepSeek 上下文构建完成",
                    token_budget=self.config.token_budget,
                    context_snapshot=context.snapshot(task),
                )

            profile = sandbox.start(
                bus,
                workspace=self.config.workspace,
                approval_mode=self.config.approval_mode,
            )
            session.append(
                "sandbox/mode",
                stage="bootstrap",
                message=f"sandbox mode: {profile.mode}",
                data={
                    "mode": profile.mode,
                    "backend": profile.backend,
                    "writableRoots": profile.writable_roots,
                    "networkAccess": profile.network_access,
                    "enforcement": profile.enforcement,
                },
                bus_data={
                    "mode": profile.mode,
                    "backend": profile.backend,
                    "writable_roots": profile.writable_roots,
                    "network_access": profile.network_access,
                },
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
                if self.config.fault_mode == "plugin_error":
                    self._announce_fault(bus, "plugins", "已注入插件装载故障，用于观察无插件降级")
                    raise RuntimeError("simulated plugin failure")
                plugin_tools = plugin_registry.load()
            except Exception as exc:
                plugin_tools = []
                errors.append(f"plugins: {exc}")
                bus.emit("error", "bootstrap", f"插件加载失败：{exc}")
                bus.emit(
                    "fallback_applied",
                    "bootstrap",
                    "插件加载失败，继续使用内置工具",
                    component="plugins",
                    strategy="continue_without_plugins",
                    error=str(exc),
                )
            if plugin_tools:
                tools.extend(plugin_tools)
                bus.emit(
                    "plugin_tools_loaded",
                    "bootstrap",
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
                    bus.emit("mcp_tools_loaded", "bootstrap", f"loaded {len(mcp_tools)} MCP tools", tools=[item.name for item in mcp_tools])
                except Exception as exc:
                    errors.append(f"mcp: {exc}")
                    bus.emit("error", "bootstrap", f"MCP 加载失败：{exc}")
                    bus.emit(
                        "fallback_applied",
                        "bootstrap",
                        "MCP 不可用，继续使用内置/插件工具",
                        component="mcp",
                        strategy="continue_without_mcp",
                        error=str(exc),
                    )

            if self.config.enable_multi_agent:
                read_only_tools = [item for item in tools if item.name in READ_ONLY_TOOLS]
                agent_tools = build_codex_agent_tools(self.model, read_only_tools, bus)
                tools.extend(agent_tools)
                bus.emit("multi_agent_tools_loaded", "bootstrap", f"loaded {len(agent_tools)} multi-agent tools", tools=[item.name for item in agent_tools])

            tool_map = {item.name: item for item in tools}
            model = self.model.bind_tools(tools)
            pipeline = DeepSeekToolPipeline(
                session=session,
                tool_map=tool_map,
                approval=ApprovalManager(self.config.approval_mode),
                read_only_names=READ_ONLY_TOOLS,
            )

            turn = 1
            session.append(
                "turn/start",
                stage="agent",
                message=f"turn {turn} started",
                data={"turn": turn},
                bus_data={"turn": turn},
            )
            for step in range(1, self.config.max_steps + 1):
                steps = step
                messages = session.derive_messages()
                messages = self._maybe_compact(session, messages, turn=turn, step=step)
                session.append(
                    "step/start",
                    stage="agent",
                    message=f"step {step} started",
                    data={"turn": turn, "step": step},
                    bus_data={"turn": turn, "step": step},
                )
                if step == 1:
                    session.append(
                        "user/message",
                        stage="agent",
                        message=task,
                        data={
                            "message": {
                                "role": "user",
                                "content": [{"type": "text", "text": task}],
                                "source": {"kind": "user"},
                            }
                        },
                        bus_data={"text": task},
                        surface_op="append",
                    )
                    messages = session.derive_messages()

                session.append(
                    "request/header",
                    stage="agent",
                    message="request header recorded",
                    data={
                        "header": {
                            "provider": "deepseek",
                            "model": self.resolved_model_name,
                            "cwd": str(self.config.workspace),
                            "reasoningEffort": self.config.reasoning_effort,
                        },
                        "reason": "initial" if step == 1 else "series",
                    },
                    bus_data={"provider": "deepseek", "model": self.resolved_model_name, "step": step},
                )
                session.flush(phase="before_request", turn=turn, step=step)
                self.flushes += 1
                bus.emit(
                    "agent/request",
                    "agent",
                    f"turn {turn} step {step} request",
                    turn=turn,
                    step=step,
                    message_count=len(messages),
                    messages=serialize_messages(messages),
                    system_prompt=self._system_prompt(context, plan_state),
                )

                request_messages = [
                    SystemMessage(content=self._system_prompt(context, plan_state)),
                    *messages,
                ]
                response, failure = self._invoke_model(
                    model,
                    request_messages,
                    session=session,
                    turn=turn,
                    step=step,
                )
                if response is None:
                    session.append(
                        "assistant/attempt",
                        stage="agent",
                        message="model attempt failed",
                        data={
                            "turn": turn,
                            "step": step,
                            "stream": [{"type": "error", "text": failure.get("message", "model failed")}],
                        },
                        bus_data={"turn": turn, "step": step, "failure": failure},
                    )
                    session.append("step/end", stage="agent", message=f"step {step} ended", data={"turn": turn, "step": step}, bus_data={"turn": turn, "step": step})
                    turn_end_reason = {"kind": "error", "error": failure}
                    final_answer = f"运行失败：{failure.get('message')}"
                    break

                reasoning = self._reasoning_text(response)
                text = message_text(response)
                tool_calls = list(getattr(response, "tool_calls", None) or [])
                usage = getattr(response, "usage_metadata", None) or {}
                content_blocks: list[dict[str, Any]] = []
                if reasoning:
                    content_blocks.append({"type": "reasoning", "text": reasoning})
                if text:
                    content_blocks.append({"type": "text", "text": text})
                assistant_payload = {
                    "role": "assistant",
                    "content": content_blocks,
                    "tool_calls": tool_calls,
                }
                stream = [
                    {"type": "reasoning", "text": reasoning},
                    {"type": "text", "text": text},
                ] if reasoning else [{"type": "text", "text": text}]
                assistant_data: dict[str, Any] = {
                    "turn": turn,
                    "step": step,
                    "message": assistant_payload,
                    "stream": stream,
                }
                if usage:
                    assistant_data["usage"] = usage
                session.append(
                    "assistant/message",
                    stage="agent",
                    message=text or "(tool calls)",
                    data=assistant_data,
                    bus_data={
                        "turn": turn,
                        "step": step,
                        "text": text,
                        "reasoning": reasoning,
                        "tool_calls": tool_calls,
                        "usage": usage,
                    },
                    surface_op="append",
                )
                session.flush(phase="after_assistant", turn=turn, step=step)
                self.flushes += 1

                for call in tool_calls:
                    name = call.get("name") or "unknown"
                    args = call.get("args") or {}
                    call_id = call.get("id") or f"call-{uuid.uuid4().hex[:8]}"
                    if self.config.fault_mode == "tool_error" and not self._tool_fault_injected:
                        self._tool_fault_injected = True
                        self._announce_fault(bus, "tool", "已注入工具执行故障，用于观察 tool/result 错误回填")
                    pipeline.execute(
                        name=name,
                        args=args,
                        call_id=call_id,
                        turn=turn,
                        step=step,
                    )
                    if name == "update_plan":
                        session.append(
                            "todo/write",
                            stage="tools",
                            message="todo updated",
                            data={
                                "items": [item.model_dump() for item in plan_state.items],
                                "summary": plan_state.summary,
                            },
                            bus_data={"items": [item.model_dump() for item in plan_state.items]},
                        )

                session.flush(phase="step_boundary", turn=turn, step=step)
                self.flushes += 1
                session.append(
                    "step/end",
                    stage="agent",
                    message=f"step {step} ended",
                    data={"turn": turn, "step": step},
                    bus_data={"turn": turn, "step": step},
                )

                if not tool_calls:
                    final_answer = text or "模型没有返回最终文本。"
                    turn_end_reason = {"kind": "completed"}
                    break
            else:
                turn_end_reason = {
                    "kind": "error",
                    "error": {
                        "code": "DSH_MINI_MAX_STEPS",
                        "message": f"reached max_steps={self.config.max_steps}",
                    },
                }
                final_answer = "达到最大步骤数，尚未得到最终回答。"

            session.append(
                "turn/end",
                stage="agent",
                message=f"turn {turn} ended: {turn_end_reason.get('kind')}",
                data={"turn": turn, "reason": turn_end_reason},
                bus_data={"turn": turn, "reason": turn_end_reason},
            )

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
                else:
                    bus.emit("verification_skipped", "verify", "未配置 verify_command")

            with bus.stage("finalize", "保存 session memory、变更、会话日志和摘要"):
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
                    f"- Turns: 1",
                    f"- Steps: {steps}",
                    f"- Session flushes: {self.flushes}",
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
                    session_path=str(session.path),
                    flushes=self.flushes,
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
            sandbox.stop(bus, reason="deepseek_run_finished")
            session.close()
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
            session_path=session.path,
            success=success,
            elapsed_ms=elapsed_ms,
            turns=1,
            steps=steps,
            flushes=self.flushes,
            retries=self.retries,
            errors=errors,
        )
