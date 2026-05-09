"""KnowledgeProvider 协议 + 通用数据模型

对应 doc/知识库体系设计方案.md §3.2。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


# ═══════════════════════════════════════════════════════════
# 数据模型（对 Agent / Tool 友好）
# ═══════════════════════════════════════════════════════════

@dataclass
class KnowledgeChunk:
    """知识检索结果 — 对外返回"""
    content: str                             # 切片文本
    score: float = 0.0                       # 相关性分数
    metadata: dict = field(default_factory=dict)
    document_id: str = ""
    document_title: str = ""
    chunk_id: str = ""
    chunk_index: int = 0
    section_title: str = ""
    section_path: str = ""
    chunk_type: str = "Text"
    expanded_context: str = ""               # Parent-Child 扩展上下文


@dataclass
class KnowledgeBaseInfo:
    """知识库信息"""
    id: int
    tenant_id: int
    api_key: str
    name: str
    description: str = ""
    default_top_k: int = 5
    document_count: int = 0
    chunk_count: int = 0


@dataclass
class DocumentInfo:
    """文档信息"""
    doc_id: str
    title: str
    file_name: str
    file_type: str
    knowledge_base_id: int
    metadata: dict = field(default_factory=dict)
    summary: str = ""
    chunk_count: int = 0
    quality_score: float = 0.0
    created_at: int = 0                      # 毫秒时间戳


@dataclass
class IngestResult:
    """入库提交结果（异步入队后立即返回给 API 调用方）"""
    task_id: str                             # 任务 ID（用于查询进度）
    doc_id: str = ""                         # 文档 ID（落库后生成）
    status: str = "pending"                  # pending / reused / running / success / failed
    reused: bool = False                     # 是否复用已存在的文档
    message: str = ""


# ═══════════════════════════════════════════════════════════
# KnowledgeProvider 协议
# ═══════════════════════════════════════════════════════════

@runtime_checkable
class KnowledgeProvider(Protocol):
    """知识库 Provider 协议

    两种实现：
        - StandaloneKnowledgeProvider: 本地完整流水线（LKEAP + PG + VDB）
        - NeoAgentKnowledgeProvider:   代理到 NeoAgent 平台 searchByApp API
    """

    # ── 入库 ──

    async def ingest_document(
        self,
        tenant_id: int,
        knowledge_base_id: int,
        file_path: str,
        file_name: str = "",
        file_hash: str = "",
        user_metadata: dict | None = None,
        dataset_id: int = 0,
    ) -> IngestResult:
        """提交文档入库任务（异步）— 立即返回 task_id，Worker 后台处理"""
        ...

    # ── 检索 ──

    async def search(
        self,
        tenant_id: int,
        query: str,
        knowledge_base_id: int | None = None,
        filters: dict | None = None,
        top_k: int = 5,
        threshold: float | None = None,
        enable_self_query: bool = True,
        conversation_history: list | None = None,
        user_id: str = "",
        thread_id: str = "",
        trace_id: str = "",
    ) -> list[KnowledgeChunk]:
        """知识检索：Self-Querying → 多路召回 → 归一化多维度加权 → threshold 过滤

        threshold 优先级：调用方显式 > KB.min_score > 默认值 (0.3)。
        传 0 可关闭过滤；传 None 按优先级自动解析。
        """
        ...

    # ── 管理 ──

    async def list_knowledge_bases(
        self, tenant_id: int,
    ) -> list[KnowledgeBaseInfo]:
        """列出租户下的所有知识库"""
        ...

    async def get_document_info(self, doc_id: str) -> DocumentInfo | None:
        """获取文档详情"""
        ...

    async def delete_document(self, tenant_id: int, doc_id: str) -> bool:
        """删除文档（级联切片 + 向量）"""
        ...

    async def get_ingest_status(self, task_id: str) -> dict | None:
        """查询入库任务状态（供前端轮询）"""
        ...
