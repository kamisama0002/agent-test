"""本地哈希向量，避免依赖当前账号没有权限的 Embedding API。

它只适合演示检索流程。生产环境应替换成真实 embedding 模型。
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import List

from llama_index.core.embeddings import BaseEmbedding


def hash_vector(text: str, dimensions: int = 512) -> list[float]:
    english = re.compile(r"[a-zA-Z0-9_]+")
    chinese = re.compile(r"[\u4e00-\u9fff]+")
    lowered = text.lower()

    tokens = english.findall(lowered)
    for run in chinese.findall(lowered):
        tokens.extend(run)
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))

    vector = [0.0] * dimensions
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1

    for token, count in counts.items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign * count

    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


class HashingLlamaEmbedding(BaseEmbedding):
    """把本地哈希向量接入 LlamaIndex 的 BaseEmbedding 接口。"""

    def _get_query_embedding(self, query: str) -> List[float]:
        return hash_vector(query)

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return hash_vector(query)

    def _get_text_embedding(self, text: str) -> List[float]:
        return hash_vector(text)

    async def _aget_text_embedding(self, text: str) -> List[float]:
        return hash_vector(text)

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return [hash_vector(text) for text in texts]
