"""DeepSeek Harness 的离线测试（不调用真实模型）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage

from deepseek_harness.config import DeepSeekHarnessConfig
from deepseek_harness.context import DeepSeekContextManager
from deepseek_harness.harness import DeepSeekHarness
from mini_codex.state import Plan, PlanItem


class FakePlanner:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, messages: list[Any]) -> Plan:
        self.calls += 1
        return Plan(
            summary="检查、修复、验证",
            items=[
                PlanItem(title="读取相关文件"),
                PlanItem(title="修复 bug"),
                PlanItem(title="运行测试"),
            ],
        )


class FakeModel:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.bound_tools: list[Any] = []
        self.seen: list[Any] = []

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "FakeModel":
        self.bound_tools = tools
        return self

    def invoke(self, messages: list[Any]) -> Any:
        self.seen.append(messages)
        if not self.responses:
            raise RuntimeError("no fake response left")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _events(run_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_deepseek_context_snapshot_and_secret_boundary(tmp_path: Path) -> None:
    (tmp_path / "DEEPSEEK.md").write_text("先读测试，再修改。", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET_SHOULD_NOT_APPEAR", encoding="utf-8")
    manager = DeepSeekContextManager(tmp_path, model_name="deepseek-test")
    snapshot = manager.snapshot("修复 bug")
    assert "先读测试，再修改。" in snapshot["DEEPSEEK.md / AGENTS.md"]
    assert "SECRET_SHOULD_NOT_APPEAR" not in json.dumps(snapshot, ensure_ascii=False)
    assert snapshot["Model"] == "deepseek-test"


def test_deepseek_loop_records_reasoning_context_and_checkpoint(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    first = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": "先读取文件，再总结。"},
        tool_calls=[{"name": "read_file", "args": {"path": "notes.txt"}, "id": "call-1"}],
    )
    second = AIMessage(content="文件内容是 hello。")
    config = DeepSeekHarnessConfig(
        workspace=tmp_path,
        max_steps=4,
        console=False,
        max_model_retries=0,
    )
    result = DeepSeekHarness(
        config,
        model=FakeModel([first, second]),
        planner=FakePlanner(),
    ).run("读取 notes.txt 并总结")
    events = _events(result.run_dir)
    event_types = [item["type"] for item in events]

    assert result.final_answer == "文件内容是 hello。"
    assert result.checkpoints >= 2
    assert "context_built" in event_types
    assert "context_assembled" in event_types
    assert "reasoning_content" in event_types
    assert "checkpoint_saved" in event_types
    context_event = next(item for item in events if item["type"] == "context_assembled")
    assert "System Prompt" in context_event["data"]["context_snapshot"]
    assert context_event["data"]["messages"]


def test_deepseek_tool_error_is_returned_to_model(tmp_path: Path) -> None:
    first = AIMessage(
        content="",
        tool_calls=[{"name": "missing_tool", "args": {}, "id": "bad-call"}],
    )
    second = AIMessage(content="工具不可用，但已经安全结束。")
    config = DeepSeekHarnessConfig(workspace=tmp_path, max_steps=3, console=False, max_model_retries=0)
    result = DeepSeekHarness(
        config,
        model=FakeModel([first, second]),
        planner=FakePlanner(),
    ).run("测试工具失败")
    events = _events(result.run_dir)
    fallbacks = [item for item in events if item["type"] == "fallback_applied"]
    assert fallbacks
    assert fallbacks[0]["data"]["strategy"] == "return_tool_error_to_model"
    assert result.final_answer == "工具不可用，但已经安全结束。"


def test_deepseek_model_retry_is_visible(tmp_path: Path) -> None:
    config = DeepSeekHarnessConfig(
        workspace=tmp_path,
        max_steps=3,
        console=False,
        max_model_retries=1,
        retry_delay_seconds=0,
    )
    model = FakeModel([RuntimeError("temporary"), AIMessage(content="重试成功。")])
    result = DeepSeekHarness(config, model=model, planner=FakePlanner()).run("测试重试")
    event_types = [item["type"] for item in _events(result.run_dir)]
    assert "retry_scheduled" in event_types
    assert "retry_succeeded" in event_types
    assert result.retries == 1
    assert result.final_answer == "重试成功。"
