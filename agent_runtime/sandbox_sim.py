"""固定、可观测的 Sandbox 生命周期模拟器。

不创建真实容器、进程或内核沙箱，只把上游源码里的 Sandbox 生命周期
记录成事件，方便本地学习和前端逐步查看。

源码参考：
- Codex: codex-rs/protocol/src/protocol.rs::SandboxPolicy；codex-rs/core/src/sandboxing/
- Claude Code: restored-src/src/utils/sandbox/sandbox-adapter.ts::SandboxManager
- Hermes: tools/environments/ 的本地/Docker/远程环境选择
- DeepSeek: packages/sandbox/sandbox/src/index.ts::SandboxPolicy；
  packages/sandbox/sandbox-local/src/index.ts；
  packages/sandbox/sandbox-windows-acl/src/index.ts
"""

from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SandboxProfile:
    system: str
    mode: str
    backend: str
    writable_roots: list[str]
    network_access: bool
    enforcement: str
    source_refs: list[str]


_PROFILES = {
    "codex": {
        "backend": "windows-sandbox" if platform.system() == "Windows" else "landlock/bwrap",
        "source_refs": [
            "codex-rs/protocol/src/protocol.rs::SandboxPolicy",
            "codex-rs/core/src/sandboxing/",
        ],
    },
    "claude": {
        "backend": "sandbox-manager-adapter",
        "source_refs": [
            "restored-src/src/utils/sandbox/sandbox-adapter.ts::SandboxManager",
            "restored-src/src/entrypoints/sandboxTypes.ts",
        ],
    },
    "hermes": {
        "backend": "local-subprocess-or-docker-adapter",
        "source_refs": [
            "tools/environments/",
            "toolsets.py",
        ],
    },
    "deepseek": {
        "backend": "dsh-sandbox-local",
        "source_refs": [
            "packages/sandbox/sandbox/src/index.ts::SandboxPolicy",
            "packages/sandbox/sandbox-local/src/index.ts",
            "packages/sandbox/sandbox-windows-acl/src/index.ts",
        ],
    },
}


class SandboxSimulator:
    """只记录 sandbox 日志，不启动真实 sandbox。"""

    def __init__(self, system: str, *, mode: str = "workspace-write") -> None:
        if system not in _PROFILES:
            raise ValueError(f"unknown sandbox system: {system}")
        self.system = system
        self.mode = mode
        self.active = False
        self.events: list[str] = []

    def _emit(self, bus: Any, event: str, message: str, **data: Any) -> None:
        self.events.append(event)
        bus.emit(event, "sandbox", message, simulated=True, system=self.system, **data)

    def start(
        self,
        bus: Any,
        *,
        workspace: Path,
        approval_mode: str = "auto",
        network_access: bool = False,
    ) -> SandboxProfile:
        config = _PROFILES[self.system]
        backend = str(config["backend"])
        writable = [str(workspace)]
        profile = SandboxProfile(
            system=self.system,
            mode=self.mode,
            backend=backend,
            writable_roots=writable,
            network_access=network_access,
            enforcement="simulated",
            source_refs=list(config["source_refs"]),
        )
        self.active = True
        self._emit(bus, "sandbox/requested", "sandbox start requested", mode=self.mode)
        self._emit(
            bus,
            "sandbox/backend_selected",
            f"selected simulated backend: {backend}",
            backend=backend,
            platform=platform.system(),
            available=bool(shutil.which("docker")) if self.system == "hermes" else None,
        )
        self._emit(
            bus,
            "sandbox/policy_applied",
            f"policy applied: {self.mode}",
            mode=self.mode,
            approval_mode=approval_mode,
            writable_roots=writable,
            network_access=network_access,
            enforcement="simulated",
            source_refs=profile.source_refs,
        )
        self._emit(
            bus,
            "sandbox/mounts_prepared",
            "workspace mount prepared",
            writable_roots=writable,
        )
        self._emit(
            bus,
            "sandbox/started",
            "sandbox simulated as started (no real process/container)",
            backend=backend,
            mode=self.mode,
            enforcement="simulated",
        )
        return profile

    def wrap_command(self, bus: Any, command: str) -> str:
        """模拟上游对命令的 sandbox 包装，不改变真实命令。"""

        if not self.active:
            return command
        wrapped = f"[simulated {self.system} sandbox] {command}"
        self._emit(bus, "sandbox/exec_wrapped", "command wrapped by sandbox policy", command=command, wrapped=wrapped)
        return wrapped

    def stop(self, bus: Any, *, reason: str = "run_finished") -> None:
        if not self.active:
            return
        self._emit(bus, "sandbox/stop_requested", "sandbox stop requested", reason=reason)
        self.active = False
        self._emit(bus, "sandbox/stopped", "sandbox simulated as stopped", reason=reason)


def sandbox_mode_for_approval(approval_mode: str) -> str:
    return "read-only" if approval_mode == "deny" else "workspace-write"


def sandbox_mode_for_permission(permission_mode: str) -> str:
    return "read-only" if permission_mode == "plan" else "workspace-write"
