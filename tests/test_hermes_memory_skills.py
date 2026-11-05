"""Hermes memory / skills / session 的离线测试。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hermes_harness.memory import MemoryStore
from hermes_harness.sessions import SessionStore
from hermes_harness.skills import SkillStore


def test_memory_add_patch_remove_and_fence(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    assert store.add("memory", "项目使用 uv。") == "added"
    assert store.add("memory", "项目使用 uv。") == "already_present"
    assert store.add("user", "用户偏好中文总结。") == "added"
    assert store.patch("memory", "uv", "uv 和 pytest") == "patched"
    assert "uv 和 pytest" in store.entries("memory")[0]
    assert "<memory-context>" in store.context_block()
    assert "not new user input" in store.context_block()
    assert store.remove("user", "中文总结") == "removed"
    assert store.entries("user") == []


def test_memory_budget_is_enforced(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path, memory_char_limit=12)
    store.add("memory", "123456")
    with pytest.raises(ValueError, match="字符预算"):
        store.add("memory", "1234567")
    assert store.entries("memory") == ["123456"]


def test_memory_batch_is_atomic(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    store.add("memory", "old")
    with pytest.raises(ValueError):
        store.apply_batch("memory", [{"action": "add", "content": "new"}, {"action": "remove", "old_text": "missing"}])
    assert store.entries("memory") == ["old"]


def test_skill_create_view_usage_archive_never_delete(tmp_path: Path) -> None:
    store = SkillStore(tmp_path)
    path = store.save(
        "python-testing",
        "用 pytest 验证 Python 改动",
        "先读测试，做最小修改，再运行 pytest。",
        category="coding",
        files={"references/checklist.md": "先跑最小测试。"},
    )
    assert path.is_file()
    assert "python-testing" in store.index_text()
    view = store.view("python-testing")
    assert "pytest" in view.content
    assert "references/checklist.md" in view.support_files
    store.record_use("python-testing")
    assert store.usage_snapshot()["python-testing"]["use_count"] == 1

    archived = store.archive("python-testing")
    assert archived.is_dir()
    assert "python-testing" not in store.index_text()
    assert (tmp_path / "skills" / ".archive" / "python-testing" / "SKILL.md").is_file()


def test_skill_description_limit_and_curator(tmp_path: Path) -> None:
    store = SkillStore(tmp_path)
    with pytest.raises(ValueError, match="60"):
        store.save("too-long", "x" * 61, "body")
    store.save("old-skill", "处理一类重复任务", "body", created_by="agent")
    usage = store.usage_snapshot()
    usage["old-skill"]["created_at"] = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    store.usage_path.write_text(json.dumps(usage), encoding="utf-8")
    result = store.curate(stale_after_days=14, archive_after_days=30)
    assert result["archived"] == 1
    assert "old-skill" not in store.index_text()
    assert (tmp_path / "skills" / ".archive" / "old-skill").exists()


def test_session_search_supports_chinese_bigram(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_id = store.create_session("Hermes 学习")
    store.append_message(session_id, "user", "请解释 Hermes 的长期记忆与技能自动整理。")
    store.append_message(session_id, "assistant", "后台复盘会在回合结束后写 MEMORY.md。")
    store.end_session(session_id)
    results = store.search("长期记忆")
    assert results
    assert results[0]["session_id"] == session_id
    assert "长期记忆" in results[0]["snippet"]
    assert store.search("技能自动整理")
    store.close()
