"""售后工单框架对比小项目。

同一个业务问题分别用 LangChain、LangGraph、CrewAI、LlamaIndex、
OpenAI Agents SDK 实现，便于比较 API 风格、控制方式和适用场景。
"""

from .contracts import FrameworkResult

__all__ = ["FrameworkResult"]
