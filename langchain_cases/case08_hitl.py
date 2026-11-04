"""案例 08：Human-in-the-loop（人在环路）。

对应官方文档：
- Human-in-the-loop: https://docs.langchain.com/oss/python/langchain/human-in-the-loop

流程：
1. Agent 决定调用敏感工具 send_email；
2. HumanInTheLoopMiddleware 在真正执行前触发 interrupt；
3. 外部程序读取待审批动作；
4. 审批后用 Command(resume=...) 恢复执行。

本案例为了自动化演示，程序会“模拟”审批人直接 approve。
真实应用中应把 interrupt.value 展示给人，再根据人工选择 approve/reject/edit/respond。
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from .common import build_chat_model, console, message_text, print_panel


# 用一个列表模拟“发送记录”，便于证明工具确实只在审批后执行。
SENT_EMAILS: list[dict[str, str]] = []


@tool
def send_email(to: str, subject: str, body: str) -> str:
    """向指定收件人发送邮件。属于有外部副作用的敏感操作，需要人工审批。"""

    SENT_EMAILS.append({"to": to, "subject": subject, "body": body})
    return f"邮件已发送给 {to}，主题：{subject}"


def _messages_from_output(output):
    """兼容 GraphOutput 与普通 dict 两种返回形态。"""

    value = getattr(output, "value", output)
    return value["messages"]


def run() -> None:
    agent = create_agent(
        model=build_chat_model(),
        tools=[send_email],
        system_prompt="用户要求发邮件时必须调用 send_email 工具，不要假装已经发送。",
        middleware=[
            HumanInTheLoopMiddleware(
                interrupt_on={
                    # True 表示允许 approve / edit / reject / respond 全部决策。
                    "send_email": True,
                },
                description_prefix="邮件发送需要人工审批",
            )
        ],
        # HITL 必须配 checkpointer：中断后要能恢复同一段图状态。
        checkpointer=InMemorySaver(),
    )

    config = {"configurable": {"thread_id": "hitl-demo-001"}}
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "请给 alice@example.com 发送邮件，主题是“项目进度”，正文写“本周已完成 LangChain 示例”。",
                }
            ]
        },
        config=config,
        version="v2",
    )

    interrupts = getattr(result, "interrupts", []) or []
    if not interrupts:
        raise RuntimeError("模型没有触发预期的人工审批中断。")

    console.print("[bold yellow]检测到待审批动作：[/bold yellow]")
    decisions: list[dict[str, str]] = []
    for interrupt in interrupts:
        # LangChain 1.4 的默认 batched 模式把待审批动作放在 action_requests 中。
        # 一次模型回合如果产生多个敏感工具调用，会按顺序排列。
        for request in interrupt.value.get("action_requests", []):
            console.print(
                f"  - 工具={request.get('name')}，参数={request.get('args')}，"
                f"interrupt_id={interrupt.id}"
            )
            # 自动演示：按顺序全部批准。真实系统在这里接收用户点击结果。
            decisions.append({"type": "approve"})

    console.print(f"\n审批前已发送邮件数：{len(SENT_EMAILS)}（应为 0）")

    # 默认 batched 模式的恢复格式是 {"decisions": [...]}，顺序与 action_requests 一致。
    resumed = agent.invoke(Command(resume={"decisions": decisions}), config=config, version="v2")

    print_panel("审批后的最终回答", message_text(_messages_from_output(resumed)[-1]), border_style="green")
    console.print(f"审批后已发送邮件数：{len(SENT_EMAILS)}（应为 1）")


if __name__ == "__main__":
    run()
