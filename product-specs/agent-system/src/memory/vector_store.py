"""向量存储 — ChromaDB 实现 + VectorStoreProvider 协议"""
from __future__ import annotations

import logging
import uuid
from typing import Protocol, runtime_checkable, Any

from .prompt import MemoryChunk

logger = logging.getLogger(__name__)


@runtime_checkable
class VectorStoreProvider(Protocol):
    async def add_memories(self, memories: list[MemoryChunk]) -> None: ...
    async def search(self, query: str, top_k: int = 5) -> list[MemoryChunk]: ...


class ChromaVectorStore:
    """基于 ChromaDB 的向量存储

    Args:
        collection_name: ChromaDB 集合名称
        embedding_client: EmbeddingClient 实例
        persist_directory: 持久化目录（None 用内存）
    """

    def __init__(
        self,
        collection_name: str = "deepagent_memories",
        embedding_client: Any = None,
        persist_directory: str | None = None,
    ) -> None:
        self._collection_name = collection_name
        self._embedding_client = embedding_client
        self._persist_directory = persist_directory
        self._collection = None
        self._client = None

    def _ensure_collection(self) -> None:
        if self._collection is not None:
            return
        import chromadb
        if self._persist_directory:
            self._client = chromadb.PersistentClient(path=self._persist_directory)
        else:
            self._client = chromadb.Client()
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    async def add_memories(self, memories: list[MemoryChunk]) -> None:
        if not memories:
            return
        self._ensure_collection()

        ids = []
        documents = []
        metadatas = []
        embeddings = None

        # 生成 embedding
        if self._embedding_client is not None:
            texts = [m.content for m in memories]
            computed = self._embedding_client.embed_texts(texts)
            embeddings = []
            for i, m in enumerate(memories):
                embeddings.append(m.embedding if m.embedding else computed[i])

        for m in memories:
            mem_id = m.id or uuid.uuid4().hex
            ids.append(mem_id)
            documents.append(m.content)
            meta = dict(m.metadata)
            if m.user_id:
                meta["user_id"] = m.user_id
            if m.thread_id:
                meta["thread_id"] = m.thread_id
            metadatas.append(meta if meta else {})

        kwargs: dict = {"ids": ids, "documents": documents}
        if any(m for m in metadatas):
            kwargs["metadatas"] = metadatas
        if embeddings:
            kwargs["embeddings"] = embeddings

        self._collection.upsert(**kwargs)
        logger.info("ChromaDB upsert: %d memories", len(memories))

    async def search(self, query: str, top_k: int = 5, user_id: str | None = None) -> list[MemoryChunk]:
        self._ensure_collection()

        query_embedding = None
        if self._embedding_client:
            query_embedding = self._embedding_client.embed_query(query)

        where = {"user_id": user_id} if user_id else None

        if query_embedding:
            results = self._collection.query(
                query_embeddings=[query_embedding], n_results=top_k,
                include=["documents", "metadatas"], where=where,
            )
        else:
            results = self._collection.query(
                query_texts=[query], n_results=top_k,
                include=["documents", "metadatas"], where=where,
            )

        chunks: list[MemoryChunk] = []
        if not results or not results.get("ids"):
            return chunks

        for i, doc_id in enumerate(results["ids"][0]):
            meta = (results["metadatas"][0][i] or {}) if results.get("metadatas") else {}
            content = results["documents"][0][i] if results.get("documents") else ""
            chunks.append(MemoryChunk(
                id=doc_id, content=content,
                user_id=meta.pop("user_id", ""),
                thread_id=meta.pop("thread_id", ""),
                metadata=meta,
            ))

        return chunks
