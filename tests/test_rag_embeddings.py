"""本地哈希向量与 URL 配置的确定性测试。"""

from __future__ import annotations

import math

from langchain_cases.case05_rag import HashingEmbeddings
from langchain_cases.config import _normalize_base_url


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def test_hashing_embeddings_prefers_related_text() -> None:
    embeddings = HashingEmbeddings()
    query = embeddings.embed_query("LangChain Agent 工具")
    related = embeddings.embed_query("LangChain Agent 如何调用工具")
    unrelated = embeddings.embed_query("今天北京天气和空气质量")

    assert math.isclose(cosine(query, query), 1.0, rel_tol=1e-9)
    assert cosine(query, related) > cosine(query, unrelated)


def test_normalize_base_url() -> None:
    assert (
        _normalize_base_url("llm.example.com")
        == "https://llm.example.com/compatible-mode/v1"
    )
    assert (
        _normalize_base_url("https://llm.example.com/compatible-mode/v1/")
        == "https://llm.example.com/compatible-mode/v1"
    )
