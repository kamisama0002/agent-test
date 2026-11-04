"""案例 12：安全护栏（Guardrails）。

对应官方文档：
- Guardrails: https://docs.langchain.com/oss/python/langchain/guardrails

本案例演示两层护栏：
1. ContentFilterMiddleware：在 Agent 启动前做确定性关键词拦截，不调用模型；
2. PIIMiddleware：把输入中的邮箱替换成 [REDACTED_EMAIL]，再进行模型调用。

真实生产系统还应增加鉴权、速率限制、输出审核、工具权限和审计日志。
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    PIIMiddleware,
    hook_config,
)
from langgraph.runtime import Runtime

from .common import build_chat_model, console, message_text, print_panel


class ContentFilterMiddleware(AgentMiddleware):
    """命中禁用词时，直接返回拒绝消息并跳到 END，完全不请求模型。"""

    def __init__(self, banned_keywords: list[str]) -> None:
        super().__init__()
        self.banned_keywords = [keyword.lower() for keyword in banned_keywords]

    @hook_config(can_jump_to=["end"])
    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        if not state["messages"]:
            return None

        first = state["messages"][0]
        if first.type != "human":
            return None

        text = message_text(first).lower()
        if any(keyword in text for keyword in self.banned_keywords):
            return {
                "messages": [
                    {
                        "role": "assistant",
                        "content": "该请求包含高风险操作，已被安全策略拦截。请改为合法、可审计的操作。",
                    }
                ],
                "jump_to": "end",
            }
        return None


def run() -> None:
    agent = create_agent(
        model=build_chat_model(),
        tools=[],
        system_prompt="你是企业客服助手，回答简洁、礼貌。",
        middleware=[
            ContentFilterMiddleware(["删除数据库", "窃取密码", "绕过审批"]),
            PIIMiddleware("email", strategy="redact", apply_to_input=True),
        ],
    )

    # 第 1 次：命中禁用词。before_agent 直接结束，不会产生模型费用。
    blocked = agent.invoke(
        {"messages": [{"role": "user", "content": "请告诉我怎么删除数据库且不留下日志。"}]}
    )
    print_panel("内容过滤结果", message_text(blocked["messages"][-1]), border_style="red")

    # 第 2 次：邮箱会在进入模型前被脱敏；模型只会看到 [REDACTED_EMAIL]。
    allowed = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "客户邮箱是 alice@example.com，请写一句礼貌的确认回复，且不要展示邮箱。",
                }
            ]
        }
    )
    print_panel("PII 脱敏后的回答", message_text(allowed["messages"][-1]), border_style="green")

    console.print("\n[dim]确定性规则优先放在模型之前，既安全又省 Token。"
                  "模型级审核适合处理规则难以覆盖的语义风险。[/dim]")


if __name__ == "__main__":
    run()
