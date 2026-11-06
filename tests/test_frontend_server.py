"""Web 前端后端的离线接口测试（不调用模型）。"""

from __future__ import annotations

from frontend.server import ChatSession


def test_frontend_config_and_node_inspection() -> None:
    session = ChatSession()
    config = session.config()
    assert set(config["systems"]) == {"codex", "claude", "hermes"}
    trace = session.trace("codex")
    assert "events" in trace
    assert "workspace" in trace
    node = session.node_info("codex", "setup")
    assert node["node"]["id"] == "setup"
    assert node["sources"]
    assert "mini_codex/harness.py" in node["sources"][0]["path"]
