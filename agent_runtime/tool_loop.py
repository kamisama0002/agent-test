"""LangGraph 版的通用工具循环。

Codex 的真实内层循环是“采样 → tool_calls → 执行 → 回填 → 再采样”。
这个模块把它显式做成 LangGraph：

```text
START → model --tool_calls--> tools --未结束--> model
             └─ no calls ────────────────────→ END
```

外层 Harness 仍可以保留自己的 bootstrap/verify/finalize 阶段。这样既有
LangGraph 的状态图、条件边和 checkpoint 接口，又不会把文件/命令执行、
流式事件和取消逻辑硬塞进图里。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, TypedDict

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from langchain_cases.common import message_text


class ToolLoopState(TypedDict, total=False):
    messages: list[Any]
    step: int
    final_answer: str
    done: bool
    errors: list[str]


@dataclass
class ToolLoopResult:
    messages: list[Any]
    final_answer: str
    steps: int
    errors: list[str] = field(default_factory=list)


class LangGraphToolLoop:
    def __init__(
        self,
        model: Any,
        tool_map: dict[str, Any],
        event_bus: Any,
        *,
        max_steps: int = 10,
        compact: Callable[[list[Any]], tuple[list[Any], int]] | None = None,
        estimate_tokens: Callable[[list[Any]], int] | None = None,
        stage: str = "agent",
        max_repeated_calls: int = 2,
    ) -> None:
        self.model = model
        self.tool_map = tool_map
        self.event_bus = event_bus
        self.max_steps = max_steps
        self.compact = compact
        self.estimate_tokens = estimate_tokens
        self.stage = stage
        self.max_repeated_calls = max_repeated_calls
        self._seen_calls: dict[str, int] = {}

    def _emit(self, event: str, message: str = "", **data: Any) -> None:
        if self.event_bus is not None:
            self.event_bus.emit(event, self.stage, message, **data)

    def _model_node(self, state: ToolLoopState) -> dict[str, Any]:
        messages = list(state.get("messages", []))
        errors = list(state.get("errors", []))
        if state.get("done"):
            return {"messages": messages, "errors": errors, "done": True}

        if self.compact is not None:
            messages, removed = self.compact(messages)
            if removed:
                extra = {"removed": removed}
                if self.estimate_tokens is not None:
                    extra["estimated_tokens"] = self.estimate_tokens(messages)
                self._emit("context_compacted", f"上下文压缩：省略 {removed} 条旧消息", **extra)

        step = int(state.get("step", 0)) + 1
        self._emit("model_request", f"第 {step} 次模型采样", step=step)
        try:
            response: AIMessage = self.model.invoke(messages)
        except Exception as exc:
            errors.append(f"model: {exc}")
            self._emit("error", f"模型调用失败：{exc}")
            self._emit(
                "failure_summary",
                "模型调用失败，当前循环安全终止",
                component="model",
                strategy="return_failure_answer",
                error=str(exc),
            )
            return {
                "messages": messages,
                "step": step,
                "errors": errors,
                "final_answer": f"运行失败：{exc}",
                "done": True,
            }

        messages.append(response)
        text = message_text(response)
        if text:
            self._emit("agent_message", text)
        usage = getattr(response, "usage_metadata", None) or {}
        if usage:
            self._emit("token_usage", "token usage", **usage)
        calls = list(getattr(response, "tool_calls", None) or [])
        if not calls:
            final = text or "模型没有返回最终文本。"
            self._emit("turn_completed", "模型完成本轮，无更多工具调用", step=step)
            return {"messages": messages, "step": step, "errors": errors, "final_answer": final, "done": True}
        return {"messages": messages, "step": step, "errors": errors, "done": False}

    def _tools_node(self, state: ToolLoopState) -> dict[str, Any]:
        messages = list(state.get("messages", []))
        errors = list(state.get("errors", []))
        last = messages[-1] if messages else None
        calls = list(getattr(last, "tool_calls", None) or [])
        final = ""
        stopped = False
        for call in calls:
            name = call.get("name") or "unknown"
            args = call.get("args") or {}
            call_id = call.get("id") or f"call-{uuid.uuid4().hex[:8]}"
            signature = name + ":" + json.dumps(args, ensure_ascii=False, sort_keys=True)
            self._seen_calls[signature] = self._seen_calls.get(signature, 0) + 1
            if self._seen_calls[signature] > self.max_repeated_calls:
                errors.append(f"repeated_tool_call:{name}")
                self._emit("error", f"检测到重复工具调用：{name}")
                self._emit(
                    "failure_summary",
                    "检测到重复工具调用，停止循环",
                    component="model",
                    strategy="stop_on_repeated_tool_call",
                    tool=name,
                )
                final = "停止：模型重复调用同一个工具，需要人工调整提示词或工具结果。"
                stopped = True
                break

            self._emit("tool_started", "", tool=name, args=args, call_id=call_id)
            started = time.perf_counter()
            try:
                target = self.tool_map.get(name)
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
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            messages.append(
                ToolMessage(
                    content=str(output),
                    tool_call_id=call_id,
                    name=name,
                    status="success" if status == "ok" else "error",
                )
            )
            self._emit(
                "tool_finished",
                str(output),
                tool=name,
                status=status,
                elapsed_ms=elapsed_ms,
                call_id=call_id,
            )
            if status == "error":
                self._emit(
                    "fallback_applied",
                    "工具错误已转成 ToolMessage，交回模型决定下一步",
                    component="tool",
                    strategy="return_tool_error_to_model",
                    tool=name,
                    call_id=call_id,
                )
        return {"messages": messages, "errors": errors, "final_answer": final, "done": stopped}

    @staticmethod
    def _route_after_model(state: ToolLoopState) -> Literal["tools", "end"]:
        return "end" if state.get("done") else "tools"

    def _route_after_tools(self, state: ToolLoopState) -> Literal["model", "end"]:
        if state.get("done"):
            return "end"
        if int(state.get("step", 0)) >= self.max_steps:
            return "end"
        return "model"

    def run(self, messages: list[Any]) -> ToolLoopResult:
        builder = StateGraph(ToolLoopState)
        builder.add_node("model", self._model_node)
        builder.add_node("tools", self._tools_node)
        builder.add_edge(START, "model")
        builder.add_conditional_edges("model", self._route_after_model, {"tools": "tools", "end": END})
        builder.add_conditional_edges("tools", self._route_after_tools, {"model": "model", "end": END})
        graph = builder.compile()
        state: ToolLoopState = {"messages": list(messages), "step": 0, "errors": [], "done": False}
        result = graph.invoke(state)
        final = str(result.get("final_answer", ""))
        if not final:
            self._emit(
                "limit_reached",
                "达到最大模型步数，返回部分结果",
                component="loop",
                strategy="stop_at_max_steps",
                max_steps=self.max_steps,
            )
            final = "达到最大步骤数，尚未得到最终回答。"
        return ToolLoopResult(
            messages=list(result.get("messages", [])),
            final_answer=final,
            steps=int(result.get("step", 0)),
            errors=list(result.get("errors", [])),
        )
