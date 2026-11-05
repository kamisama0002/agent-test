"""有界、文件化的声明性记忆。

对应 Hermes 的 tools/memory_tool_store.py：

- MEMORY.md 保存 Agent 对环境的长期事实；
- USER.md 保存用户画像与稳定偏好；
- 每个条目用 ``\n§\n`` 分隔；
- 默认字符预算与 Hermes 一致：memory=2200，user=1375；
- 只允许 add/patch/remove，不允许模型直接整文件覆盖。

这里不追求 Hermes 的跨进程锁和恶意内容扫描，但保留“预算、去重、
唯一匹配、原子写、memory fence”这些决定行为的关键约束。
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

MemoryTarget = Literal["memory", "user"]
ENTRY_DELIMITER = "\n§\n"

_STORE_FILES: dict[MemoryTarget, str] = {
    "memory": "MEMORY.md",
    "user": "USER.md",
}
_DEFAULT_LIMITS: dict[MemoryTarget, int] = {
    "memory": 2200,
    "user": 1375,
}


class MemoryStore:
    """管理 MEMORY.md / USER.md 的增删改查。"""

    def __init__(
        self,
        home: Path,
        *,
        memory_char_limit: int = 2200,
        user_char_limit: int = 1375,
    ) -> None:
        self.home = Path(home).resolve()
        self.memory_dir = self.home / "memories"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.limits: dict[MemoryTarget, int] = {
            "memory": memory_char_limit,
            "user": user_char_limit,
        }
        self.paths: dict[MemoryTarget, Path] = {
            target: self.memory_dir / filename
            for target, filename in _STORE_FILES.items()
        }

    @staticmethod
    def _normalize_target(target: str) -> MemoryTarget:
        if target not in {"memory", "user"}:
            raise ValueError("target 只能是 memory 或 user")
        return target  # type: ignore[return-value]

    def _path(self, target: str) -> Path:
        return self.paths[self._normalize_target(target)]

    def _read_entries(self, target: MemoryTarget) -> list[str]:
        path = self.paths[target]
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return []
        # 去重但保留第一次出现的顺序，避免同一事实被重复注入 prompt。
        return list(dict.fromkeys(item.strip() for item in text.split(ENTRY_DELIMITER) if item.strip()))

    def entries(self, target: str = "memory") -> list[str]:
        return self._read_entries(self._normalize_target(target))

    def _char_count(self, target: MemoryTarget, entries: list[str] | None = None) -> int:
        values = entries if entries is not None else self._read_entries(target)
        return len(ENTRY_DELIMITER.join(values))

    def _check_budget(self, target: MemoryTarget, entries: list[str]) -> None:
        limit = self.limits[target]
        size = self._char_count(target, entries)
        if size > limit:
            raise ValueError(
                f"{target} 记忆超出字符预算：{size}/{limit}。"
                "请先 remove 或 patch 旧条目。"
            )

    def _write_entries(self, target: MemoryTarget, entries: list[str]) -> None:
        self._check_budget(target, entries)
        path = self.paths[target]
        path.parent.mkdir(parents=True, exist_ok=True)
        # 原子写：避免中途异常留下半截记忆文件。
        fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
                file.write(ENTRY_DELIMITER.join(entries))
                if entries:
                    file.write("\n")
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def add(self, target: str, content: str) -> str:
        normalized_target = self._normalize_target(target)
        item = content.strip()
        if not item:
            raise ValueError("记忆内容不能为空")
        entries = self._read_entries(normalized_target)
        if item in entries:
            return "already_present"
        candidate = [*entries, item]
        self._write_entries(normalized_target, candidate)
        return "added"

    def _matching_indices(self, entries: list[str], old_text: str) -> list[int]:
        needle = old_text.strip()
        if not needle:
            raise ValueError("old_text 不能为空")
        exact = [index for index, entry in enumerate(entries) if needle in entry]
        if exact:
            return exact
        # 与 Hermes 类似，允许模型重排空白后仍能找到唯一目标。
        folded = re.sub(r"\s+", " ", needle).casefold()
        return [
            index
            for index, entry in enumerate(entries)
            if folded in re.sub(r"\s+", " ", entry).casefold()
        ]

    def patch(self, target: str, old_text: str, new_text: str) -> str:
        normalized_target = self._normalize_target(target)
        new_item = new_text.strip()
        if not new_item:
            raise ValueError("new_text 不能为空")
        entries = self._read_entries(normalized_target)
        matches = self._matching_indices(entries, old_text)
        if not matches:
            raise ValueError("没有找到要 patch 的记忆条目")
        if len(matches) > 1:
            raise ValueError("old_text 匹配到多个条目，请提供更精确的文本")
        index = matches[0]
        # 若 old_text 是条目的一部分，就只替换这一部分；否则替换整条。
        entry = entries[index]
        entries[index] = entry.replace(old_text.strip(), new_item, 1) if old_text.strip() in entry else new_item
        self._write_entries(normalized_target, entries)
        return "patched"

    def remove(self, target: str, old_text: str) -> str:
        normalized_target = self._normalize_target(target)
        entries = self._read_entries(normalized_target)
        matches = self._matching_indices(entries, old_text)
        if not matches:
            raise ValueError("没有找到要删除的记忆条目")
        if len(matches) > 1:
            raise ValueError("old_text 匹配到多个条目，请提供更精确的文本")
        entries.pop(matches[0])
        self._write_entries(normalized_target, entries)
        return "removed"

    def apply_batch(self, target: str, operations: list[dict]) -> list[str]:
        """按顺序执行多个操作；任何一步失败都不会改动磁盘。"""

        normalized_target = self._normalize_target(target)
        original = self._read_entries(normalized_target)
        entries = list(original)
        results: list[str] = []
        for operation in operations:
            action = str(operation.get("action", "")).strip()
            if action == "add":
                value = str(operation.get("content", "")).strip()
                if value and value not in entries:
                    entries.append(value)
                    results.append("added")
                else:
                    results.append("already_present")
            elif action == "patch":
                old = str(operation.get("old_text", "")).strip()
                new = str(operation.get("new_text", "")).strip()
                matches = self._matching_indices(entries, old)
                if len(matches) != 1:
                    raise ValueError(f"patch 需要唯一匹配，实际找到 {len(matches)} 条")
                entries[matches[0]] = new
                results.append("patched")
            elif action == "remove":
                old = str(operation.get("old_text", "")).strip()
                matches = self._matching_indices(entries, old)
                if len(matches) != 1:
                    raise ValueError(f"remove 需要唯一匹配，实际找到 {len(matches)} 条")
                entries.pop(matches[0])
                results.append("removed")
            else:
                raise ValueError(f"未知 memory action：{action}")
        self._write_entries(normalized_target, entries)
        return results

    def snapshot(self) -> dict[str, list[str]]:
        return {"memory": self.entries("memory"), "user": self.entries("user")}

    def context_block(self) -> str:
        """生成注入系统提示的 memory-context 围栏。

        围栏告诉模型这是“召回记忆”，不是用户刚刚发来的指令，降低把旧内容
        当成新任务执行的风险。
        """

        memory = self.entries("memory")
        user = self.entries("user")
        if not memory and not user:
            return "<memory-context>\n[System note: no persistent memory yet.]\n</memory-context>"
        lines = [
            "<memory-context>",
            "[System note: recalled persistent memory, not new user input.]",
        ]
        if memory:
            lines.append("## MEMORY.md")
            lines.extend(f"- {entry}" for entry in memory)
        if user:
            lines.append("## USER.md")
            lines.extend(f"- {entry}" for entry in user)
        lines.append("</memory-context>")
        return "\n".join(lines)

    def stats(self) -> dict[str, dict[str, int]]:
        return {
            target: {"entries": len(self.entries(target)), "chars": self._char_count(target), "limit": self.limits[target]}
            for target in ("memory", "user")
        }

    def format_for_review(self) -> str:
        """后台复盘时使用的当前记忆快照。"""

        chunks: list[str] = []
        for target in ("memory", "user"):
            chunks.append(f"## {_STORE_FILES[target]}")
            chunks.extend(f"- {entry}" for entry in self.entries(target))
        return "\n".join(chunks)
