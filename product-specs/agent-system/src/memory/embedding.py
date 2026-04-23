"""嵌入模型客户端 — 封装 OpenAI-compatible embedding API"""
from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class Embeddings(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class EmbeddingClient:
    """Embedding 客户端 — 支持 OpenAI / DeepSeek / 任意 OpenAI-compatible 端点

    Args:
        model_name: 模型名称
        api_key: API key
        api_base: API base URL（DeepSeek 用 https://api.deepseek.com）
        embeddings: 外部注入的 Embeddings 实例（优先使用）
    """

    def __init__(
        self,
        model_name: str = "text-embedding-3-small",
        api_key: str = "",
        api_base: str = "",
        embeddings: Embeddings | None = None,
    ) -> None:
        self._model_name = model_name
        if embeddings is not None:
            self._embeddings = embeddings
        else:
            self._embeddings = self._create_default(model_name, api_key, api_base)

    @property
    def embeddings(self) -> Embeddings:
        return self._embeddings

    @staticmethod
    def _create_default(model_name: str, api_key: str, api_base: str) -> Embeddings:
        try:
            from langchain_openai import OpenAIEmbeddings
            kwargs = {"model": model_name}
            if api_key:
                kwargs["api_key"] = api_key
            if api_base:
                kwargs["base_url"] = api_base
            return OpenAIEmbeddings(**kwargs)
        except ImportError:
            raise ImportError("langchain_openai 未安装")

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embeddings.embed_documents(texts)

    def embed_query(self, query: str) -> list[float]:
        return self._embeddings.embed_query(query)
