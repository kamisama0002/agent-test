"""把 Harness 的 events.jsonl 映射到 Archify 流程图节点。

这是“实时沟通”的轻量桥：流程图本身由 Archify 生成，运行轨迹由 Harness
写 JSONL；本脚本负责把运行阶段翻译成图中的节点 ID，便于一边跑一边观察。

示例：
    python docs/system-maps/trace_to_map.py --system hermes_harness \
      --run-dir "$env:TEMP/hermes_harness_demo/.hermes/runs/<timestamp>" --watch
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any



EVENT_TO_NODE: dict[str, dict[str, str]] = {
    "mini_codex": {
        "context_built": "context", "context_assembled": "context",
        "tool_started": "tools", "tool_finished": "tools", "plan_created": "plan",
        "verification_completed": "verify", "run_completed": "final",
        "approval_decision": "extensions", "plugin_tools_loaded": "extensions",
        "plugin_loaded": "extensions",
        "mcp_tools_loaded": "extensions", "multi_agent_tools_loaded": "multi_agent",
        "fallback_applied": "error", "failure_summary": "error", "limit_reached": "error",
        "retry_scheduled": "error", "retry_succeeded": "model",
    },
    "claude_harness": {
        "context_prepared": "prepare", "context_assembled": "prepare",
        "tool_started": "tools", "tool_finished": "tools", "permission_decision": "permissions",
        "hook_pre_tool": "hooks", "hook_post_tool": "hooks",
        "verification_completed": "verify", "query_completed": "finalize",
        "plugin_loaded": "extensions", "plugin_tools_loaded": "extensions", "mcp_tools_loaded": "extensions",
    },
    "hermes_harness": {
        "context_prepared": "prepare", "context_assembled": "prepare", "memory_changed": "memory",
        "skill_viewed": "skills", "skill_changed": "skills",
        "review_completed": "review", "turn_completed": "finalize",
        "verification_completed": "verify", "approval_decision": "approval",
        "plugin_loaded": "extensions", "plugin_tools_loaded": "extensions", "mcp_tools_loaded": "extensions",
        "multi_agent_tools_loaded": "multi_agent",
        "failure_summary": "finalize", "limit_reached": "finalize",
    },
    "deepseek_harness": {
        "context_built": "context", "run_started": "boot",
        "turn/start": "model", "step/start": "model", "step/end": "model", "turn/end": "verify",
        "user/message": "model", "request/header": "model", "agent/request": "model",
        "assistant/message": "model", "assistant/attempt": "error",
        "llm/retry": "error", "llm/retry-started": "error",
        "tool/call": "tools", "tool/result": "tools",
        "approval/policy": "error", "approval/asked": "error", "approval/decided": "error",
        "session/flush": "events", "checkpoint_saved": "events",
        "compaction/start": "events", "compaction/prune": "events",
        "compaction/summary": "events", "compaction/end": "events",
        "todo/write": "plan", "verification_completed": "verify", "verification_skipped": "verify",
        "run_completed": "final", "plugin_loaded": "extensions", "plugin_tools_loaded": "extensions",
        "mcp_tools_loaded": "extensions", "multi_agent_tools_loaded": "multi_agent",
        "fallback_applied": "error", "failure_summary": "error", "limit_reached": "error",
        "fault_injected": "error", "reasoning_content": "model",
    },

}

STAGE_TO_NODE: dict[str, dict[str, str]] = {
    "mini_codex": {
        "bootstrap": "boot",
        "context": "context",
        "plan": "plan",
        "agent": "model",
        "verify": "verify",
        "finalize": "final",
    },
    "claude_harness": {
        "prepare": "prepare",
        "plan": "plan",
        "model": "model",
        "tools": "tools",
        "compact": "compact",
        "finalize": "finalize",
        "verify": "verify",
    },
    "hermes_harness": {
        "bootstrap": "start",
        "prepare": "prepare",
        "model": "model",
        "tools": "tools",
        "finalize": "finalize",
        "review": "review",
        "verify": "verify",
    },
    "deepseek_harness": {
        "bootstrap": "boot",
        "context": "context",
        "plan": "plan",
        "agent": "model",
        "verify": "verify",
        "finalize": "final",
    },
}


def map_event(system: str, event: dict[str, Any]) -> dict[str, Any]:
    mapping = STAGE_TO_NODE.get(system, {})
    stage = str(event.get("stage") or "")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    event_type = str(event.get("type") or "")
    node = EVENT_TO_NODE.get(system, {}).get(event_type, mapping.get(stage, "unknown"))
    if event_type.startswith("sandbox/"):
        node = "extensions"
    return {
        "system": system,
        "stage": stage,
        "node": node,
        "event": event.get("type", ""),
        "message": event.get("message", ""),
        "tool": data.get("tool"),
        "data": data,
        "timestamp": event.get("timestamp"),
    }


def read_events(run_dir: Path, system: str) -> list[dict[str, Any]]:
    path = run_dir / "events.jsonl"
    if not path.exists():
        raise FileNotFoundError(path)
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(map_event(system, json.loads(line)))
        except json.JSONDecodeError:
            continue
    return rows


def watch(run_dir: Path, system: str) -> None:
    path = run_dir / "events.jsonl"
    offset = 0
    if path.exists():
        offset = path.stat().st_size
        print(json.dumps({"watching": str(path), "from_offset": offset}, ensure_ascii=False))
    while True:
        if not path.exists():
            time.sleep(0.5)
            continue
        with path.open("r", encoding="utf-8", errors="replace") as file:
            file.seek(offset)
            for line in file:
                if not line.strip():
                    continue
                try:
                    print(json.dumps(map_event(system, json.loads(line)), ensure_ascii=False), flush=True)
                except json.JSONDecodeError:
                    print(line.rstrip(), flush=True)
            offset = file.tell()
        time.sleep(0.5)


def main() -> int:
    parser = argparse.ArgumentParser(description="把 Harness events.jsonl 映射到 Archify 节点")
    parser.add_argument("--run-dir", required=True, help="包含 events.jsonl 的运行目录")
    parser.add_argument("--system", choices=sorted(STAGE_TO_NODE), default="hermes_harness")
    parser.add_argument("--watch", action="store_true", help="持续跟随新事件")
    parser.add_argument("--json", action="store_true", help="输出 JSON 数组而不是逐行")
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    if args.watch:
        watch(run_dir, args.system)
        return 0
    rows = read_events(run_dir, args.system)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
