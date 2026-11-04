"""跨框架统一结果结构。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FrameworkResult:
    """所有框架最终都转换成一个统一结果，方便并排比较。"""

    framework: str
    answer: str
    elapsed_ms: float
    strategy: str
    trace: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
