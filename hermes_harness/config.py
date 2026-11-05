"""Hermes-style Harness 的配置。

这个配置刻意只覆盖“通用 Agent + 持续学习”最小闭环：

- workspace：普通任务可读写的目录；
- hermes_home：MEMORY.md、USER.md、skills、sessions、运行记录；
- toolsets：决定本次模型能看到哪些工具；
- background_review：每轮结束后是否让独立模型复盘并写入持久层。

源码对照：Hermes 的 run_agent.py、toolsets.py、agent/background_review.py。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass
class HermesHarnessConfig:
    """一次 Hermes mini 会话的运行配置。"""

    workspace: Path
    hermes_home: Path | None = None
    max_turns: int = 8
    token_budget: int = 14000
    compact_threshold: int = 10000
    command_timeout: int = 60
    verify_command: str | None = None
    trace_root: Path | None = None
    console: bool = True
    toolsets: tuple[str, ...] = ("hermes",)
    enable_background_review: bool = True
    background_review_async: bool = False
    review_max_turns: int = 6
    enable_multi_agent: bool = False
    enable_mcp: bool = False
    mcp_server_script: Path | None = None
    plugin_dirs: tuple[Path, ...] = ()
    approval_mode: Literal["auto", "ask", "deny"] = "auto"

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace).resolve()
        if not self.workspace.is_dir():
            raise ValueError(f"workspace 不存在或不是目录：{self.workspace}")

        if self.hermes_home is None:
            self.hermes_home = self.workspace / ".hermes"
        else:
            self.hermes_home = Path(self.hermes_home).resolve()
        self.hermes_home.mkdir(parents=True, exist_ok=True)

        if self.trace_root is None:
            self.trace_root = self.hermes_home / "runs"
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

        # 约定目录和 Hermes 源码一致：记忆、技能、会话、运行记录彼此隔离。
        for name in ("memories", "skills", "sessions", "runs"):
            (self.hermes_home / name).mkdir(parents=True, exist_ok=True)

        if self.max_turns < 1:
            raise ValueError("max_turns 必须 >= 1")
        if self.token_budget < 1000:
            raise ValueError("token_budget 太小")
        if self.compact_threshold > self.token_budget:
            raise ValueError("compact_threshold 不能大于 token_budget")
        if not self.toolsets:
            raise ValueError("至少启用一个 toolset")
