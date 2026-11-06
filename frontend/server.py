"""Mini Harness 的本地 Web 前端。

启动：

```powershell
uv run python frontend/server.py --open
```

页面提供：
- Codex / Claude / Hermes 切换；
- 对话输入；
- Archify 流程图；
- events.jsonl 实时高亮；
- 点击节点查看源码位置和当前机制。

后端只绑定 127.0.0.1，不读取 .env。
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import shutil
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "docs" / "system-maps") not in sys.path:
    sys.path.insert(0, str(ROOT / "docs" / "system-maps"))

from trace_to_map import map_event  # noqa: E402
from frontend.explanations import explain_event  # noqa: E402


SYSTEMS = {
    "codex": {
        "label": "Mini Codex",
        "internal": "mini_codex",
        "demo": "mini_codex_demo",
        "diagram": "mini-codex.html",
        "workflow": "mini-codex.workflow.json",
        "run_root": ".mini_codex/runs",
    },
    "claude": {
        "label": "Claude mini",
        "internal": "claude_harness",
        "demo": "claude_harness_demo",
        "diagram": "claude-harness.html",
        "workflow": "claude-harness.workflow.json",
        "run_root": ".claude/runs",
    },
    "hermes": {
        "label": "Hermes mini",
        "internal": "hermes_harness",
        "demo": "hermes_harness_demo",
        "diagram": "hermes-harness.html",
        "workflow": "hermes-harness.workflow.json",
        "run_root": ".hermes/runs",
    },
    "deepseek": {
        "label": "DeepSeek Harness",
        "internal": "deepseek_harness",
        "demo": "deepseek_harness_demo",
        "diagram": "deepseek-harness.html",
        "workflow": "deepseek-harness.workflow.json",
        "run_root": ".deepseek/runs",
    },
}


def _make_workspace(system: str) -> Path:
    source = ROOT / "examples" / SYSTEMS[system]["demo"]
    target = Path(tempfile.mkdtemp(prefix=f"mini-frontend-{system}-"))
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".mini_codex", ".claude", ".hermes", ".git"))
    return target


def _workflow(system: str) -> dict:
    path = ROOT / "docs" / "system-maps" / "sources" / SYSTEMS[system]["workflow"]
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_run(system: str, workspace: Path) -> Path | None:
    root = workspace / SYSTEMS[system]["run_root"]
    if not root.is_dir():
        return None
    runs = [item for item in root.iterdir() if (item / "events.jsonl").is_file()]
    if not runs:
        return None
    return max(runs, key=lambda item: item.stat().st_mtime)


def _task_with_history(history: list[tuple[str, str]], message: str) -> str:
    if not history:
        return message
    lines = ["# 之前的对话（仅作上下文，不要逐字复述）"]
    for role, text in history[-8:]:
        lines.append(f"{role}: {text}")
    lines.extend(["", "# 当前用户消息", message])
    return "\n".join(lines)


class ChatSession:
    def __init__(self) -> None:
        self.workspaces = {key: _make_workspace(key) for key in SYSTEMS}
        self.history: dict[str, list[tuple[str, str]]] = {key: [] for key in SYSTEMS}
        self.locks = {key: threading.Lock() for key in SYSTEMS}

    def config(self) -> dict:
        return {
            "systems": {
                key: {
                    "label": value["label"],
                    "workspace": str(self.workspaces[key]),
                    "internal": value["internal"],
                }
                for key, value in SYSTEMS.items()
            }
        }

    def trace(self, system: str) -> dict:
        if system not in SYSTEMS:
            raise ValueError("unknown system")
        workspace = self.workspaces[system]
        run_dir = _latest_run(system, workspace)
        events = []
        if run_dir is not None:
            for line in (run_dir / "events.jsonl").read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    event = map_event(SYSTEMS[system]["internal"], json.loads(line))
                    event["explanation"] = explain_event(system, event)
                    events.append(event)
                except json.JSONDecodeError:
                    continue
        nodes = {node["id"]: node for node in _workflow(system).get("nodes", [])}
        for event in events:
            node = nodes.get(event.get("node", ""))
            event["node_label"] = node.get("label") if node else None
        workflow = _workflow(system)
        return {
            "system": system,
            "workspace": str(workspace),
            "run_dir": str(run_dir) if run_dir else "",
            "events": events,
            "nodes": [
                {
                    "id": node["id"],
                    "label": node.get("label"),
                    "sublabel": node.get("sublabel"),
                    "type": node.get("type"),
                    "tag": node.get("tag"),
                }
                for node in workflow.get("nodes", [])
            ],
        }

    def node_info(self, system: str, node_id: str) -> dict:
        if system not in SYSTEMS:
            raise ValueError("unknown system")
        workflow = _workflow(system)
        node = next((item for item in workflow.get("nodes", []) if item["id"] == node_id), None)
        if node is None:
            raise ValueError(f"node not found: {node_id}")
        snippets = []
        for source in node.get("sources", []):
            path = (ROOT / source["path"]).resolve()
            if ROOT not in path.parents or not path.is_file() or path.name in {".env", "auth.json"}:
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            start = max(1, int(source.get("line", 1)))
            end = min(len(lines), int(source.get("end_line", start)))
            snippets.append({
                "path": source["path"],
                "line": start,
                "end_line": end,
                "label": source.get("label", ""),
                "code": "\n".join(f"{n:04d} | {lines[n-1]}" for n in range(start, end + 1)),
            })
        return {"node": node, "sources": snippets}

    def chat(self, system: str, message: str, options: dict | None = None) -> dict:
        if system not in SYSTEMS:
            raise ValueError("unknown system")
        if not message.strip():
            raise ValueError("message 不能为空")
        options = options or {}
        lock = self.locks[system]
        if not lock.acquire(blocking=False):
            raise RuntimeError("这个系统正在运行，请等上一次回答结束")
        try:
            workspace = self.workspaces[system]
            prompt = _task_with_history(self.history[system], message.strip())
            plugins = (ROOT / "examples" / "plugins",) if options.get("plugins") else ()
            enable_multi = bool(options.get("multi_agent"))
            enable_mcp = bool(options.get("mcp"))
            approval = str(options.get("approval_mode", "auto"))
            engine = str(options.get("engine", "langgraph"))
            permission = str(options.get("permission_mode", "acceptEdits"))
            fault_mode = str(options.get("fault_mode", "none"))

            if system == "codex":
                from mini_codex.config import HarnessConfig
                from mini_codex.harness import MiniCodexHarness

                result = MiniCodexHarness(HarnessConfig(
                    workspace=workspace,
                    max_steps=8,
                    console=False,
                    enable_multi_agent=enable_multi,
                    enable_mcp=enable_mcp,
                    plugin_dirs=plugins,
                    approval_mode=approval,
                    engine=engine,
                )).run(prompt)
            elif system == "claude":
                from claude_harness.config import ClaudeHarnessConfig
                from claude_harness.harness import ClaudeHarness

                result = ClaudeHarness(ClaudeHarnessConfig(
                    workspace=workspace,
                    permission_mode=permission,
                    auto_approve=permission in {"acceptEdits", "bypassPermissions"},
                    max_turns=8,
                    console=False,
                    enable_mcp=enable_mcp,
                    plugin_dirs=plugins,
                )).run(prompt)
            elif system == "deepseek":
                from deepseek_harness.config import DeepSeekHarnessConfig
                from deepseek_harness.harness import DeepSeekHarness

                result = DeepSeekHarness(DeepSeekHarnessConfig(
                    workspace=workspace,
                    max_steps=8,
                    console=False,
                    enable_multi_agent=enable_multi,
                    enable_mcp=enable_mcp,
                    plugin_dirs=plugins,
                    approval_mode=approval,
                    fault_mode=fault_mode,
                )).run(prompt)
            else:
                from hermes_harness.config import HermesHarnessConfig
                from hermes_harness.harness import HermesHarness

                harness = HermesHarness(HermesHarnessConfig(
                    workspace=workspace,
                    max_turns=8,
                    console=False,
                    toolsets=("hermes",),
                    plugin_dirs=plugins,
                    enable_multi_agent=enable_multi,
                    enable_mcp=enable_mcp,
                    approval_mode=approval,
                ))
                try:
                    result = harness.run(prompt)
                finally:
                    harness.close()

            answer = str(getattr(result, "final_answer", result))
            self.history[system].append(("user", message.strip()))
            self.history[system].append(("assistant", answer))
            return {
                "system": system,
                "answer": answer,
                "success": bool(getattr(result, "success", True)),
                "run_dir": str(getattr(result, "run_dir", "")),
                "errors": list(getattr(result, "errors", [])),
            }
        finally:
            lock.release()

    def reset(self, system: str) -> dict:
        if system not in SYSTEMS:
            raise ValueError("unknown system")
        self.history[system].clear()
        return {"ok": True, "system": system}

class Handler(BaseHTTPRequestHandler):
    server_version = "MiniHarnessFrontend/1.0"
    session: ChatSession | None = None

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, value: object, status: int = 200) -> None:
        self._send(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"), "application/json; charset=utf-8", status)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self._send(b"not found", "text/plain; charset=utf-8", 404)
            return
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send(path.read_bytes(), mime)

    def _body_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON body 必须是对象")
        return value

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        session = self.session
        assert session is not None
        if parsed.path == "/":
            self._file(ROOT / "frontend" / "index.html")
            return
        if parsed.path == "/favicon.ico":
            self._send(b"", "image/x-icon", 204)
            return
        if parsed.path in {"/app.js", "/styles.css"}:
            self._file(ROOT / "frontend" / parsed.path.lstrip("/"))
            return
        if parsed.path == "/api/config":
            self._json(session.config())
            return
        if parsed.path == "/diagram":
            system = (query.get("system") or ["codex"])[0]
            if system not in SYSTEMS:
                self._json({"error": "unknown system"}, 404)
                return
            self._file(ROOT / "docs" / "system-maps" / SYSTEMS[system]["diagram"])
            return
        if parsed.path == "/api/trace":
            system = (query.get("system") or ["codex"])[0]
            try:
                self._json(session.trace(system))
            except ValueError as exc:
                self._json({"error": str(exc)}, 404)
            return
        if parsed.path == "/api/node":
            system = (query.get("system") or ["codex"])[0]
            node = (query.get("node") or [""])[0]
            try:
                self._json(session.node_info(system, node))
            except ValueError as exc:
                self._json({"error": str(exc)}, 404)
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        session = self.session
        assert session is not None
        try:
            body = self._body_json()
            if parsed.path == "/api/chat":
                system = str(body.get("system", "codex"))
                message = str(body.get("message", ""))
                options = body.get("options") if isinstance(body.get("options"), dict) else {}
                self._json(session.chat(system, message, options))
                return
            if parsed.path == "/api/reset":
                self._json(session.reset(str(body.get("system", "codex"))))
                return
            self._json({"error": "not found"}, 404)
        except RuntimeError as exc:
            self._json({"error": str(exc)}, 409)
        except Exception as exc:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 400)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mini Harness Web Frontend")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--open", action="store_true", help="启动后打开浏览器")
    args = parser.parse_args()
    session = ChatSession()
    Handler.session = session

    def factory(*handler_args, **handler_kwargs):
        return Handler(*handler_args, **handler_kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), factory)
    server.daemon_threads = True
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Mini Harness Frontend: {url}")
    for key, workspace in session.workspaces.items():
        print(f"  {SYSTEMS[key]['label']}: {workspace}")
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
