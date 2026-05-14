"""知识库模块 — 腾讯云 LKEAP 文档解析 + 知识检索

Phase 1 + Phase 2 交付：

存储与底层（Phase 1）
    - TencentLKEAPClient: LKEAP API 封装
    - KnowledgeVectorStore: tcvectordb 封装（单库多租户）
    - IngestionGuard: 去重 + LKEAP 并发限流
    - PgIngestQueue / IngestTask: PG 任务队列（SKIP LOCKED）
    - IngestWorker / Reclaimer / IngestSupervisor: 协程池调度

流水线与检索（Phase 2）
    - DocumentCleaningService / CleaningResult: 4 Stage 文本清洗
    - DocumentQualityScorer / QualityScoreResult: 4 信号质量评分
    - KnowledgeProvider / KnowledgeChunk / IngestResult: Provider 协议 + 模型
    - KnowledgeRetriever: 混合检索 + RRF + Rerank + Parent-Child
    - DocumentIngestionPipeline: 5 阶段入库流水线（实现 IngestPipeline）
    - StandaloneKnowledgeProvider: 完整 Provider 实现
"""

from .lkeap_client import TencentLKEAPClient
from .cos_client import TencentCOSClient
from .archive_extractor import ArchiveExtractor, is_archive, ExtractionResult, ExtractedFile
from .vdb_writer import KnowledgeVectorStore
from .guard import IngestionGuard, DuplicateIngestionError, ConcurrentIngestionError
from .queue import IngestTask, PgIngestQueue
from .worker import (
    IngestPipeline,
    IngestWorker,
    Reclaimer,
    IngestSupervisor,
)
from .cleaning import (
    CleaningConfig,
    CleaningResult,
    CleaningSignals,
    DocumentCleaningService,
)
from .quality import (
    DocumentQualityScorer,
    QualityScoreResult,
)
from .keyword_extract import KeywordExtractor
from .provider import (
    DocumentInfo,
    IngestResult,
    KnowledgeBaseInfo,
    KnowledgeChunk,
    KnowledgeProvider,
)
from .retriever import KnowledgeRetriever
from .ingestion import DocumentIngestionPipeline
from .standalone_provider import StandaloneKnowledgeProvider
from .factory import build_knowledge_provider


__all__ = [
    # LKEAP
    "TencentLKEAPClient",
    # COS
    "TencentCOSClient",
    # Archive
    "ArchiveExtractor",
    "is_archive",
    "ExtractionResult",
    "ExtractedFile",
    # VDB
    "KnowledgeVectorStore",
    # Guard
    "IngestionGuard",
    "DuplicateIngestionError",
    "ConcurrentIngestionError",
    # Queue + Worker
    "IngestTask",
    "PgIngestQueue",
    "IngestPipeline",
    "IngestWorker",
    "Reclaimer",
    "IngestSupervisor",
    # Cleaning
    "CleaningConfig",
    "CleaningResult",
    "CleaningSignals",
    "DocumentCleaningService",
    # Quality
    "DocumentQualityScorer",
    "QualityScoreResult",
    # Keywords
    "KeywordExtractor",
    # Provider
    "KnowledgeProvider",
    "KnowledgeChunk",
    "KnowledgeBaseInfo",
    "DocumentInfo",
    "IngestResult",
    # Retriever & Pipeline
    "KnowledgeRetriever",
    "DocumentIngestionPipeline",
    "StandaloneKnowledgeProvider",
    "build_knowledge_provider",
]
