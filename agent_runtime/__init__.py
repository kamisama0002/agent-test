"""可复用的 Agent runtime 组件：多 Agent、审批、插件、LangGraph 工具循环。"""

from .approval import ApprovalDecision, ApprovalManager, ApprovalMode
from .plugins import LoadedPlugin, PluginRegistry, PluginToolSpec
from .runtime import AgentRecord, SubagentRuntime
from .tool_loop import LangGraphToolLoop, ToolLoopResult

__all__ = [
    "AgentRecord",
    "ApprovalDecision",
    "ApprovalManager",
    "ApprovalMode",
    "LangGraphToolLoop",
    "LoadedPlugin",
    "PluginRegistry",
    "PluginToolSpec",
    "SubagentRuntime",
    "ToolLoopResult",
]
