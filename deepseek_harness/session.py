"""DeepSeek Harness 的 append-only 会话日志（mini 版）。

源码映射：
- packages/core/session/src/types.ts::SessionEventMap
- packages/core/session/src/index.ts::Session.append / deriveMessages
- docs/subsystems/session.zh.md

核心原则与上游一致：会话事件是唯一真源，模型消息从事件日志派生，
而不是额外维护一份聊天列表。教学版只保留文本/工具/压缩所需的最小
surface 事件，省略 Cordis 的完整 projection 与 persistence 插件体系。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from mini_codex.events import EventBus


@dataclass(frozen=True)
class SessionEvent:
    seq: int
    time: int
    type: str
    data: dict[str, Any]
    surfaceOp: dict[str, Any] | None = None
    sourceEventSeqs: list[int] | None = None

    def as_json(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "seq": self.seq,
            "time": self.time,
            "type": self.type,
            "data": self.data,
        }
        if self.surfaceOp is not None:
            row["surfaceOp"] = self.surfaceOp
        if self.sourceEventSeqs:
            row["sourceEventSeqs"] = self.sourceEventSeqs
        return row


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content or "")


def _content_blocks_text(content: Any) -> str:
    return _text_from_content(content)


def _shadowed_sequences(events: Iterable[SessionEvent]) -> set[int]:
    shadowed: set[int] = set()
    for event in events:
        op = event.surfaceOp
        if not isinstance(op, dict) or op.get("op") != "replace":
            continue
        start = op.get("start")
        end = op.get("end")
        if isinstance(start, int) and isinstance(end, int):
            shadowed.update(range(start, end + 1))
    return shadowed


class DeepSeekSession:
    """由 SessionEvent 驱动的会话日志。

    events.jsonl 是给 Mini Harness Studio 的可视化镜像；session.v1.jsonl
    才是模型历史派生的权威日志。两者使用同一组上游事件名，便于对照源码。
    """

    def __init__(self, run_dir: Path, bus: EventBus) -> None:
        self.run_dir = run_dir
        self.bus = bus
        self.path = run_dir / "session.v1.jsonl"
        self._fh = self.path.open("w", encoding="utf-8")
        self.events: list[SessionEvent] = []

    def append(
        self,
        event_type: str,
        *,
        stage: str,
        message: str,
        data: dict[str, Any] | None = None,
        bus_data: dict[str, Any] | None = None,
        surface_op: dict[str, Any] | None = None,
        source_event_seqs: list[int] | None = None,
        emit: bool = True,
    ) -> SessionEvent:
        event = SessionEvent(
            seq=len(self.events),
            time=int(time.time() * 1000),
            type=event_type,
            data=data or {},
            surfaceOp=surface_op,
            sourceEventSeqs=source_event_seqs,
        )
        self.events.append(event)
        self._fh.write(json.dumps(event.as_json(), ensure_ascii=False, default=str) + "\n")
        self._fh.flush()
        if emit:
            payload: dict[str, Any] = {
                "session_seq": event.seq,
                "session_event": event_type,
                "session_data": event.data,
            }
            if bus_data:
                payload.update(bus_data)
            self.bus.emit(event_type, stage, message, **payload)
        return event

    def flush(self, *, phase: str, turn: int, step: int) -> None:
        """对应 session-checkpoint-policy 的 durability checkpoint。

        上游会在模型请求前、工具正文前和 step 边界调用 session/flush。
        这里真正 flush 文件，并在 events.jsonl 留下可观察镜像。
        """

        self._fh.flush()
        self.bus.emit(
            "session/flush",
            "session",
            f"session checkpoint: {phase}",
            phase=phase,
            turn=turn,
            step=step,
            session_file=str(self.path),
        )

    def visible_events(self) -> list[SessionEvent]:
        shadowed = _shadowed_sequences(self.events)
        return [event for event in self.events if event.seq not in shadowed]

    def derive_messages(self) -> list[BaseMessage]:
        messages: list[BaseMessage] = []
        for event in self.visible_events():
            if event.type == "user/message":
                payload = event.data.get("message") or {}
                content = _content_blocks_text(payload.get("content", ""))
                messages.append(HumanMessage(content=content))
            elif event.type == "assistant/message":
                payload = event.data.get("message") or {}
                text = _content_blocks_text(payload.get("content", ""))
                reasoning = ""
                for block in payload.get("content", []) if isinstance(payload.get("content"), list) else []:
                    if isinstance(block, dict) and block.get("type") in {"reasoning", "thinking"}:
                        reasoning += str(block.get("text") or block.get("reasoning") or "")
                tool_calls = payload.get("tool_calls") or []
                messages.append(
                    AIMessage(
                        content=text,
                        tool_calls=tool_calls,
                        additional_kwargs={"reasoning_content": reasoning} if reasoning else {},
                    )
                )
            elif event.type == "tool/result":
                payload = event.data.get("message") or {}
                content = _content_blocks_text(payload.get("content", ""))
                messages.append(
                    ToolMessage(
                        content=content,
                        tool_call_id=str(payload.get("tool_call_id") or event.data.get("callId") or ""),
                        name=str(payload.get("name") or event.data.get("name") or ""),
                        status="error" if event.data.get("isError") else "success",
                    )
                )
        return messages

    def message_events(self) -> list[SessionEvent]:
        return [
            event for event in self.visible_events()
            if event.type in {"user/message", "assistant/message", "tool/result"}
        ]

    def close(self) -> None:
        self._fh.close()
