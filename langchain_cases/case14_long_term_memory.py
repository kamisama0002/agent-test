"""案例 14：长期记忆（Long-term Memory）。

对应官方文档：
- Long-term memory: https://docs.langchain.com/oss/python/langchain/long-term-memory

短期记忆按 thread_id 隔离；长期记忆存放在 LangGraph Store 中，可跨 thread 读取。
本案例预置一个用户画像，再让 Agent 通过工具读取：
- namespace = ("users",)
- key = "u-1001"
- value = {"name": ..., "language": ..., "preferences": ...}

生产中可把 InMemoryStore 换成 Postgres/Redis/Mongo 等持久化 Store。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from langchain.agents import create_agent
from langchain.tools import ToolRuntime, tool
from langgraph.store.memory import InMemoryStore

from .common import build_chat_model, console, message_text, print_panel


@dataclass
class UserContext:
    """每次请求由上层应用注入的可信用户身份。"""

    user_id: str


def run() -> None:
    store = InMemoryStore()

    # 写入长期记忆：同一用户下次打开页面、甚至换一个 thread，仍可读取。
    store.put(
        ("users",),
        "u-1001",
        {
            "name": "林舟",
            "language": "中文",
            "preferences": ["回答简洁", "喜欢先看结论", "示例优先使用 Python"],
        },
    )

    @tool
    def get_user_profile(runtime: ToolRuntime[UserContext]) -> str:
        """读取当前用户的长期画像，包括姓名、语言和偏好。"""

        assert runtime.store is not None
        user_id = runtime.context.user_id
        item = runtime.store.get(("users",), user_id)
        if item is None:
            return "未找到用户画像"
        return json.dumps(item.value, ensure_ascii=False)

    agent = create_agent(
        model=build_chat_model(),
        tools=[get_user_profile],
        system_prompt=(
            "你是个人学习助手。回答前先读取用户画像，并严格遵循用户偏好。"
            "不要猜测用户身份。"
        ),
        store=store,
        context_schema=UserContext,
    )

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "给我一个学习 LangChain 的建议。"}]},
        # context 不是给模型看的文本，而是运行时传给工具的强类型上下文。
        context=UserContext(user_id="u-1001"),
    )

    print_panel("带长期记忆的回答", message_text(result["messages"][-1]), border_style="green")
    console.print("\n[dim]安全提醒：namespace/key 必须由服务端根据登录身份生成，"
                  "不要让模型自由指定 user_id，否则可能越权读取他人记忆。[/dim]")


if __name__ == "__main__":
    run()
