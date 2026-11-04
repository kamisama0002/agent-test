"""案例 03：工具定义与 Agent 工具调用循环。

对应官方文档：
- Tools: https://docs.langchain.com/oss/python/langchain/tools
- Agents: https://docs.langchain.com/oss/python/langchain/agents

关键点：
1. ``@tool`` 会把 Python 函数名、类型标注和 docstring 转成模型可见的工具 Schema；
2. ``create_agent`` 返回一个“模型 → 工具 → 模型”的循环图；
3. 工具结果是 ToolMessage，会被自动追加到上下文，模型据此生成最终答案。
"""

from __future__ import annotations

from langchain.agents import create_agent
from langchain.tools import tool

from .common import build_chat_model, console, message_text, print_messages, print_panel


@tool
def query_order(order_id: str) -> dict:
    """根据订单号查询订单状态、金额和预计送达时间。"""

    # 用固定数据模拟数据库/订单服务，保证示例可重复运行。
    orders = {
        "A1001": {"status": "已发货", "amount": 299.0, "eta": "2026-11-06"},
        "B2002": {"status": "待付款", "amount": 89.5, "eta": "付款后 48 小时"},
    }
    return orders.get(order_id.upper(), {"error": f"未找到订单 {order_id}"})


@tool
def estimate_shipping(weight_kg: float, destination: str) -> dict:
    """根据重量（公斤）和目的城市估算运费，首重 12 元，续重每公斤 5 元。"""

    if weight_kg <= 0:
        raise ValueError("重量必须大于 0")
    price = 12 + max(0.0, weight_kg - 1) * 5
    return {
        "destination": destination,
        "weight_kg": weight_kg,
        "shipping_fee": round(price, 2),
        "currency": "CNY",
    }


def run() -> None:
    model = build_chat_model()

    agent = create_agent(
        model=model,
        tools=[query_order, estimate_shipping],
        # system_prompt 不是“可有可无的礼貌用语”，它会显著影响工具选择与回答边界。
        system_prompt=(
            "你是电商客服。涉及订单或运费时必须调用工具，不要凭记忆编造。"
            "回答使用中文，并说明你查到了什么。"
        ),
    )

    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "帮我查订单 A1001 的状态，再估算 2.5 公斤寄到北京的运费。",
                }
            ]
        }
    )

    # 打印完整轨迹能清楚看到：
    # HumanMessage → AIMessage(tool_calls) → ToolMessage → AIMessage(最终答案)
    print_messages(result["messages"], "Agent 工具调用轨迹")
    print_panel("最终回答", message_text(result["messages"][-1]), border_style="green")

    console.print(
        "\n[dim]注意：工具 docstring 越清楚，模型越不容易传错参数。"
        "生产环境还应在工具内部做鉴权、超时、幂等与输入校验。[/dim]"
    )


if __name__ == "__main__":
    run()
