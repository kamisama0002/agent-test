"""LlamaIndex 版本：文档索引 + QueryEngine + FunctionAgent。

适合场景：
- 企业文档、知识库、PDF/网页问答；
- 需要数据连接器、索引、检索、QueryEngine 和引用的场景；
- 想把 RAG 作为“一等公民”，而不是自己拼向量库。

本适配器把售后政策建立成 VectorStoreIndex，再把 QueryEngine 包装成 Agent 工具。
当前账号无 embedding 权限，因此使用本地哈希向量；生产环境换成真实 embedding 即可。
"""

from __future__ import annotations

import time

from llama_index.core import Document, VectorStoreIndex
from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.tools import QueryEngineTool
from llama_index.llms.openai_like import OpenAILike

from langchain_cases.config import get_settings
from support_project.contracts import FrameworkResult
from support_project.domain import calculate_refund, lookup_order, policy_sections
from support_project.local_embedding import HashingLlamaEmbedding


def _build_llm() -> OpenAILike:
    settings = get_settings()
    return OpenAILike(
        model=settings.chat_model,
        api_base=settings.base_url,
        api_key=settings.api_key,
        context_window=128000,
        is_chat_model=True,
        is_function_calling_model=True,
        temperature=0,
        max_tokens=800,
        timeout=settings.timeout,
    )


def _build_policy_engine():
    # 每个政策小节是一个 Document，避免依赖外部 tokenizer。
    documents = [
        Document(
            text=f"{section['title']}\n{section['content']}",
            metadata={"title": section["title"], "source": "support_policy.md"},
        )
        for section in policy_sections()
    ]
    index = VectorStoreIndex.from_documents(
        documents,
        embed_model=HashingLlamaEmbedding(),
        transformations=[],
        show_progress=False,
    )
    return index.as_query_engine(llm=_build_llm(), similarity_top_k=2, response_mode="compact")


async def run(question: str) -> FrameworkResult:
    started = time.perf_counter()
    llm = _build_llm()
    policy_engine = _build_policy_engine()

    # QueryEngineTool 是 LlamaIndex 的关键抽象：把“检索 + 生成”封装成工具。
    policy_tool = QueryEngineTool.from_defaults(
        query_engine=policy_engine,
        name="search_support_policy",
        description="检索售后与退款政策，回答政策依据。",
    )

    agent = FunctionAgent(
        tools=[lookup_order, calculate_refund, policy_tool],
        llm=llm,
        system_prompt=(
            "你是售后知识助手。先查订单和退款规则，再检索政策，最后回答。"
            "回答必须说明政策依据和退款金额。"
        ),
    )
    result = await agent.run(question)
    texture = str(result)
    return FrameworkResult(
        framework="LlamaIndex",
        answer=texture,
        elapsed_ms=(time.perf_counter() - started) * 1000,
        strategy="政策 VectorIndex → QueryEngineTool → FunctionAgent",
        trace=["policy_index", "query_engine", "function_agent"],
    )
