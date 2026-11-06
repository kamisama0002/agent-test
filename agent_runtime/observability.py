"""运行时可观测性辅助函数。

Harness 的事件流既要给人看，也要能被前端稳定渲染。这里刻意只做
“JSON 安全的结构化快照”，不读取环境变量、不读取 .env，也不把
凭据类文件写进事件。
"""

from __future__ import annotations

from typing import Any, Iterable


def serialize_messages(messages: Iterable[Any]) -> list[dict[str, Any]]:
    """把 LangChain Message 转成可写入 events.jsonl 的轻量快照。

    只保留角色、正文和工具调用骨架。它不是模型的完整序列化协议，
    目的是让学习页面能看清“这一轮到底把哪些内容交给了模型”。
    """

    rows: list[dict[str, Any]] = []
    for message in messages:
        row: dict[str, Any] = {
            "role": str(getattr(message, "type", type(message).__name__)),
            "content": getattr(message, "content", ""),
        }
        name = getattr(message, "name", None)
        if name:
            row["name"] = name
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            row["tool_calls"] = tool_calls
        rows.append(row)
    return rows
