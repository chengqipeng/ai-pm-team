"""知识库 Plugin 组装工厂

根据 KnowledgeSettings 配置组装完整的 StandaloneKnowledgeProvider 及其依赖。
由 server.py / build_middleware 调用，得到 provider 后塞入 langgraph config 供
knowledge_search Tool 使用。

用法：
    from src.knowledge.factory import build_knowledge_provider, start_ingest_supervisor

    provider, supervisor = build_knowledge_provider(settings, llm=my_llm)
    await supervisor.start()  # 后台启动 Worker 协程池
    # ...
    await supervisor.stop()
"""
from __future__ import annotations

import logging
import os
from typing import Any

from src.config.models import KnowledgeSettings

from .cleaning import CleaningConfig, DocumentCleaningService
from .cos_client import TencentCOSClient
from .guard import IngestionGuard
from .ingestion import DocumentIngestionPipeline
from .lkeap_client import TencentLKEAPClient
from .quality import DocumentQualityScorer
from .queue import PgIngestQueue
from .retriever import KnowledgeRetriever
from .standalone_provider import StandaloneKnowledgeProvider
from .vdb_writer import KnowledgeVectorStore
from .worker import IngestSupervisor

logger = logging.getLogger(__name__)


def build_knowledge_provider(
    settings: KnowledgeSettings,
    llm: Any | None = None,
    embedding_fn: Any | None = None,
) -> tuple[StandaloneKnowledgeProvider, IngestSupervisor]:
    """组装完整知识库 Provider + 入库 Supervisor

    Args:
        settings: KnowledgeSettings 配置
        llm: LLM 实例（用于 Self-Querying + Auto-Tagging），可选
        embedding_fn: 自定义 embedding 函数；None 时走 LKEAP GetEmbedding

    Returns:
        (provider, supervisor)
        provider 用于 knowledge_search Tool 调用
        supervisor.start() 启动后台 Worker；应用退出时 supervisor.stop()
    """
    # 启动期配置诊断（帮助排查 "为什么 Provider 没起来"）
    # 注意：凭证可能是 base64 编码，用解码后的值做校验
    from .lkeap_client import _maybe_decode_base64

    sid_decoded = _maybe_decode_base64(settings.lkeap_secret_id)
    skey_decoded = _maybe_decode_base64(settings.lkeap_secret_key)

    issues = []
    if not sid_decoded or not skey_decoded:
        issues.append("lkeap_secret_id/lkeap_secret_key 未配置")
    if not settings.vdb_url:
        issues.append("vdb_url 未配置")
    if not settings.vdb_key:
        issues.append("vdb_key 未配置")
    if llm is None:
        issues.append("llm 未注入（自动打标/Self-Querying 将降级）")

    if issues:
        logger.warning(
            "KnowledgeProvider 配置不完整: %s", "; ".join(issues),
        )

    logger.info(
        "KnowledgeProvider 组装: "
        "lkeap_region=%s vdb=%s/%s dim=%d worker_count=%d lkeap_concurrency=%d",
        settings.lkeap_region,
        settings.vdb_database, settings.vdb_chunk_collection,
        settings.embedding_dim,
        settings.ingest_worker_count,
        settings.lkeap_concurrency,
    )

    # 1. LKEAP 客户端
    lkeap = TencentLKEAPClient(
        secret_id=settings.lkeap_secret_id,
        secret_key=settings.lkeap_secret_key,
        region=settings.lkeap_region,
    )

    # 2. 向量库
    vdb = KnowledgeVectorStore(
        url=settings.vdb_url,
        key=settings.vdb_key,
        username=settings.vdb_username,
        database_name=settings.vdb_database,
        chunk_collection=settings.vdb_chunk_collection,
        doc_metadata_collection=settings.vdb_doc_metadata_collection,
        dimension=settings.embedding_dim,
    )

    # 3. 入库守卫
    guard = IngestionGuard(lkeap_concurrency=settings.lkeap_concurrency)

    # 4. 清洗 + 质量评分
    cleaner = DocumentCleaningService(CleaningConfig())
    scorer = DocumentQualityScorer()

    # 5. 入库流水线（实现 IngestPipeline 协议）
    pipeline = DocumentIngestionPipeline(
        lkeap=lkeap,
        vector_store=vdb,
        cleaning_service=cleaner,
        quality_scorer=scorer,
        llm=llm,
        embedding_fn=embedding_fn,
        guard=guard,
        parsed_dir=settings.parsed_dir,
    )

    # 6. 队列 + Worker Supervisor
    queue = PgIngestQueue()
    supervisor = IngestSupervisor(
        pipeline=pipeline,
        worker_count=settings.ingest_worker_count,
        batch=settings.ingest_batch_size,
        poll_interval_ms=settings.ingest_poll_interval_ms,
        reclaim_interval_ms=settings.reclaim_interval_ms,
        queue=queue,
    )

    # 7. 检索引擎
    retriever = KnowledgeRetriever(
        vector_store=vdb,
        lkeap=lkeap,
        llm=llm,
        embedding_fn=embedding_fn,
        expand_context_n=settings.expand_context_n,
    )

    # 8. COS 客户端（可选，凭证通过环境变量注入）
    cos_client: TencentCOSClient | None = None
    cos_secret_id = settings.cos_secret_id or os.environ.get("COS_SECRET_ID", "")
    cos_secret_key = settings.cos_secret_key or os.environ.get("COS_SECRET_KEY", "")
    if cos_secret_id and cos_secret_key:
        try:
            cos_client = TencentCOSClient(
                secret_id=cos_secret_id,
                secret_key=cos_secret_key,
                bucket=settings.cos_bucket or os.environ.get("COS_BUCKET", ""),
                region=settings.cos_region or os.environ.get("COS_REGION", "ap-beijing"),
                key_prefix=settings.cos_key_prefix or os.environ.get("COS_KEY_PREFIX", "knowledge/"),
            )
            logger.info(
                "COS client initialized: bucket=%s region=%s prefix=%s",
                settings.cos_bucket, settings.cos_region, settings.cos_key_prefix,
            )
        except Exception as exc:
            logger.warning("COS client init failed (upload will use local path): %s", exc)
    else:
        logger.info("COS credentials not configured; file upload will use local storage only")

    # 9. 组装 Provider
    provider = StandaloneKnowledgeProvider(
        lkeap=lkeap,
        vector_store=vdb,
        retriever=retriever,
        queue=queue,
        guard=guard,
        upload_dir=settings.upload_dir,
        cos_client=cos_client,
    )

    logger.info(
        "KnowledgeProvider ready (VDB=%s/%s, worker_count=%d, lkeap_region=%s)",
        settings.vdb_database, settings.vdb_chunk_collection,
        settings.ingest_worker_count, settings.lkeap_region,
    )
    return provider, supervisor
