"""Claude-style Harness 的本地 MCP Server。

只提供两个只读开发工具，用来演示 MCP 的动态工具发现：
- repo_stats：统计 workspace 文件；
- find_todos：搜索 TODO/FIXME。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP("claude-harness-mcp")


def _workspace() -> Path:
    return Path(os.environ.get("CLAUDE_WORKSPACE", ".")).resolve()


@mcp.tool
def repo_stats() -> dict:
    """返回 workspace 的顶层文件和常见源码文件数量。"""

    root = _workspace()
    files = [p for p in root.rglob("*") if p.is_file() and not any(
        part in {".git", ".venv", "__pycache__", "node_modules", ".claude"}
        for part in p.parts
    )]
    return {
        "workspace": str(root),
        "top_level": sorted(p.name for p in root.iterdir())[:30],
        "file_count": len(files),
        "python_files": sum(1 for p in files if p.suffix == ".py"),
        "test_files": sum(1 for p in files if "test" in p.name.lower()),
    }


@mcp.tool
def find_todos() -> str:
    """搜索 workspace 中的 TODO/FIXME 注释。"""

    root = _workspace()
    matches: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or any(
            part in {".git", ".venv", "__pycache__", "node_modules", ".claude"}
            for part in path.parts
        ):
            continue
        if path.suffix.lower() not in {".py", ".ts", ".tsx", ".js", ".md", ".rs", ".go"}:
            continue
        try:
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if re.search(r"\b(TODO|FIXME)\b", line, re.IGNORECASE):
                    matches.append(f"{path.relative_to(root)}:{number}: {line.strip()[:200]}")
        except OSError:
            continue
    return "\n".join(matches[:80]) or "No TODO/FIXME comments found."


if __name__ == "__main__":
    mcp.run(show_banner=False)
