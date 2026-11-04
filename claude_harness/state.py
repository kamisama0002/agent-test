"""计划、Todo、文件变更和命令记录。"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field


class TodoItem(BaseModel):
    content: str = Field(description="任务步骤")
    status: Literal["pending", "in_progress", "completed"] = "pending"


class TodoPlan(BaseModel):
    summary: str = Field(default="")
    items: list[TodoItem] = Field(default_factory=list)


class TodoState:
    def __init__(self) -> None:
        self.summary = ""
        self.items: list[TodoItem] = []

    def set(self, plan: TodoPlan) -> None:
        self.summary = plan.summary
        self.items = list(plan.items)

    def update(self, summary: str, items: list[TodoItem]) -> None:
        if summary:
            self.summary = summary
        self.items = items

    def to_text(self) -> str:
        icon = {"pending": "○", "in_progress": "◐", "completed": "●"}
        lines = [self.summary or "开发任务计划"]
        lines += [f"{icon.get(item.status, '○')} [{item.status}] {item.content}" for item in self.items]
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
        self.records.append(FileChange(path, operation, before, after))

    def changed_files(self) -> list[str]:
        return list(dict.fromkeys(item.path for item in self.records))

    def diff_text(self) -> str:
        return "\n".join(item.diff() for item in self.records)


@dataclass
class CommandRecord:
    command: str
    returncode: int
    output: str


@dataclass
class HookRecord:
    event: str
    tool: str
    detail: str = ""
    extra: dict = field(default_factory=dict)
