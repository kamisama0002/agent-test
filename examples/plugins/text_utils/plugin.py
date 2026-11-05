"""示例插件：只读文本工具。"""

from __future__ import annotations


def word_count(text: str) -> str:
    words = text.split()
    return f"words={len(words)} chars={len(text)}"


def keyword_scan(text: str, keyword: str) -> str:
    return f"keywords={keyword!r} count={text.count(keyword)}"
