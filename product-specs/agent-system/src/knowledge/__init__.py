"""知识库模块 — 腾讯云 LKEAP 文档解析 + 知识检索

Phase 1 交付：
    - TencentLKEAPClient: LKEAP API 封装（已有）
    - KnowledgeVectorStore: tcvectordb 封装（单库多租户）
    - IngestionGuard: 去重 + LKEAP 并发限流
    - PgIngestQueue / IngestTask: PG 任务队列
    - IngestWorker / Reclaimer / IngestSupervisor: 协程池调度
"""

from .lkeap_client import TencentLKEAPClient
from .vdb_writer import KnowledgeVectorStore
from .guard import IngestionGuard, DuplicateIngestionError, ConcurrentIngestionError
from .queue import IngestTask, PgIngestQueue
from .worker import (
    IngestPipeline,
    IngestWorker,
    Reclaimer,
    IngestSupervisor,
)

__all__ = [
    # LKEAP 客户端
    "TencentLKEAPClient",
    # 向量库
    "KnowledgeVectorStore",
    # 守卫
    "IngestionGuard",
    "DuplicateIngestionError",
    "ConcurrentIngestionError",
    # 队列
    "IngestTask",
    "PgIngestQueue",
    # Worker
    "IngestPipeline",
    "IngestWorker",
    "Reclaimer",
    "IngestSupervisor",
]
