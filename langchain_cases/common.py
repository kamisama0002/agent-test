"""所有案例共享的小工具。

这里刻意保持“薄”：只放模型构造、终端输出和消息处理，
不把业务逻辑抽象进去，保证每个 case 文件仍然可以独立阅读。
"""

from __future__ import annotations

import json
import sys
from typing import Any, Iterable

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from rich.console import Console
from rich.panel import Panel

from .config import get_settings


# Windows 控制台默认可能不是 UTF-8，统一改掉，避免中文和 Emoji 乱码。
def setup_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except ValueError:
                pass


setup_utf8()
console = Console()


def build_chat_model(**overrides: Any) -> ChatOpenAI:
    """构造指向百炼 OpenAI 兼容接口的 ChatOpenAI。

    ``ChatOpenAI`` 默认连接 OpenAI 官方地址；这里通过 ``base_url`` 指向阿里云百炼。
    只要服务端兼容 OpenAI Chat Completions 协议，LangChain 的工具调用、
    结构化输出和流式能力都可以继续复用。
    """

    settings = get_settings()
    params: dict[str, Any] = {
        "model": settings.chat_model,
        "api_key": settings.api_key,
        "base_url": settings.base_url,
        "temperature": settings.temperature,
        "max_tokens": settings.max_tokens,
        "timeout": settings.timeout,
        "max_retries": 2,
    }
    # 允许单个案例覆盖参数，例如流式案例不需要改全局配置。
    params.update(overrides)
    return ChatOpenAI(**params)


def message_text(message: BaseMessage | Any) -> str:
    """把 LangChain 消息的 content 统一转换成字符串。

    LangChain 1.x 的 content 可能是：
    - 普通字符串；
    - content blocks 列表（文本、图片、工具结果等）。
    这个函数只提取其中的文本，便于打印和测试断言。
    """

    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                # 常见文本块：{"type": "text", "text": "..."}
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
                # 推理模型的思考块：{"type": "reasoning", ...}
                elif isinstance(block.get("reasoning"), str):
                    parts.append(block["reasoning"])
        return "".join(parts)
    return str(content)


def print_message(message: BaseMessage, index: int | None = None) -> None:
    """以易读格式打印一条消息，并展示工具调用信息。"""

    prefix = f"{index:02d}. " if index is not None else ""
    role = getattr(message, "type", message.__class__.__name__)
    console.print(f"[bold cyan]{prefix}{role}[/bold cyan]")
    text = message_text(message)
    if text:
        console.print(text)

    tool_calls = getattr(message, "tool_calls", None) or []
    for call in tool_calls:
        console.print(
            f"  [yellow]→ 调用工具[/yellow] [bold]{call['name']}[/bold] "
            f"参数={json.dumps(call.get('args', {}), ensure_ascii=False)}"
        )

    # ToolMessage 里有 tool_call_id，可帮助理解“哪次工具调用返回了这条结果”。
    if getattr(message, "type", None) == "tool":
        console.print(f"  [dim]tool_call_id={getattr(message, 'tool_call_id', '-')}[/dim]")


def print_messages(messages: Iterable[BaseMessage], title: str = "消息轨迹") -> None:
    """打印完整的消息列表，是理解 Agent 内部循环最直观的方式。"""

    console.rule(f"[bold]{title}")
    for i, message in enumerate(messages, start=1):
        print_message(message, i)
        console.print()


def print_panel(title: str, body: str, border_style: str = "cyan") -> None:
    """统一的 Rich 面板输出。"""

    console.print(Panel(body, title=title, border_style=border_style, expand=False))


def json_text(value: Any) -> str:
    """中文友好的 JSON 序列化。"""

    return json.dumps(value, ensure_ascii=False, indent=2, default=str)
