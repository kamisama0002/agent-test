"""Claude-style Harness 的运行配置。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


PermissionMode = Literal[
    "default",
    "plan",
    "acceptEdits",
    "bypassPermissions",
    "dontAsk",
]


@dataclass
class ClaudeHarnessConfig:
    """一次 Claude-style queryLoop 的配置。

    permission_mode 对应 Claude Code 的权限模式：
    - default：读写都要经过权限判断；
    - plan：只允许只读探索；
    - acceptEdits：自动允许文件编辑，命令仍受安全策略；
    - bypassPermissions：全部允许（仅用于可信临时仓库）；
    - dontAsk：不能询问时，需要询问的操作直接拒绝。
    """

    workspace: Path
    permission_mode: PermissionMode = "default"
    max_turns: int = 10
    token_budget: int = 14000
    compact_threshold: int = 10000
    command_timeout: int = 60
    verify_command: str | None = None
    trace_root: Path | None = None
    console: bool = True
    auto_approve: bool = False
    enable_mcp: bool = False
    mcp_server_script: Path | None = None

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace).resolve()
        if not self.workspace.is_dir():
            raise ValueError(f"workspace 不存在或不是目录：{self.workspace}")
        if self.trace_root is None:
            self.trace_root = self.workspace / ".claude" / "runs"
        else:
            self.trace_root = Path(self.trace_root).resolve()
        if self.mcp_server_script is not None:
            self.mcp_server_script = Path(self.mcp_server_script).resolve()
        if self.compact_threshold > self.token_budget:
            raise ValueError("compact_threshold 不能大于 token_budget")
