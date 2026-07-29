"""本地 Embedding 模块 — 基于 Qwen3-Embedding-0.6B

提供统一的 embedding 接口，支持：
  - 单条 query embedding（带 instruction prefix，检索优化）
  - 批量 document embedding
  - 兼容 langchain Embeddings 协议

使用：
    from src.embedding import LocalEmbedding

    emb = LocalEmbedding()
    vec = emb.embed_query("华为报价是多少")
    vecs = emb.embed_documents(["文本1", "文本2"])
"""

from .local_embedding import LocalEmbedding

__all__ = ["LocalEmbedding"]
