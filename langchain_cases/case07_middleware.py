"""案例 07：Middleware（中间件）。

对应官方文档：
- Middleware overview: https://docs.langchain.com/oss/python/langchain/middleware/overview
- Prebuilt middleware: https://docs.langchain.com/oss/python/langchain/middleware/built-in
- Custom middleware: https://docs.langchain.com/oss/python/langchain/middleware/custom

中间件不是独立运行时，它挂在 create_agent 返回的 LangGraph 上。
本案例组合两类能力：
- 自定义 TimingMiddleware：在每次模型调用前后统计耗时；
- 内置 ModelCallLimitMiddleware：限制一次运行最多调用几次模型，防止失控循环。
"""

from __future__ import annotations

import time
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, AgentState, ModelCallLimitMiddleware
from langchain.tools import tool

from .common import build_chat_model, console, message_text, print_panel


class TimingMiddleware(AgentMiddleware):
    """在每次模型调用前后记录耗时。"""

    def __init__(self) -> None:
        super().__init__()
        self._started_at: float | None = None
        self.model_calls = 0

    def before_model(self, state: AgentState, runtime: Any) -> dict[str, Any] | None:
        # 返回 None 表示不修改 Agent 状态，只做旁路观测。
        self._started_at = time.perf_counter()
        return None

    def after_model(self, state: AgentState, runtime: Any) -> dict[str, Any] | None:
        elapsed = time.perf_counter() - self._started_at if self._started_at else 0.0
        self.model_calls += 1
        console.print(f"[dim]  [middleware] 第 {self.model_calls} 次模型调用耗时 {elapsed:.2f}s[/dim]")
        return None


@tool
def convert_currency(amount: float, rate: float) -> dict:
    """按给定汇率把金额换算成目标币种。"""

    return {"amount": amount, "rate": rate, "converted": round(amount * rate, 2)}


def run() -> None:
    timing = TimingMiddleware()
    agent = create_agent(
        model=build_chat_model(),
        tools=[convert_currency],
        system_prompt="涉及金额换算时调用工具。",
        middleware=[
            timing,
            # 一次 Agent run 最多允许 4 次模型调用；超限时优雅结束。
            ModelCallLimitMiddleware(run_limit=4, exit_behavior="end"),
        ],
    )

    result = agent.invoke(
        {
            "messages": [
                {"role": "user", "content": "1000 美元按 7.18 的汇率换成人民币是多少？请调用工具。"}
            ]
        }
    )

    print_panel("最终回答", message_text(result["messages"][-1]), border_style="green")
    console.print(f"\n[dim]总共观测到 {timing.model_calls} 次模型调用。"
                  "中间件适合放日志、重试、回退、限流、审批等横切逻辑。[/dim]")


if __name__ == "__main__":
    run()
