"""实时轨迹映射的离线测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_trace_module():
    path = Path(__file__).resolve().parents[1] / "docs" / "system-maps" / "trace_to_map.py"
    spec = importlib.util.spec_from_file_location("trace_to_map_for_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hermes_event_mapping() -> None:
    module = _load_trace_module()
    event = {
        "type": "memory_changed",
        "stage": "tools",
        "message": "added",
        "data": {"tool": "memory"},
    }
    row = module.map_event("hermes_harness", event)
    assert row["node"] == "memory"
    assert row["tool"] == "memory"


def test_codex_tool_event_maps_to_tool_node() -> None:
    module = _load_trace_module()
    row = module.map_event("mini_codex", {"type": "tool_started", "stage": "agent", "data": {"tool": "read_file"}})
    assert row["node"] == "tools"
    assert row["tool"] == "read_file"


def test_hermes_review_event_maps_to_review_node() -> None:
    module = _load_trace_module()
    row = module.map_event("hermes_harness", {"type": "review_completed", "stage": "review"})
    assert row["node"] == "review"
