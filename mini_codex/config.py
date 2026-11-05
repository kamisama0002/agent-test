"""Mini Codex 的运行配置。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


EngineMode = Literal["langgraph", "loop"]
ApprovalMode = Literal["auto", "ask", "deny"]


@dataclass
class HarnessConfig:
    """一个开发任务的完整运行配置。

    workspace 是唯一的文件操作根目录；所有读写都必须落在这个目录内。

    engine 默认使用 LangGraph 表达模型 ↔ 工具循环；需要对照真实 Codex
    的过程式结构时，可切换为 ``loop``。
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
    plugin_dirs: tuple[Path, ...] = ()
    approval_mode: ApprovalMode = "auto"
    engine: EngineMode = "langgraph"

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
        self.plugin_dirs = tuple(Path(item).resolve() for item in self.plugin_dirs)
        for plugin_dir in self.plugin_dirs:
            if not plugin_dir.is_dir():
                raise ValueError(f"插件目录不存在：{plugin_dir}")
        if self.approval_mode not in {"auto", "ask", "deny"}:
            raise ValueError("approval_mode 只能是 auto / ask / deny")
        if self.engine not in {"langgraph", "loop"}:
            raise ValueError("engine 只能是 langgraph / loop")
