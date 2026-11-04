"""计划、文件变更和命令记录。"""

# Codex refs: core/src/tools/handlers/plan.rs; protocol/src/plan_tool.rs
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field


class PlanItem(BaseModel):
    title: str = Field(description="一个可执行的开发步骤")
    status: Literal["pending", "in_progress", "completed"] = "pending"


class Plan(BaseModel):
    summary: str = Field(default="", description="对任务的整体计划摘要")
    items: list[PlanItem] = Field(default_factory=list, description="按顺序排列的步骤")


class PlanState:
    def __init__(self) -> None:
        self.summary = ""
        self.items: list[PlanItem] = []

    def set(self, plan: Plan) -> None:
        self.summary = plan.summary
        self.items = list(plan.items)

    def update(self, summary: str, items: list[PlanItem]) -> None:
        if summary:
            self.summary = summary
        self.items = items

    def to_text(self) -> str:
        status_icon = {"pending": "○", "in_progress": "◐", "completed": "●"}
        lines = [self.summary or "开发任务计划"]
        for item in self.items:
            lines.append(f"{status_icon.get(item.status, '○')} [{item.status}] {item.title}")
        return "\n".join(lines)


@dataclass
class FileChange:
    path: str
    operation: str
    before: str
    after: str

    def diff(self) -> str:
        return "".join(
            difflib.unified_diff(
                self.before.splitlines(keepends=True),
                self.after.splitlines(keepends=True),
                fromfile=f"a/{self.path}",
                tofile=f"b/{self.path}",
            )
        )


class ChangeTracker:
    def __init__(self) -> None:
        self.records: list[FileChange] = []

    def record(self, path: str, operation: str, before: str, after: str) -> None:
        self.records.append(FileChange(path=path, operation=operation, before=before, after=after))

    def changed_files(self) -> list[str]:
        # 同一个文件多次修改时只展示一次。
        return list(dict.fromkeys(record.path for record in self.records))

    def diff_text(self) -> str:
        return "\n".join(record.diff() for record in self.records)


@dataclass
class CommandRecord:
    command: str
    returncode: int
    output: str
