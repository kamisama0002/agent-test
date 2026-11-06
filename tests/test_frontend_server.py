"""Web 前端后端的离线接口测试（不调用模型）。"""

from __future__ import annotations

import json
from pathlib import Path

from frontend.explanations import explain_event
from frontend.server import ChatSession


def test_frontend_config_and_node_inspection() -> None:
    session = ChatSession()
    config = session.config()
    assert set(config["systems"]) == {"codex", "claude", "hermes", "deepseek"}
    trace = session.trace("codex")
    assert "events" in trace
    assert "workspace" in trace
    node = session.node_info("codex", "setup")
    assert node["node"]["id"] == "setup"
    assert node["sources"]
    assert "mini_codex/harness.py" in node["sources"][0]["path"]


def test_context_event_explanation_contains_design_rationale() -> None:
    event = {
        "event": "context_built",
        "stage": "context",
        "message": "上下文构建完成",
        "data": {
            "message_count": 3,
            "context_snapshot": {
                "System Prompt": "system",
                "AGENTS.md": "rules",
            },
        },
    }
    explanation = explain_event("codex", event)
    assert explanation["title"] == "构建上下文"
    assert "完整内容" in explanation["output"]
    assert explanation["design"]
    assert "Codex" in explanation["system_design"]
    assert explanation["next"]


def test_trace_adds_explanation_to_each_event() -> None:
    session = ChatSession()
    workspace = session.workspaces["deepseek"]
    run_dir = workspace / ".deepseek" / "runs" / "test-run"
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").write_text(
        json.dumps(
            {
                "type": "assistant/message",
                "stage": "agent",
                "message": "hello",
                "data": {
                    "turn": 1,
                    "step": 1,
                    "text": "hello",
                    "reasoning": "",
                    "tool_calls": [],
                    "usage": {},
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    trace = session.trace("deepseek")
    assert trace["events"]
    event = trace["events"][0]
    assert event["event"] == "assistant/message"
    assert event["node"] == "model"
    assert event["explanation"]["title"] == "记录助手消息"
    assert event["explanation"]["design"]
    assert event["explanation"]["source_refs"]
