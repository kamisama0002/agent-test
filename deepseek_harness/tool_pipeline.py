"""DeepSeek Harness 的工具执行流水线（mini 版）。

源码映射：
- packages/core/agent-loop/src/tool-calls.ts::executeToolCalls
- packages/core/agent-loop/src/tool-calls.ts::appendToolCall / appendToolResult
- docs/subsystems/tools.zh.md
- docs/tool-execution-pipeline.zh.md

上游顺序：工具调用先被记录，随后进入 pre-execute/approval/guards，
再执行工具正文，最后把权威结果记录为 tool/result。教学版保留
"先记录调用、再审批、再执行、失败也形成结果" 的顺序，省略 Cordis
waterfall、并行调度、abort signal 和完整 guard 注册表。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import ToolMessage

from agent_runtime.approval import ApprovalManager
from .session import DeepSeekSession


def _result_content(text: str) -> list[dict[str, str]]:
    return [{"type": "text", "text": text}]


class DeepSeekToolPipeline:
    def __init__(
        self,
        *,
        session: DeepSeekSession,
        tool_map: dict[str, Any],
        approval: ApprovalManager,
        read_only_names: set[str],
    ) -> None:
        self.session = session
        self.tool_map = tool_map
        self.approval = approval
        self.read_only_names = set(read_only_names)

    def execute(
        self,
        *,
        name: str,
        args: dict[str, Any],
        call_id: str,
        turn: int,
        step: int,
    ) -> ToolMessage:
        raw_arguments = json.dumps(args, ensure_ascii=False, sort_keys=True)
        call_event = self.session.append(
            "tool/call",
            stage="tools",
            message=f"{name} {raw_arguments}",
            data={
                "turn": turn,
                "step": step,
                "callId": call_id,
                "name": name,
                "arguments": raw_arguments,
            },
            bus_data={"tool": name, "args": args, "call_id": call_id},
        )

        read_only = name in self.read_only_names
        decision = self.approval.decide(name, args, read_only=read_only)
        self.session.append(
            "approval/policy",
            stage="tools",
            message=f"{name}: {decision.behavior}",
            data={
                "callId": call_id,
                "tool": name,
                "mode": self.approval.mode,
                "readOnly": read_only,
                "behavior": decision.behavior,
                "reason": decision.reason,
            },
            bus_data={"tool": name, "call_id": call_id, "behavior": decision.behavior, "reason": decision.reason},
        )
        if not read_only:
            self.session.append(
                "approval/asked",
                stage="tools",
                message=f"ask approval for {name}",
                data={"callId": call_id, "tool": name, "arguments": raw_arguments},
                bus_data={"tool": name, "call_id": call_id, "args": args},
            )
            self.session.append(
                "approval/decided",
                stage="tools",
                message=f"{name}: {decision.behavior}",
                data={
                    "callId": call_id,
                    "tool": name,
                    "behavior": decision.behavior,
                    "reason": decision.reason,
                },
                bus_data={"tool": name, "call_id": call_id, "behavior": decision.behavior, "reason": decision.reason},
            )

        # session-checkpoint-policy 在顶层工具正文运行前刷新持久日志。
        self.session.flush(phase="before_tool", turn=turn, step=step)

        is_error = False
        error_info: dict[str, Any] | None = None
        if not decision.allowed:
            output = f"Error: permission denied — {decision.reason}"
            is_error = True
            error_info = {"code": "APPROVAL_DENIED", "message": decision.reason}
        else:
            target = self.tool_map.get(name)
            if target is None:
                output = f"Error: unknown tool: {name}"
                is_error = True
                error_info = {"code": "UNKNOWN_TOOL", "message": f"unknown tool: {name}"}
            else:
                try:
                    output = str(target.invoke(args))
                except Exception as exc:
                    output = f"Error: {type(exc).__name__}: {exc}"
                    is_error = True
                    error_info = {"code": "TOOL_EXCEPTION", "message": str(exc)}

        result_data: dict[str, Any] = {
            "turn": turn,
            "step": step,
            "callId": call_id,
            "name": name,
            "message": {
                "role": "tool",
                "content": _result_content(output),
                "tool_call_id": call_id,
                "name": name,
            },
            "isError": is_error,
            "status": "error" if is_error else "success",
        }
        if error_info:
            result_data["error"] = error_info
        self.session.append(
            "tool/result",
            stage="tools",
            message=output,
            data=result_data,
            bus_data={
                "tool": name,
                "call_id": call_id,
                "status": "error" if is_error else "success",
                "output": output,
                "isError": is_error,
            },
            surface_op="append",
            source_event_seqs=[call_event.seq],
        )
        return ToolMessage(
            content=output,
            tool_call_id=call_id,
            name=name,
            status="error" if is_error else "success",
        )
