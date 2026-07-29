"""本地 Embedding 引擎 — Qwen3-Embedding-0.6B

零网络依赖，纯本地推理。支持 MPS (Apple Silicon) / CUDA / CPU。

特性：
  - instruction-aware embedding（检索 query 自动加前缀，提升召回精度）
  - 批量推理（batch_size=32，吞吐最优）
  - 归一化输出（cosine similarity 直接点积）
  - 兼容 langchain Embeddings 协议
  - 线程安全（SentenceTransformer 内部保证）

性能参考（30条文档，1024维）：
  - MPS (M1/M2):  ~180ms/条 embed, 总批量 5.4s
  - CUDA (4090):  ~5-15ms/条 embed（预估）
  - 检索时单条:   ~60ms (MPS), ~5ms (CUDA)

使用：
    from src.embedding import LocalEmbedding

    emb = LocalEmbedding()

    # 检索场景（query 自动加 instruction prefix）
    query_vec = emb.embed_query("华为ERP项目报价")

    # 写入场景（纯文本 embedding）
    doc_vecs = emb.embed_documents(["文本1", "文本2"])

    # 兼容 langchain
    from langchain.vectorstores import FAISS
    store = FAISS.from_texts(texts, embedding=emb)
"""
from __future__ import annotations

import logging
import os
import time
from typing import List

import numpy as np

logger = logging.getLogger(__name__)

# 模型路径（项目内 models 目录）
_DEFAULT_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "models", "Qwen3-Embedding-0.6B"
)

# 检索 query 的 instruction prefix（Qwen3-Embedding 官方推荐）
_QUERY_INSTRUCTION = "Instruct: Retrieve relevant conversation context\nQuery: "

# 自定义 instruction 映射（按场景切换）
_TASK_INSTRUCTIONS = {
    "retrieval": "Instruct: Retrieve relevant conversation context\nQuery: ",
    "similarity": "Instruct: Find semantically similar text\nQuery: ",
    "classification": "Instruct: Classify the following text\nQuery: ",
}


class LocalEmbedding:
    """本地 Embedding 引擎

    Args:
        model_path: 模型路径，默认 models/Qwen3-Embedding-0.6B
        device: 推理设备 ("mps" / "cuda" / "cpu" / "auto")
        batch_size: 批量推理大小
        normalize: 是否 L2 归一化（默认 True，输出可直接点积算 cosine）
        query_instruction: query embedding 的前缀指令
    """

    def __init__(
        self,
        model_path: str | None = None,
        device: str = "auto",
        batch_size: int = 32,
        normalize: bool = True,
        query_instruction: str | None = None,
    ):
        self._model_path = model_path or _DEFAULT_MODEL_PATH
        self._batch_size = batch_size
        self._normalize = normalize
        self._query_instruction = query_instruction or _QUERY_INSTRUCTION
        self._device = self._resolve_device(device)
        self._model = None
        self._dim: int | None = None

    @property
    def dimension(self) -> int:
        """向量维度（延迟获取，首次调用时加载模型）"""
        if self._dim is None:
            self._ensure_model()
        return self._dim

    # ══════════════════════════════════════════════════════
    # 公开接口
    # ══════════════════════════════════════════════════════

    def embed_query(self, text: str, task: str = "retrieval") -> List[float]:
        """嵌入单条查询（带 instruction prefix）

        Args:
            text: 查询文本
            task: 任务类型 ("retrieval" / "similarity" / "classification")

        Returns:
            1024 维归一化向量
        """
        self._ensure_model()
        instruction = _TASK_INSTRUCTIONS.get(task, self._query_instruction)
        prefixed = f"{instruction}{text}"
        vec = self._model.encode(
            [prefixed],
            normalize_embeddings=self._normalize,
            batch_size=1,
            show_progress_bar=False,
        )[0]
        return vec.tolist()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """嵌入多条文档（无 instruction prefix）

        Args:
            texts: 文档文本列表

        Returns:
            向量列表，每个 1024 维
        """
        if not texts:
            return []
        self._ensure_model()
        vecs = self._model.encode(
            texts,
            normalize_embeddings=self._normalize,
            batch_size=self._batch_size,
            show_progress_bar=False,
        )
        return vecs.tolist()

    def embed_documents_np(self, texts: List[str]) -> np.ndarray:
        """嵌入多条文档，返回 numpy 数组（用于直接写入 HNSW）

        Returns:
            shape (N, 1024) 的 float32 数组
        """
        if not texts:
            return np.array([], dtype=np.float32)
        self._ensure_model()
        return self._model.encode(
            texts,
            normalize_embeddings=self._normalize,
            batch_size=self._batch_size,
            show_progress_bar=False,
        )

    def embed_query_np(self, text: str, task: str = "retrieval") -> np.ndarray:
        """嵌入单条查询，返回 numpy 数组

        Returns:
            shape (1024,) 的 float32 数组
        """
        self._ensure_model()
        instruction = _TASK_INSTRUCTIONS.get(task, self._query_instruction)
        prefixed = f"{instruction}{text}"
        return self._model.encode(
            [prefixed],
            normalize_embeddings=self._normalize,
            batch_size=1,
            show_progress_bar=False,
        )[0]

    # ══════════════════════════════════════════════════════
    # 内部方法
    # ══════════════════════════════════════════════════════

    def _ensure_model(self):
        """延迟加载模型（首次调用时触发）"""
        if self._model is not None:
            return

        from sentence_transformers import SentenceTransformer

        logger.info(
            "Loading Qwen3-Embedding-0.6B on %s from %s...",
            self._device, self._model_path,
        )
        t0 = time.time()

        self._model = SentenceTransformer(
            self._model_path,
            device=self._device,
            trust_remote_code=True,
        )

        # Warmup（首次推理会触发 JIT 编译等开销）
        warmup_vec = self._model.encode(
            ["warmup"], normalize_embeddings=True, show_progress_bar=False
        )
        self._dim = warmup_vec.shape[1]

        load_ms = (time.time() - t0) * 1000
        logger.info(
            "Qwen3-Embedding-0.6B loaded: dim=%d, device=%s, load_time=%.0fms",
            self._dim, self._device, load_ms,
        )

    @staticmethod
    def _resolve_device(device: str) -> str:
        """自动检测最优设备"""
        if device != "auto":
            return device

        import torch
        if torch.cuda.is_available():
            return "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        else:
            return "cpu"

    # ══════════════════════════════════════════════════════
    # langchain Embeddings 协议兼容
    # ══════════════════════════════════════════════════════

    def __call__(self, text: str) -> List[float]:
        """兼容函数式调用"""
        return self.embed_query(text)
