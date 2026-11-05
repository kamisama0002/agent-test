"""本地实时查看 Harness 运行轨迹的轻量服务器。

用法（示例）：

    uv run python docs/system-maps/live_viewer.py `
      --system hermes_harness `
      --run-dir "$env:TEMP/hermes_harness_demo/.hermes/runs/<timestamp>" `
      --open

它只读取指定 run 目录下的 events.jsonl，以及本目录中的 Archify HTML；
不读取 .env、不会把 API Key 发到浏览器。
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from trace_to_map import STAGE_TO_NODE, map_event


BASE_DIR = Path(__file__).resolve().parent
DIAGRAM_FILES = {
    "mini_codex": "mini-codex.html",
    "claude_harness": "claude-harness.html",
    "hermes_harness": "hermes-harness.html",
}


class TraceState:
    def __init__(self, run_dir: Path, system: str) -> None:
        self.run_dir = run_dir.resolve()
        self.system = system
        self.lock = threading.Lock()
        self.cache: list[dict] = []
        self.offset = 0

    def refresh(self) -> list[dict]:
        """增量读取 events.jsonl，避免每次轮询重扫整个文件。"""

        with self.lock:
            path = self.run_dir / "events.jsonl"
            if not path.exists():
                return list(self.cache)
            with path.open("r", encoding="utf-8", errors="replace") as file:
                file.seek(self.offset)
                for line in file:
                    if not line.strip():
                        continue
                    try:
                        self.cache.append(map_event(self.system, json.loads(line)))
                    except json.JSONDecodeError:
                        continue
                self.offset = file.tell()
            return list(self.cache)

    def snapshot(self) -> dict:
        rows = self.refresh()
        return {
            "system": self.system,
            "run_dir": str(self.run_dir),
            "events": rows,
            "count": len(rows),
            "mapping": STAGE_TO_NODE.get(self.system, {}),
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "HermesTraceViewer/1.0"

    def __init__(self, *args, state: TraceState | None = None, **kwargs):
        self.state = state
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.is_file():
            self._send_bytes(b"not found", "text/plain; charset=utf-8", 404)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send_bytes(path.read_bytes(), content_type)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/trace":
            assert self.state is not None
            body = json.dumps(self.state.snapshot(), ensure_ascii=False, indent=2).encode("utf-8")
            self._send_bytes(body, "application/json; charset=utf-8")
            return
        if parsed.path in {"/", "/live"}:
            self._send_file(BASE_DIR / "live_view.html")
            return
        if parsed.path == "/diagram":
            assert self.state is not None
            self._send_file(BASE_DIR / DIAGRAM_FILES.get(self.state.system, f"{self.state.system}.html"))
            return
        relative = parsed.path.lstrip("/")
        target = (BASE_DIR / relative).resolve()
        if BASE_DIR not in target.parents and target != BASE_DIR:
            self._send_bytes(b"forbidden", "text/plain; charset=utf-8", 403)
            return
        self._send_file(target)


def latest_run_dir(workspace: Path, system: str) -> Path:
    roots = {
        "mini_codex": workspace / ".mini_codex" / "runs",
        "claude_harness": workspace / ".claude" / "runs",
        "hermes_harness": workspace / ".hermes" / "runs",
    }
    root = roots.get(system)
    if root is None or not root.is_dir():
        raise SystemExit(f"找不到 {system} 的运行目录，请显式传 --run-dir")
    runs = [item for item in root.iterdir() if (item / "events.jsonl").is_file()]
    if not runs:
        raise SystemExit(f"{root} 里还没有 events.jsonl")
    return max(runs, key=lambda item: item.stat().st_mtime)


def main() -> int:
    parser = argparse.ArgumentParser(description="Harness 实时轨迹可视化")
    parser.add_argument("--run-dir", default=None, help="包含 events.jsonl 的运行目录")
    parser.add_argument("--workspace", default=".", help="未传 --run-dir 时，自动寻找该工作区最新运行")
    parser.add_argument("--system", choices=sorted(STAGE_TO_NODE), default="hermes_harness")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="启动后打开浏览器")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir(Path(args.workspace).resolve(), args.system)
    if not run_dir.is_dir():
        raise SystemExit(f"run-dir 不存在：{run_dir}")
    state = TraceState(run_dir, args.system)

    def handler_factory(*handler_args, **handler_kwargs):
        return Handler(*handler_args, state=state, **handler_kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_factory)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"live viewer: {url}")
    print(f"run dir: {run_dir}")
    print(f"system: {args.system}")
    if args.open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    time.sleep(0)
    raise SystemExit(main())
