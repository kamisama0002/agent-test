"""Mini Codex 的运行配置。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class HarnessConfig:
    """一个开发任务的完整运行配置。

    workspace 是唯一的文件操作根目录；所有读写都必须落在这个目录内。
    """

    workspace: Path
    max_steps: int = 10
    token_budget: int = 12000
    command_timeout: int = 60
    verify_command: str | None = None
    trace_root: Path | None = None
    console: bool = True
    enable_multi_agent: bool = False
    enable_mcp: bool = False
    mcp_server_script: Path | None = None

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace).resolve()
        if not self.workspace.exists() or not self.workspace.is_dir():
            raise ValueError(f"workspace 不存在或不是目录：{self.workspace}")
        if self.trace_root is None:
            self.trace_root = self.workspace / ".mini_codex" / "runs"
        else:
            self.trace_root = Path(self.trace_root).resolve()
        if self.mcp_server_script is not None:
            self.mcp_server_script = Path(self.mcp_server_script).resolve()
