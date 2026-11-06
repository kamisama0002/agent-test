"""DeepSeek Harness 的离线测试（按官方 dsh 事件模型断言）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage

from deepseek_harness.config import DeepSeekHarnessConfig
from deepseek_harness.context import DeepSeekContextManager
from deepseek_harness.harness import DeepSeekHarness


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


def _session_events(run_dir: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (run_dir / "session.v1.jsonl").read_text(encoding="utf-8").splitlines()
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


def test_deepseek_turn_step_session_and_tool_pipeline(tmp_path: Path) -> None:
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
    result = DeepSeekHarness(config, model=FakeModel([first, second])).run("读取 notes.txt 并总结")
    events = _events(result.run_dir)
    event_types = [item["type"] for item in events]
    session_types = [item["type"] for item in _session_events(result.run_dir)]

    assert result.final_answer == "文件内容是 hello。"
    assert result.steps == 2
    assert result.flushes >= 4
    for expected in [
        "turn/start", "step/start", "user/message", "request/header",
        "assistant/message", "tool/call", "tool/result", "step/end", "turn/end",
    ]:
        assert expected in session_types
    assert "agent/request" in event_types
    assert "session/flush" in event_types
    assistant = next(item for item in _session_events(result.run_dir) if item["type"] == "assistant/message")
    blocks = assistant["data"]["message"]["content"]
    assert any(block.get("type") == "reasoning" for block in blocks)
    tool_result = next(item for item in _session_events(result.run_dir) if item["type"] == "tool/result")
    assert tool_result["surfaceOp"] == "append"


def test_deepseek_tool_error_is_recorded_as_tool_result(tmp_path: Path) -> None:
    first = AIMessage(
        content="",
        tool_calls=[{"name": "missing_tool", "args": {}, "id": "bad-call"}],
    )
    second = AIMessage(content="工具不可用，但已经安全结束。")
    config = DeepSeekHarnessConfig(workspace=tmp_path, max_steps=3, console=False, max_model_retries=0)
    result = DeepSeekHarness(config, model=FakeModel([first, second])).run("测试工具失败")
    results = [item for item in _session_events(result.run_dir) if item["type"] == "tool/result"]
    assert results
    assert results[0]["data"]["isError"] is True
    assert results[0]["data"]["error"]["code"] == "UNKNOWN_TOOL"
    assert result.final_answer == "工具不可用，但已经安全结束。"


def test_deepseek_model_retry_uses_llm_retry_events(tmp_path: Path) -> None:
    config = DeepSeekHarnessConfig(
        workspace=tmp_path,
        max_steps=3,
        console=False,
        max_model_retries=1,
        retry_initial_delay_ms=0,
        retry_jitter_ratio=0,
    )
    model = FakeModel([RuntimeError("temporary"), AIMessage(content="重试成功。")])
    result = DeepSeekHarness(config, model=model).run("测试重试")
    event_types = [item["type"] for item in _session_events(result.run_dir)]
    assert "llm/retry" in event_types
    assert "llm/retry-started" in event_types
    assert result.retries == 1
    assert result.final_answer == "重试成功。"


def test_deepseek_model_failure_closes_turn_with_error(tmp_path: Path) -> None:
    config = DeepSeekHarnessConfig(
        workspace=tmp_path,
        max_steps=2,
        console=False,
        max_model_retries=0,
        fault_mode="model_error",
    )
    result = DeepSeekHarness(config, model=FakeModel([AIMessage(content="never used")])).run("测试模型失败")
    session_events = _session_events(result.run_dir)
    assert any(item["type"] == "assistant/attempt" for item in session_events)
    end = next(item for item in reversed(session_events) if item["type"] == "turn/end")
    assert end["data"]["reason"]["kind"] == "error"
    assert result.success is False
