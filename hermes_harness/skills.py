"""Hermes 风格的 Skills 程序性记忆。

一个技能不是一段聊天记录，而是“以后如何完成一类任务”的可复用说明：

    skills/[category/]<name>/
      SKILL.md
      references/
      templates/
      scripts/
      assets/

关键规则与 Hermes 对齐：

- SKILL.md frontmatter 中的 description <= 60 字符；
- 索引只暴露 name/description/category，正文通过 skill_view 渐进读取；
- Agent 创建/修改技能时必须先 view，再写（工具层可做 read-before-write）；
- usage.json 记录使用、查看、修改和 pinned/state；
- curator 只整理 created_by=agent 的技能，只归档不删除。
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


@dataclass
class SkillEntry:
    name: str
    description: str
    path: Path
    category: str = ""
    created_by: str = "unknown"
    version: str = "1"
    tags: list[str] = field(default_factory=list)
    related_skills: list[str] = field(default_factory=list)

    @property
    def directory(self) -> Path:
        return self.path.parent

    def index_line(self) -> str:
        category = f" [{self.category}]" if self.category else ""
        return f"- {self.name}{category}: {self.description}"


@dataclass
class SkillView:
    name: str
    content: str
    support_files: list[str]


def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        return [item.strip().strip("'\"") for item in value[1:-1].split(",") if item.strip()]
    return value.strip("'\"")


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta: dict[str, Any] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, raw = line.split(":", 1)
        key = key.strip()
        # 简化版只解析顶层字段；metadata 里的 tags 用 dot key 表示。
        if key == "metadata":
            continue
        meta[key] = _parse_scalar(raw)
    body = text[match.end():]
    # metadata.hermes.* 在真实 Hermes 中很常见，这里兼容 extraction。
    metadata_match = re.search(r"metadata:\s*\n((?:[ \t]+.*\n?)*)", match.group(1))
    if metadata_match:
        for line in metadata_match.group(1).splitlines():
            if ":" in line:
                key, raw = line.strip().split(":", 1)
                meta[f"metadata.{key.strip()}"] = _parse_scalar(raw)
    return meta, body


def _format_frontmatter(meta: dict[str, Any]) -> str:
    lines = ["---"]
    for key in ("name", "description", "version", "author", "license", "created_by", "category"):
        if key in meta:
            lines.append(f"{key}: {meta[key]}")
    tags = meta.get("tags") or []
    if tags:
        lines.append(f"tags: [{', '.join(str(tag) for tag in tags)}]")
    related = meta.get("related_skills") or []
    if related:
        lines.append(f"related_skills: [{', '.join(str(item) for item in related)}]")
    lines.append("---")
    return "\n".join(lines)


class SkillStore:
    """扫描、创建、查看和整理 SKILL.md。"""

    def __init__(self, home: Path) -> None:
        self.home = Path(home).resolve()
        self.root = self.home / "skills"
        self.root.mkdir(parents=True, exist_ok=True)
        self.usage_path = self.root / ".usage.json"
        self.archive_root = self.root / ".archive"

    def _usage(self) -> dict[str, dict[str, Any]]:
        if not self.usage_path.exists():
            return {}
        try:
            data = json.loads(self.usage_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_usage(self, usage: dict[str, dict[str, Any]]) -> None:
        self.usage_path.write_text(
            json.dumps(usage, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _default_usage(self, name: str) -> dict[str, Any]:
        return {
            "use_count": 0,
            "view_count": 0,
            "patch_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_used_at": None,
            "last_viewed_at": None,
            "state": "active",
            "pinned": False,
        }

    def _record(self, name: str, field: str) -> None:
        usage = self._usage()
        row = usage.setdefault(name, self._default_usage(name))
        row[field] = int(row.get(field, 0) or 0) + 1
        row["last_used_at" if field == "use_count" else "last_viewed_at" if field == "view_count" else "last_patched_at"] = (
            datetime.now(timezone.utc).isoformat()
        )
        self._save_usage(usage)

    def record_use(self, name: str) -> None:
        self._record(name, "use_count")

    def record_view(self, name: str) -> None:
        self._record(name, "view_count")
        # 查看也算一次活动，但单独保留 view_count 便于统计。
        usage = self._usage()
        row = usage.setdefault(name, self._default_usage(name))
        row["last_used_at"] = datetime.now(timezone.utc).isoformat()
        self._save_usage(usage)

    def _usage_data(self) -> dict[str, dict[str, Any]]:
        return self._usage()

    def scan(self) -> list[SkillEntry]:
        result: list[SkillEntry] = []
        if not self.root.exists():
            return result
        for path in sorted(self.root.rglob("SKILL.md")):
            if ".archive" in path.parts or ".usage" in path.name:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                meta, _ = _parse_frontmatter(text)
            except OSError:
                continue
            name = str(meta.get("name") or path.parent.name).strip()
            if not name:
                continue
            relative_parent = path.parent.relative_to(self.root)
            category = str(meta.get("category") or (relative_parent.parts[0] if len(relative_parent.parts) > 1 else ""))
            description = str(meta.get("description") or "").strip()
            if not description:
                description = "(no description)"
            tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
            related = meta.get("related_skills") if isinstance(meta.get("related_skills"), list) else []
            result.append(
                SkillEntry(
                    name=name,
                    description=description,
                    path=path,
                    category=category,
                    created_by=str(meta.get("created_by") or meta.get("author") or "unknown"),
                    version=str(meta.get("version") or "1"),
                    tags=[str(item) for item in tags],
                    related_skills=[str(item) for item in related],
                )
            )
        return result

    def index(self) -> list[SkillEntry]:
        return self.scan()

    def index_text(self) -> str:
        entries = self.scan()
        if not entries:
            return "(no skills yet)"
        return "\n".join(entry.index_line() for entry in entries)

    def find(self, name: str) -> SkillEntry | None:
        normalized = name.strip().lower()
        for entry in self.scan():
            if entry.name.lower() == normalized:
                return entry
        return None

    def _safe_support_path(self, skill_dir: Path, relative: str) -> Path:
        target = (skill_dir / relative).resolve()
        root = skill_dir.resolve()
        if target != root and root not in target.parents:
            raise ValueError("技能支持文件路径越界")
        return target

    def view(self, name: str, file_path: str | None = None) -> SkillView:
        entry = self.find(name)
        if entry is None:
            raise ValueError(f"技能不存在：{name}")
        if file_path:
            target = self._safe_support_path(entry.directory, file_path)
            if not target.is_file():
                raise ValueError(f"技能文件不存在：{file_path}")
            self.record_view(entry.name)
            return SkillView(entry.name, target.read_text(encoding="utf-8", errors="replace"), [])
        text = entry.path.read_text(encoding="utf-8", errors="replace")
        support = []
        for path in sorted(entry.directory.rglob("*")):
            if path.is_file() and path != entry.path:
                support.append(path.relative_to(entry.directory).as_posix())
        self.record_view(entry.name)
        # Hermes 的 skill_view 会把正文注入上下文；这里限制大小，防止无限膨胀。
        if len(text) > 24000:
            text = text[:24000] + "\n...[skill truncated; open support files for details]"
        return SkillView(entry.name, text, support)

    def save(
        self,
        name: str,
        description: str,
        body: str,
        *,
        category: str = "",
        created_by: str = "agent",
        version: str = "1",
        tags: list[str] | None = None,
        related_skills: list[str] | None = None,
        update: bool = False,
        files: dict[str, str] | None = None,
    ) -> Path:
        name = name.strip().lower()
        if not _NAME_RE.fullmatch(name):
            raise ValueError("技能名必须是 2-64 位小写字母、数字或连字符，且以字母开头")
        description = " ".join(description.strip().split())
        if not description:
            raise ValueError("技能 description 不能为空")
        if len(description) > 60:
            raise ValueError("技能 description 不能超过 60 个字符（为了索引可扫描）")
        if category and not _CATEGORY_RE.fullmatch(category):
            raise ValueError("category 只能使用小写字母、数字、下划线或连字符")
        existing = self.find(name)
        if existing is not None and not update:
            raise ValueError(f"技能已存在：{name}；若要修改请显式 update=True")
        if existing is not None:
            skill_dir = existing.directory
        else:
            skill_dir = self.root / (category or "general") / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "name": name,
            "description": description,
            "version": version,
            "author": created_by,
            "created_by": created_by,
            "license": "MIT",
            "category": category or (existing.category if existing else "general"),
            "tags": tags or [],
            "related_skills": related_skills or [],
        }
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text(_format_frontmatter(meta) + "\n\n" + body.strip() + "\n", encoding="utf-8")
        usage = self._usage()
        usage.setdefault(name, self._default_usage(name))
        self._save_usage(usage)
        if existing is not None:
            self._record(name, "patch_count")
        for relative, content in (files or {}).items():
            target = self._safe_support_path(skill_dir, relative)
            if target == skill_path:
                raise ValueError("files 不能覆盖 SKILL.md")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return skill_path

    def add_file(self, name: str, relative: str, content: str) -> Path:
        entry = self.find(name)
        if entry is None:
            raise ValueError(f"技能不存在：{name}")
        target = self._safe_support_path(entry.directory, relative)
        if target == entry.path:
            raise ValueError("请使用 save(update=True) 修改 SKILL.md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._record(entry.name, "patch_count")
        return target

    def remove_file(self, name: str, relative: str) -> str:
        entry = self.find(name)
        if entry is None:
            raise ValueError(f"技能不存在：{name}")
        target = self._safe_support_path(entry.directory, relative)
        if target == entry.path:
            raise ValueError("不能删除 SKILL.md；请归档整个技能")
        if not target.is_file():
            raise ValueError(f"技能文件不存在：{relative}")
        target.unlink()
        self._record(entry.name, "patch_count")
        return "removed"

    def set_pinned(self, name: str, pinned: bool) -> dict[str, Any]:
        entry = self.find(name)
        if entry is None:
            raise ValueError(f"技能不存在：{name}")
        usage = self._usage()
        row = usage.setdefault(entry.name, self._default_usage(entry.name))
        row["pinned"] = bool(pinned)
        self._save_usage(usage)
        return row

    def archive(self, name: str) -> Path:
        entry = self.find(name)
        if entry is None:
            raise ValueError(f"技能不存在：{name}")
        self.archive_root.mkdir(parents=True, exist_ok=True)
        destination = self.archive_root / entry.name
        if destination.exists():
            destination = self.archive_root / f"{entry.name}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        shutil.move(str(entry.directory), str(destination))
        usage = self._usage()
        row = usage.setdefault(entry.name, self._default_usage(entry.name))
        row["state"] = "archived"
        row["archived_at"] = datetime.now(timezone.utc).isoformat()
        self._save_usage(usage)
        return destination

    def curate(self, stale_after_days: int = 14, archive_after_days: int = 30, *, now: datetime | None = None) -> dict[str, int]:
        """确定性 curator：只整理 agent 创建且未 pinned 的技能。"""

        if stale_after_days < 1 or archive_after_days <= stale_after_days:
            raise ValueError("需要 1 <= stale_after_days < archive_after_days")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        counts = {"stale": 0, "archived": 0, "active": 0, "skipped": 0}
        usage = self._usage()
        for entry in list(self.scan()):
            if entry.created_by != "agent":
                counts["skipped"] += 1
                continue
            row = usage.setdefault(entry.name, self._default_usage(entry.name))
            if row.get("pinned"):
                counts["skipped"] += 1
                continue
            raw_anchor = row.get("last_used_at") or row.get("created_at")
            try:
                anchor = datetime.fromisoformat(str(raw_anchor).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                anchor = current
            if anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=timezone.utc)
            age_days = (current - anchor).total_seconds() / 86400
            if age_days >= archive_after_days:
                row["state"] = "archived"
                row["archived_at"] = current.isoformat()
                self.archive(entry.name)
                counts["archived"] += 1
            elif age_days >= stale_after_days:
                row["state"] = "stale"
                counts["stale"] += 1
            else:
                if row.get("state") == "stale":
                    row["state"] = "active"
                counts["active"] += 1
        self._save_usage(usage)
        return counts

    def usage_snapshot(self) -> dict[str, dict[str, Any]]:
        return self._usage()

    def context_index(self) -> str:
        return self.index_text()

    def format_for_review(self) -> str:
        """给后台复盘模型看的紧凑索引与使用状态。"""

        usage = self._usage()
        lines = ["# Skills"]
        for entry in self.scan():
            row = usage.get(entry.name, {})
            lines.append(
                f"- {entry.name} [{entry.category}] ({entry.created_by}, "
                f"uses={row.get('use_count', 0)}, state={row.get('state', 'active')}): {entry.description}"
            )
        return "\n".join(lines) if len(lines) > 1 else "# Skills\n(no skills yet)"

