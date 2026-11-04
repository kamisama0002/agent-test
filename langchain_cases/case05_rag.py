"""案例 05：RAG（检索增强生成）。

对应官方文档：
- Retrieval: https://docs.langchain.com/oss/python/langchain/retrieval
- RAG tutorial: https://docs.langchain.com/oss/python/langchain/rag

完整流程：
1. 加载本地 Markdown 文档；
2. 用 RecursiveCharacterTextSplitter 切片；
3. 生成向量并写入 InMemoryVectorStore；
4. 把“相似度检索”包装成工具；
5. Agent 在需要时检索，再基于检索片段回答。

关于 Embedding 的特别说明：
当前提供的百炼 API Key 访问 embedding 接口会返回 403（API-Key restrictions）。
因此默认使用本地确定性 HashingEmbeddings，保证示例开箱即跑。
如果账号开通了 embedding 权限，在 .env 设置 BAILIAN_EMBEDDING_MODEL 后，
本文件会自动切换到 OpenAIEmbeddings，无需改业务代码。
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .common import build_chat_model, console, message_text, print_panel
from .config import PROJECT_ROOT, get_settings


class HashingEmbeddings(Embeddings):
    """不依赖外部 API 的哈希向量实现，仅用于本地教学与离线演示。

    做法：把英文单词、数字、中文单字和中文二元组哈希到固定维度，
    再做 L2 归一化。它不是语义模型，但对“包含相同关键词”的文本有稳定召回，
    足以让 RAG 流程完整跑通。生产环境请替换成真正的 embedding 模型。
    """

    _english = re.compile(r"[a-zA-Z0-9_]+")
    _chinese = re.compile(r"[\u4e00-\u9fff]+")

    def __init__(self, dimensions: int = 512) -> None:
        self.dimensions = dimensions

    def _tokens(self, text: str) -> list[str]:
        lowered = text.lower()
        tokens = self._english.findall(lowered)
        for run in self._chinese.findall(lowered):
            tokens.extend(run)  # 中文单字
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))  # 中文二元组
        return tokens

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in self._tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            # 正负号能降低不同 token 偶然落到同一桶时的系统性偏差。
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def _build_embeddings() -> tuple[Embeddings, str]:
    """优先使用配置的真实 Embedding；没有配置时回退到本地哈希向量。"""

    settings = get_settings()
    if settings.embedding_model:
        embeddings = OpenAIEmbeddings(
            model=settings.embedding_model,
            api_key=settings.api_key,
            base_url=settings.base_url,
            # 百炼兼容端点对 tiktoken 预分词支持有限，关闭本地长度预检查更稳妥。
            check_embedding_ctx_length=False,
        )
        return embeddings, f"OpenAIEmbeddings({settings.embedding_model})"
    return HashingEmbeddings(), "HashingEmbeddings（本地，512 维）"


def run() -> None:
    data_file = PROJECT_ROOT / "data" / "langchain_guide.md"
    # 使用 LangChain 的 Document 统一承载“正文 + 元数据”。真实项目可换成
    # PDF/Word/网页加载器；后续切分、检索和引用逻辑保持不变。
    documents = [
        Document(
            page_content=data_file.read_text(encoding="utf-8"),
            metadata={"source": str(data_file)},
        )
    ]

    # chunk_size/overlap 没有放之四海皆准的值：
    # - 太小：上下文碎片化；
    # - 太大：检索噪声多、占用 Token。
    # 这里用较小的值，便于观察中文文档的切片效果。
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=260,
        chunk_overlap=40,
        separators=["\n\n", "\n", "。", "；", " "],
    )
    chunks = splitter.split_documents(documents)

    embeddings, embedding_name = _build_embeddings()
    vector_store = InMemoryVectorStore(embedding=embeddings)
    vector_store.add_documents(chunks)

    console.print(f"[cyan]加载文档：[/cyan]{data_file}")
    console.print(f"[cyan]切片数量：[/cyan]{len(chunks)}")
    console.print(f"[cyan]向量实现：[/cyan]{embedding_name}")
    if not get_settings().embedding_model:
        console.print("[yellow]注意：[/yellow]当前 Key 无 embedding 权限，已自动使用本地哈希向量。\n")

    # 检索工具：模型看到的是“工具说明”，实际执行的是向量检索。
    # 返回内容中保留来源文件名，便于最终答案给出处。
    @tool
    def search_langchain_notes(query: str) -> str:
        """搜索本地 LangChain 学习笔记，返回与问题最相关的前三个片段。"""

        hits = vector_store.similarity_search(query, k=3)
        sections: list[str] = []
        for index, doc in enumerate(hits, start=1):
            source = Path(doc.metadata.get("source", "unknown")).name
            sections.append(f"[片段 {index}｜来源 {source}]\n{doc.page_content}")
        return "\n\n".join(sections)

    question = "create_agent 和 LangGraph 分别适合什么场景？"

    # 先单独展示一次检索结果。这样即使不调用模型，也能检查“检索质量”。
    preview_hits = vector_store.similarity_search(question, k=2)
    preview = "\n\n".join(
        f"[片段 {i}] {doc.page_content[:220]}..." for i, doc in enumerate(preview_hits, start=1)
    )
    print_panel("检索预览", preview)

    agent = create_agent(
        model=build_chat_model(),
        tools=[search_langchain_notes],
        system_prompt=(
            "你是 LangChain 学习助手。回答与本地笔记有关的问题前必须调用检索工具；"
            "只依据检索结果作答，并在末尾列出使用到的来源文件名。"
        ),
    )
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})

    console.print("\n[bold]Agent 最终回答[/bold]")
    console.print(message_text(result["messages"][-1]))
    console.print("\n[dim]生产建议：真实 embedding + 持久化向量库 + 元数据过滤 + 重排 + 引用校验。[/dim]")


if __name__ == "__main__":
    run()
