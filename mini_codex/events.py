"""Harness 事件流与可视化。

Codex 的 app-server 会把 turn/tool/patch/token/compaction 等事件流给 UI。
Mini Codex 用同样思路：
- 控制台实时打印阶段和工具调用；
- 同时写 events.jsonl，便于机器回放；
- 运行结束生成 timeline.md，便于人看每个阶段做了什么。
"""

# Codex refs: protocol/src/protocol.rs::EventMsg; TurnStarted/AgentMessage/ExecCommand*/PatchApply*/PlanUpdate/TokenCount/ContextCompacted
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from rich.console import Console


@dataclass
class StageRecord:
    name: str
    summary: str
    started_at: float
    elapsed_ms: float = 0.0
    status: str = "ok"


@dataclass
class EventRecord:
    type: str
    stage: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class EventBus:
    """同时面向终端和文件的轻量事件总线。"""

    def __init__(self, run_dir: Path, *, console: bool = True) -> None:
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = run_dir / "events.jsonl"
        self._fh = self.events_path.open("a", encoding="utf-8")
        self.console = Console() if console else None
        self.stages: list[StageRecord] = []
        self._stage_started: dict[str, float] = {}

    def emit(self, event_type: str, stage: str, message: str = "", **data: Any) -> None:
        event = EventRecord(type=event_type, stage=stage, message=message, data=data)
        self._fh.write(json.dumps(event.__dict__, ensure_ascii=False) + "\n")
        self._fh.flush()

        if self.console is None:
            return
        if event_type == "stage_started":
            self.console.rule(f"[bold cyan]{stage}[/bold cyan] {message}")
        elif event_type == "tool_started":
            name = data.get("tool", "tool")
            args = data.get("args", {})
            self.console.print(f"  [yellow]→ {name}[/yellow] {json.dumps(args, ensure_ascii=False)[:220]}")
        elif event_type == "tool_finished":
            name = data.get("tool", "tool")
            status = data.get("status", "ok")
            color = "green" if status == "ok" else "red"
            self.console.print(f"  [{color}]✓ {name}[/{color}] {message[:180]}")
        elif event_type == "agent_message":
            if message.strip():
                self.console.print(f"[bold]agent[/bold] {message[:500]}")
        elif event_type in {"error", "verification_completed"}:
            color = "red" if event_type == "error" or data.get("returncode") not in (0, None) else "green"
            self.console.print(f"[{color}]{message}[/{color}]")

    @contextmanager
    def stage(self, name: str, summary: str = "") -> Iterator[None]:
        """记录一个阶段的开始/结束与耗时。"""

        started = time.perf_counter()
        self._stage_started[name] = started
        self.emit("stage_started", name, summary)
        status = "ok"
        try:
            yield
        except Exception:
            status = "error"
            raise
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            self.stages.append(StageRecord(name=name, summary=summary, started_at=started, elapsed_ms=elapsed, status=status))
            self.emit("stage_completed", name, f"{name} completed", elapsed_ms=round(elapsed, 2), status=status)

    def close(self) -> None:
        self._fh.close()
        self.write_timeline()

    def write_timeline(self) -> Path:
        """生成人可读的阶段时间线。"""

        lines = ["# Mini Codex Run Timeline", ""]
        lines.append("| 阶段 | 耗时 | 状态 | 说明 |")
        lines.append("|---|---:|---|---|")
        for stage in self.stages:
            lines.append(
                f"| {stage.name} | {stage.elapsed_ms / 1000:.2f}s | {stage.status} | {stage.summary} |"
            )
        path = self.run_dir / "timeline.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
