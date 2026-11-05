"""Hermes mini 的核心 Harness。

主流程（与 Hermes 的通用 agent turn 对齐）：

    prepare（SOUL/MEMORY/USER/Skills/环境）
      → model（模型决定下一步）
      → tools（执行文件、命令、记忆、技能、历史检索）
      → model ... 直到模型不再调用工具
      → finalize（保存 session / summary / timeline）
      → background_review（独立模型复盘并更新长期记忆/技能）

关键点：主对话和后台上下文隔离；后台复盘不会改变本轮答案。
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from langchain_cases.common import build_chat_model, message_text
from mini_codex.events import EventBus
from .config import HermesHarnessConfig
from .context import HermesContextManager
from .memory import MemoryStore
from .review import BackgroundReview, ReviewResult
from .sessions import SessionStore
from .skills import SkillStore
from .tools import ToolContext, build_tools
from .toolsets import describe_toolsets, resolve_toolsets


class HermesState(TypedDict):
    task: str
    messages: list[Any]
    turn: int
    final: str
    done: bool


@dataclass
class HermesRunResult:
    task: str
    final_answer: str
    session_id: str
    run_dir: Path
    timeline_path: Path
    success: bool
    elapsed_ms: float
    turns: int
    memory_stats: dict[str, dict[str, int]]
    skills_used: list[str]
    review: ReviewResult | None = None
    errors: list[str] = field(default_factory=list)


class HermesHarness:
    """一个带长期记忆、技能和后台复盘的通用 Agent。"""

    def __init__(
        self,
        config: HermesHarnessConfig,
        *,
        model: Any | None = None,
        review_model: Any | None = None,
    ) -> None:
        self.config = config
        self.memory = MemoryStore(config.hermes_home)  # type: ignore[arg-type]
        self.skills = SkillStore(config.hermes_home)  # type: ignore[arg-type]
        self.sessions = SessionStore(config.hermes_home)  # type: ignore[arg-type]
        self.context = HermesContextManager(
            config.workspace,
            config.hermes_home,  # type: ignore[arg-type]
            self.memory,
            self.skills,
            token_budget=config.token_budget,
            compact_threshold=config.compact_threshold,
            toolsets=config.toolsets,
        )
        self.tool_ctx = ToolContext(
            workspace=config.workspace,
            home=config.hermes_home,  # type: ignore[arg-type]
            memory=self.memory,
            skills=self.skills,
            sessions=self.sessions,
            command_timeout=config.command_timeout,
        )
        self.tool_names = resolve_toolsets(config.toolsets)
        self.tools = build_tools(self.tool_ctx, self.tool_names)
        self.tool_map = {tool.name: tool for tool in self.tools}
        self.model = model or build_chat_model()
        self.review_model = review_model
        self.bound_model = self.model.bind_tools(self.tools) if self.tools else self.model
        self._review_threads: list[threading.Thread] = []

    def _append_session_message(self, session_id: str, message: Any) -> None:
        role = getattr(message, "type", message.__class__.__name__)
        content = message_text(message)
        metadata: dict[str, Any] = {}
        calls = getattr(message, "tool_calls", None) or []
        if calls:
            metadata["tool_calls"] = calls
        if role == "tool":
            metadata["tool_call_id"] = getattr(message, "tool_call_id", None)
            metadata["name"] = getattr(message, "name", None)
        self.sessions.append_message(session_id, role, content or json.dumps(metadata, ensure_ascii=False), metadata)

    def _save_transcript(self, session_id: str, messages: list[Any]) -> None:
        for message in messages:
            # prepare 阶段写入的 task 是 HumanMessage；工具消息和 assistant 都要留档。
            self._append_session_message(session_id, message)

    def _verify(self, bus: EventBus, errors: list[str]) -> bool | None:
        command = self.config.verify_command
        if not command:
            return None
        with bus.stage("verify", "执行最终验证命令"):
            try:
                argv = shlex.split(command, posix=True)
                if argv and Path(argv[0]).name.lower() in {"python", "python3"}:
                    argv[0] = sys.executable
                result = subprocess.run(
                    argv,
                    cwd=self.config.workspace,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.config.command_timeout,
                )
                passed = result.returncode == 0
                message = (result.stdout or "") + (result.stderr or "")
                bus.emit(
                    "verification_completed",
                    "verify",
                    f"{command} → exit {result.returncode}",
                    returncode=result.returncode,
                    output=message[-1200:],
                )
                return passed
            except Exception as exc:
                errors.append(f"verify: {exc}")
                bus.emit("error", "verify", f"验证失败：{exc}")
                return False

    def run(self, task: str) -> HermesRunResult:
        started = time.perf_counter()
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        run_dir = (self.config.trace_root or self.config.hermes_home / "runs") / run_id  # type: ignore[union-attr]
        bus = EventBus(run_dir, console=self.config.console)
        errors: list[str] = []
        session_id = self.sessions.create_session(
            title=task[:100],
            metadata={"toolsets": list(self.config.toolsets), "run_id": run_id},
        )
        self.tool_ctx.event_bus = bus
        final = ""
        turns = 0
        review_result: ReviewResult | None = None
        verification_passed: bool | None = None

        bus.emit(
            "run_started",
            "bootstrap",
            f"task={task}",
            session_id=session_id,
            workspace=str(self.config.workspace),
            hermes_home=str(self.config.hermes_home),
        )
        bus.emit(
            "toolsets_resolved",
            "bootstrap",
            f"{len(self.tools)} tools",
            toolsets=list(self.config.toolsets),
            tools=[tool.name for tool in self.tools],
        )

        def prepare_node(state: HermesState) -> dict[str, Any]:
            with bus.stage("prepare", "加载 SOUL/MEMORY/USER/Skills/环境"):
                messages = self.context.initial_messages(state["task"])
                bus.emit(
                    "context_prepared",
                    "prepare",
                    "长期上下文已注入",
                    memory_stats=self.memory.stats(),
                    skills=len(self.skills.index()),
                    toolsets=describe_toolsets(self.config.toolsets),
                )
                return {"messages": messages, "turn": 0, "done": False}

        def model_node(state: HermesState) -> dict[str, Any]:
            messages, removed = self.context.compact(state["messages"])
            if removed:
                bus.emit(
                    "context_compacted",
                    "model",
                    f"省略 {removed} 条旧消息",
                    removed=removed,
                    estimated_tokens=HermesContextManager.estimate_tokens(messages),
                )
            step = int(state["turn"]) + 1
            bus.emit("model_request", "model", f"第 {step} 次采样", step=step)
            try:
                response: AIMessage = self.bound_model.invoke(messages)
            except Exception as exc:
                errors.append(f"model: {exc}")
                bus.emit("error", "model", f"模型调用失败：{exc}")
                return {"messages": messages, "final": f"运行失败：{exc}", "turn": step, "done": True}
            messages.append(response)
            text = message_text(response)
            if text:
                bus.emit("agent_message", "model", text)
            usage = getattr(response, "usage_metadata", None) or {}
            if usage:
                bus.emit("token_usage", "model", "token usage", **usage)
            return {"messages": messages, "turn": step, "done": False}

        def route_after_model(state: HermesState) -> Literal["tools", "finalize"]:
            if state.get("done"):
                return "finalize"
            last = state["messages"][-1] if state["messages"] else None
            return "tools" if getattr(last, "tool_calls", None) else "finalize"

        def tools_node(state: HermesState) -> dict[str, Any]:
            with bus.stage("tools", "执行工具并把观察写回主对话"):
                last = state["messages"][-1]
                tool_messages: list[ToolMessage] = []
                for call in getattr(last, "tool_calls", None) or []:
                    name = call.get("name") or "unknown"
                    args = call.get("args") or {}
                    call_id = call.get("id") or f"call-{uuid.uuid4().hex[:8]}"
                    bus.emit("tool_started", "tools", "", tool=name, args=args, call_id=call_id)
                    tool_started = time.perf_counter()
                    try:
                        target = self.tool_map.get(name)
                        output = str(target.invoke(args)) if target is not None else f"ERROR: unknown tool {name}"
                        status = "error" if output.startswith("ERROR:") else "success"
                    except Exception as exc:
                        output = f"ERROR: {type(exc).__name__}: {exc}"
                        status = "error"
                        errors.append(f"{name}: {exc}")
                    bus.emit(
                        "tool_finished",
                        "tools",
                        output[:1000],
                        tool=name,
                        status=status,
                        elapsed_ms=round((time.perf_counter() - tool_started) * 1000, 2),
                        call_id=call_id,
                    )
                    tool_messages.append(ToolMessage(content=output, tool_call_id=call_id, name=name))
                return {"messages": [*state["messages"], *tool_messages]}

        def route_after_tools(state: HermesState) -> Literal["model", "finalize"]:
            return "model" if int(state["turn"]) < self.config.max_turns else "finalize"

        def finalize_node(state: HermesState) -> dict[str, Any]:
            with bus.stage("finalize", "保存会话、记忆快照和运行摘要"):
                last = state["messages"][-1] if state["messages"] else None
                value = state.get("final") or (message_text(last) if last is not None else "")
                if not value:
                    value = "达到最大轮数，尚未得到最终 assistant message。"
                bus.emit("turn_completed", "finalize", value, turns=state.get("turn", 0))
                return {"final": value, "done": True}

        builder = StateGraph(HermesState)
        builder.add_node("prepare", prepare_node)
        builder.add_node("model", model_node)
        builder.add_node("tools", tools_node)
        builder.add_node("finalize", finalize_node)
        builder.add_edge(START, "prepare")
        builder.add_edge("prepare", "model")
        builder.add_conditional_edges("model", route_after_model, {"tools": "tools", "finalize": "finalize"})
        builder.add_conditional_edges("tools", route_after_tools, {"model": "model", "finalize": "finalize"})
        builder.add_edge("finalize", END)
        graph = builder.compile()

        initial_state: HermesState = {"task": task, "messages": [], "turn": 0, "final": "", "done": False}
        review_thread: threading.Thread | None = None
        try:
            result = graph.invoke(initial_state)
            final = str(result.get("final", ""))
            turns = int(result.get("turn", 0))
            messages = list(result.get("messages", []))
            self._save_transcript(session_id, messages)
            verification_passed = self._verify(bus, errors)
            if self.config.enable_background_review:
                review_model = self.review_model or build_chat_model()
                reviewer = BackgroundReview(review_model, self.tool_ctx, max_turns=self.config.review_max_turns)

                def run_review_job() -> None:
                    nonlocal review_result
                    try:
                        with bus.stage("review", "后台复盘：只允许写 memory/skills"):
                            local_result = reviewer.run(task, messages, final)
                            review_result = local_result
                            bus.emit("review_completed", "review", "后台复盘完成", review=local_result.as_dict())
                            if local_result.error:
                                errors.append(f"review: {local_result.error}")
                            (run_dir / "review.json").write_text(
                                json.dumps(local_result.as_dict(), ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8",
                            )
                    except Exception as exc:
                        errors.append(f"review: {exc}")
                        review_result = ReviewResult(attempted=True, error=f"{type(exc).__name__}: {exc}")
                        bus.emit("error", "review", f"后台复盘失败：{exc}")
                    finally:
                        if self.config.background_review_async:
                            bus.close()

                if self.config.background_review_async:
                    review_result = ReviewResult(attempted=True, final="scheduled in background")
                    review_thread = threading.Thread(target=run_review_job, daemon=True, name="hermes-review")
                    self._review_threads.append(review_thread)
                    review_thread.start()
                else:
                    run_review_job()
        except Exception as exc:
            errors.append(f"harness: {exc}")
            bus.emit("error", "harness", f"运行失败：{exc}")
            final = final or f"运行失败：{exc}"
        finally:
            try:
                self.sessions.end_session(
                    session_id,
                    metadata={
                        "success": bool(final) and verification_passed is not False,
                        "review": review_result.as_dict() if review_result else None,
                    },
                )
            except Exception:
                pass
            if review_thread is None:
                bus.close()

        success = bool(final) and verification_passed is not False
        (run_dir / "summary.md").write_text(
            "\n".join(
                [
                    "# Hermes Mini Run Summary",
                    "",
                    f"- Task: {task}",
                    f"- Session: {session_id}",
                    f"- Turns: {turns}",
                    f"- Toolsets: {', '.join(self.config.toolsets)}",
                    f"- Memory: {json.dumps(self.memory.stats(), ensure_ascii=False)}",
                    f"- Skills used: {', '.join(sorted(self.tool_ctx.viewed_skills)) or '(none)'}",
                    f"- Review: {review_result.final if review_result else 'disabled'}",
                    f"- Verification: {verification_passed if verification_passed is not None else 'not configured'}",
                    "",
                    "## Final Answer",
                    final,
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return HermesRunResult(
            task=task,
            final_answer=final,
            session_id=session_id,
            run_dir=run_dir,
            timeline_path=run_dir / "timeline.md",
            success=success,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            turns=turns,
            memory_stats=self.memory.stats(),
            skills_used=sorted(self.tool_ctx.viewed_skills),
            review=review_result,
            errors=errors,
        )

    def close(self) -> None:
        for thread in self._review_threads:
            thread.join(timeout=120)
        self.sessions.close()
