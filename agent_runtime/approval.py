"""共享审批策略。

生产 Harness 的审批通常是 sandbox / policy / UI 三者的组合。这里做一个
可教学的最小版本：

- read_only 工具自动允许；
- mode=auto 自动允许（默认，保持旧 demo 可跑）；
- mode=ask 调用可选 approval_callback，否则拒绝并说明需要人工；
- mode=deny 拒绝所有写入/执行类操作。

真正的交互式审批应该由 app-server 或 CLI 的 request_user_input 提供，
不要让后台 review 或子 Agent 静默绕过去。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

ApprovalMode = Literal["auto", "ask", "deny"]


@dataclass(frozen=True)
class ApprovalDecision:
    allowed: bool
    reason: str
    behavior: str


class ApprovalManager:
    def __init__(
        self,
        mode: ApprovalMode = "auto",
        *,
        approval_callback: Callable[[str, dict], bool] | None = None,
    ) -> None:
        if mode not in {"auto", "ask", "deny"}:
            raise ValueError("approval mode 只能是 auto / ask / deny")
        self.mode = mode
        self.approval_callback = approval_callback

    def decide(
        self,
        tool_name: str,
        args: dict,
        *,
        read_only: bool = False,
        destructive: bool = False,
    ) -> ApprovalDecision:
        if read_only:
            return ApprovalDecision(True, "read-only tool", "allow")
        if self.mode == "auto":
            return ApprovalDecision(True, "auto approval mode", "allow")
        if self.mode == "deny":
            return ApprovalDecision(False, "approval mode denies side effects", "deny")
        if self.approval_callback is not None:
            approved = bool(self.approval_callback(tool_name, args))
            return ApprovalDecision(
                approved,
                "approved by callback" if approved else "rejected by callback",
                "allow" if approved else "deny",
            )
        return ApprovalDecision(False, f"{tool_name} requires human approval", "ask")
