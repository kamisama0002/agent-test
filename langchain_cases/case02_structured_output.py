"""案例 02：结构化输出。

对应官方文档：
- Structured output: https://docs.langchain.com/oss/python/langchain/structured-output

目标：让模型不要返回一段自由文本，而是返回可被程序直接消费的 Pydantic 对象。

说明：当前百炼网关不支持 OpenAI 的 json_schema 响应格式，因此这里显式使用
``method="function_calling"``。LangChain 会把 Pydantic Schema 转成工具描述，
模型调用该“结构化输出工具”，最终由 LangChain 校验并构造对象。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .common import build_chat_model, console, json_text, print_panel


class BookCard(BaseModel):
    """一本书的结构化信息卡。字段描述会进入模型可见的 JSON Schema。"""

    title: str = Field(description="书名")
    author: str = Field(description="作者")
    genre: Literal["科幻", "技术", "历史", "文学", "其他"] = Field(description="图书分类")
    rating: float = Field(ge=0, le=5, description="0 到 5 分的推荐指数")
    keywords: list[str] = Field(min_length=1, max_length=5, description="3 个左右关键词")
    one_sentence: str = Field(description="一句话书评")


def run() -> None:
    model = build_chat_model()

    # 方式 A：with_structured_output 是“模型级”结构化输出，适合单次抽取。
    structured_model = model.with_structured_output(BookCard, method="function_calling")

    source_text = """
    《设计数据密集型应用》由 Martin Kleppmann 撰写。它系统讨论了可靠性、
    可扩展性、可维护性，以及数据库、分布式系统和数据流架构。内容偏工程实践，
    适合后端工程师和架构师，推荐指数 4.8。
    """

    card = structured_model.invoke(
        f"请从下面的文字中提取图书信息，并给出简洁的一句话书评：\n{source_text}"
    )

    # card 已经是 BookCard 实例，不再是字符串。字段错误会在解析阶段直接暴露。
    assert isinstance(card, BookCard)
    print_panel("Pydantic 结构化结果", json_text(card.model_dump()), border_style="green")

    console.print("[dim]提示：把生成结果直接保存到数据库、调用下游 API 或做规则校验时，"
                  "结构化输出比正则解析自由文本可靠得多。[/dim]")
    console.print("[dim]若供应商原生支持 json_schema，可省略 method，让 LangChain 自动选择 ProviderStrategy。[/dim]")


if __name__ == "__main__":
    run()
