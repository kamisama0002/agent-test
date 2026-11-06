"""DeepSeek Harness 的配置。

DeepSeek 套件和 Codex 套件共享工具/审批/插件基础设施，但单独暴露
模型名、重试次数和推理内容记录策略，便于解释推理模型的差异。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


FaultMode = Literal["none", "tool_error", "plugin_error", "model_error"]


@dataclass
class DeepSeekHarnessConfig:
    workspace: Path
    max_steps: int = 10
    token_budget: int = 12000
    compact_threshold: int = 10000
    command_timeout: int = 60
    verify_command: str | None = None
    trace_root: Path | None = None
    console: bool = True
    model_name: str | None = None
    reasoning_effort: str | None = None
    max_model_retries: int = 5
    retry_initial_delay_ms: int = 500
    retry_max_delay_ms: int = 10000
    retry_jitter_ratio: float = 0.1
    enable_multi_agent: bool = False
    enable_mcp: bool = False
    mcp_server_script: Path | None = None
    plugin_dirs: tuple[Path, ...] = ()
    approval_mode: Literal["auto", "ask", "deny"] = "auto"
    fault_mode: FaultMode = "none"

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace).resolve()
        if not self.workspace.is_dir():
            raise ValueError(f"workspace 不存在或不是目录：{self.workspace}")
        if self.max_steps < 1:
            raise ValueError("max_steps 必须 >= 1")
        if self.token_budget < 1000:
            raise ValueError("token_budget 太小")
        if self.compact_threshold > self.token_budget:
            raise ValueError("compact_threshold 不能大于 token_budget")
        if self.max_model_retries < 0:
            raise ValueError("max_model_retries 不能为负数")
        if self.retry_initial_delay_ms < 0 or self.retry_max_delay_ms < 0:
            raise ValueError("retry delay 不能为负数")
        if not 0 <= self.retry_jitter_ratio <= 1:
            raise ValueError("retry_jitter_ratio 必须在 0 到 1 之间")
        if self.trace_root is None:
            self.trace_root = self.workspace / ".deepseek" / "runs"
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
        if self.fault_mode not in {"none", "tool_error", "plugin_error", "model_error"}:
            raise ValueError("fault_mode 不受支持")
