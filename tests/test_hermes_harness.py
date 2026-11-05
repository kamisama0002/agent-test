"""Hermes Harness 的离线闭环测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage

from hermes_harness.config import HermesHarnessConfig
from hermes_harness.harness import HermesHarness
from hermes_harness.tools import ToolContext, build_tools


class FakeModel:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.seen: list[Any] = []

    def bind_tools(self, tools, **kwargs):
        self.bound_tools = tools
        return self

    def invoke(self, messages):
        self.seen.append(messages)
        if not self.responses:
            raise RuntimeError("no fake response left")
        return self.responses.pop(0)


def _context(tmp_path: Path) -> ToolContext:
    from hermes_harness.memory import MemoryStore
    from hermes_harness.sessions import SessionStore
    from hermes_harness.skills import SkillStore

    return ToolContext(
        workspace=tmp_path,
        home=tmp_path / ".hermes",
        memory=MemoryStore(tmp_path / ".hermes"),
        skills=SkillStore(tmp_path / ".hermes"),
        sessions=SessionStore(tmp_path / ".hermes"),
    )


def test_toolsets_are_filtered_and_paths_are_bounded(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    ctx = _context(tmp_path)
    tools = {item.name: item for item in build_tools(ctx, ("file",))}
    assert "read_file" in tools and "memory" not in tools
    assert "hello" in tools["read_file"].invoke({"path": "notes.txt"})
    try:
        tools["read_file"].invoke({"path": "../outside.txt"})
    except ValueError as exc:
        assert "越界" in str(exc)
    else:
        raise AssertionError("path escape should fail")
    ctx.sessions.close()


def test_harness_main_loop_and_session_record(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("Hermes 会检索历史。", encoding="utf-8")
    main_model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "read_file", "args": {"path": "notes.txt"}, "id": "call-1"}],
            ),
            AIMessage(content="已经读取 notes.txt。"),
        ]
    )
    config = HermesHarnessConfig(
        workspace=tmp_path,
        toolsets=("file", "session_search"),
        enable_background_review=False,
        console=False,
    )
    harness = HermesHarness(config, model=main_model)
    result = harness.run("读取文件并总结")
    assert result.final_answer == "已经读取 notes.txt。"
    assert result.success is True
    assert result.turns == 2
    assert harness.sessions.search("Hermes")[0]["session_id"] == result.session_id
    assert result.run_dir.exists()
    assert (result.run_dir / "events.jsonl").exists()
    harness.close()


def test_background_review_updates_memory_and_skill(tmp_path: Path) -> None:
    main_model = FakeModel([AIMessage(content="任务完成，用户喜欢中文。")])
    review_model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "memory",
                        "args": {"action": "add", "target": "user", "content": "用户偏好中文总结。"},
                        "id": "review-memory",
                    },
                    {
                        "name": "skill_manage",
                        "args": {
                            "action": "create",
                            "name": "repo-summary",
                            "description": "总结一个代码仓库的结构与测试方式",
                            "body": "先读 README 和测试入口，再按模块总结。",
                            "category": "research",
                        },
                        "id": "review-skill",
                    },
                ],
            ),
            AIMessage(content="已保存用户偏好，并创建 repo-summary 技能。"),
        ]
    )
    config = HermesHarnessConfig(
        workspace=tmp_path,
        toolsets=("file", "memory", "skills"),
        enable_background_review=True,
        console=False,
    )
    harness = HermesHarness(config, model=main_model, review_model=review_model)
    result = harness.run("请以后都用中文总结")
    assert result.final_answer == "任务完成，用户喜欢中文。"
    assert result.review is not None and not result.review.error
    assert harness.memory.entries("user") == ["用户偏好中文总结。"]
    assert harness.skills.find("repo-summary") is not None
    assert "user" in result.review.changed_memory
    assert "repo-summary" in result.review.changed_skills
    harness.close()


def test_review_failure_does_not_replace_main_answer(tmp_path: Path) -> None:
    main_model = FakeModel([AIMessage(content="主任务答案")])

    class BrokenReview:
        def bind_tools(self, tools, **kwargs):
            raise RuntimeError("review unavailable")

    config = HermesHarnessConfig(
        workspace=tmp_path,
        toolsets=("file",),
        enable_background_review=True,
        console=False,
    )
    harness = HermesHarness(config, model=main_model, review_model=BrokenReview())
    result = harness.run("完成一个小任务")
    assert result.final_answer == "主任务答案"
    assert result.review is not None
    assert result.review.error
    assert any("review:" in item for item in result.errors)
    harness.close()


