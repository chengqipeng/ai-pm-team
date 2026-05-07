"""StandaloneKnowledgeProvider — 独立模式完整实现

组合 LKEAP + PG + VDB + COS 本地文件存储，实现 KnowledgeProvider 协议。

职责：
    - ingest_document: 把用户上传文件存本地 → 写 PG document + log → 入队（Worker 异步处理）
    - search:          委托 KnowledgeRetriever
    - 管理接口:        直接读 PG
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from src.store.knowledge_dao import (
    KnowledgeBaseBindingDAO, KnowledgeBaseDAO, KnowledgeChunkDAO,
    KnowledgeDocumentDAO, KnowledgeIngestLogDAO,
)
from src.store.knowledge_models import (
    KnowledgeDocumentRow, KnowledgeIngestLogRow,
)

from .guard import DuplicateIngestionError, IngestionGuard
from .lkeap_client import TencentLKEAPClient
from .provider import (
    DocumentInfo, IngestResult, KnowledgeBaseInfo, KnowledgeChunk,
)
from .queue import IngestTask, PgIngestQueue
from .retriever import KnowledgeRetriever
from .vdb_writer import KnowledgeVectorStore

logger = logging.getLogger(__name__)


class StandaloneKnowledgeProvider:
    """本地独立部署模式的 KnowledgeProvider 实现"""

    def __init__(
        self,
        lkeap: TencentLKEAPClient,
        vector_store: KnowledgeVectorStore,
        retriever: KnowledgeRetriever,
        queue: PgIngestQueue,
        guard: IngestionGuard,
        upload_dir: str = "./data/knowledge/uploads",
    ) -> None:
        self._lkeap = lkeap
        self._vdb = vector_store
        self._retriever = retriever
        self._queue = queue
        self._guard = guard
        self._upload_dir = Path(upload_dir)
        self._upload_dir.mkdir(parents=True, exist_ok=True)

    # ═══════════════════════════════════════════════════════════
    # 入库
    # ═══════════════════════════════════════════════════════════

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
        """提交文档入库

        流程：
            1. 计算 file_hash（如未提供）
            2. 查重（guard.check_duplicate）
                - 已入库完成 → 复用，直接返回
                - 正在入库中 → 拒绝（抛异常）
            3. 拷贝文件到 upload_dir
            4. 写 PG ai_knowledge_document（parse_status=pending）
            5. 写 PG ai_knowledge_ingest_log（phase=upload）
            6. 入队 ai_knowledge_ingest_queue
            7. 立即返回 task_id，Worker 异步处理
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        file_name = file_name or os.path.basename(file_path)
        file_type = os.path.splitext(file_name)[1].lstrip(".").lower()
        file_size = os.path.getsize(file_path)

        # 1. 计算 hash
        if not file_hash:
            file_hash = self._compute_hash(file_path)

        # 2. 查重
        try:
            existing = self._guard.check_duplicate(
                tenant_id, knowledge_base_id, file_hash,
            )
        except DuplicateIngestionError as exc:
            return IngestResult(
                task_id="",
                doc_id=exc.doc_id,
                status="running",
                reused=False,
                message=str(exc),
            )

        if existing is not None and existing.parse_status == "parsed" \
                and existing.chunk_status == "indexed":
            return IngestResult(
                task_id="",
                doc_id=existing.doc_id,
                status="reused",
                reused=True,
                message=f"复用已入库文档 {existing.doc_id}",
            )

        # 3. 拷贝到 upload_dir（用 doc_id 命名）
        doc_id = f"doc_{uuid.uuid4().hex[:20]}"
        target_dir = self._upload_dir / str(tenant_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{doc_id}.{file_type}" if file_type else target_dir / doc_id
        shutil.copy2(file_path, target_path)

        # 4. 写 PG document（pending）
        doc_row = KnowledgeDocumentRow(
            doc_id=doc_id,
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
            dataset_id=dataset_id,
            title=(user_metadata or {}).get("title") or file_name,
            file_name=file_name,
            file_type=file_type,
            file_size=file_size,
            file_hash=file_hash,
            raw_url=str(target_path),
            parse_status="pending",
            clean_status="pending",
            chunk_status="pending",
            parse_engine="lkeap",
        )
        KnowledgeDocumentDAO.insert(doc_row)

        # 5. 构造任务 & 写 ingest_log
        task = IngestTask.new(
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
            dataset_id=dataset_id,
            payload={
                "doc_id": doc_id,
                "file_path": str(target_path),
                "file_name": file_name,
                "file_type": file_type,
                "file_size": file_size,
                "file_hash": file_hash,
                "title": (user_metadata or {}).get("title") or file_name,
                "user_metadata": user_metadata or {},
            },
            priority=(user_metadata or {}).get("_priority", 0),
        )
        log_row = KnowledgeIngestLogRow(
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
            dataset_id=dataset_id,
            doc_id=doc_id,
            task_id=task.task_id,
            file_name=file_name,
            file_size=file_size,
            file_type=file_type,
            phase="upload",
            status="running",
            progress=1,
        )
        KnowledgeIngestLogDAO.insert(log_row)

        # 6. 入队
        self._queue.enqueue(task)

        logger.info(
            "Ingest queued: tenant=%s kb=%s doc_id=%s task_id=%s file=%s",
            tenant_id, knowledge_base_id, doc_id, task.task_id, file_name,
        )

        return IngestResult(
            task_id=task.task_id,
            doc_id=doc_id,
            status="pending",
            reused=False,
            message="任务已入队",
        )

    @staticmethod
    def _compute_hash(file_path: str, chunk_size: int = 65536) -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    # ═══════════════════════════════════════════════════════════
    # 检索（委托 Retriever）
    # ═══════════════════════════════════════════════════════════

    async def search(
        self,
        tenant_id: int,
        query: str,
        knowledge_base_id: int | None = None,
        filters: dict | None = None,
        top_k: int = 5,
        enable_rerank: bool = True,
        enable_self_query: bool = True,
        conversation_history: list | None = None,
        agent_name: str = "",
        user_id: str = "",
        thread_id: str = "",
        trace_id: str = "",
    ) -> list[KnowledgeChunk]:
        # Agent 授权校验
        if agent_name:
            if knowledge_base_id:
                ok = KnowledgeBaseBindingDAO.check_access(
                    tenant_id, agent_name, knowledge_base_id,
                )
                if not ok:
                    logger.warning(
                        "Agent %s not authorized for kb %s (tenant=%s)",
                        agent_name, knowledge_base_id, tenant_id,
                    )
                    return []
            else:
                # 无指定 KB → 默认在该 Agent 可见的所有 KB 中检索
                # 此处简化为：若无任何授权，则不检索
                kb_ids = KnowledgeBaseBindingDAO.list_kb_ids_for_agent(
                    tenant_id, agent_name,
                )
                if not kb_ids:
                    return []
                # 当前检索引擎支持单 KB；跨 KB 检索可多次调用聚合或扩展 filter_expr
                # 简化：取第一个（未来可扩展为 OR IN 查询）
                if len(kb_ids) == 1:
                    knowledge_base_id = kb_ids[0]

        return await self._retriever.search(
            tenant_id=tenant_id,
            query=query,
            knowledge_base_id=knowledge_base_id,
            filters=filters,
            top_k=top_k,
            enable_rerank=enable_rerank,
            enable_self_query=enable_self_query,
            conversation_history=conversation_history,
            user_id=user_id,
            thread_id=thread_id,
            trace_id=trace_id,
        )

    # ═══════════════════════════════════════════════════════════
    # 管理接口
    # ═══════════════════════════════════════════════════════════

    async def list_knowledge_bases(
        self, tenant_id: int, agent_name: str = "",
    ) -> list[KnowledgeBaseInfo]:
        rows = KnowledgeBaseDAO.list_by_tenant(tenant_id)
        # 按 agent_name 过滤
        if agent_name:
            allowed = set(KnowledgeBaseBindingDAO.list_kb_ids_for_agent(
                tenant_id, agent_name,
            ))
            rows = [r for r in rows if r.id in allowed]
        return [
            KnowledgeBaseInfo(
                id=r.id,
                tenant_id=r.tenant_id,
                api_key=r.api_key,
                name=r.name,
                description=r.description,
                default_top_k=r.default_top_k,
                document_count=r.document_count,
                chunk_count=r.chunk_count,
            )
            for r in rows
        ]

    async def get_document_info(self, doc_id: str) -> DocumentInfo | None:
        row = KnowledgeDocumentDAO.get_by_doc_id(doc_id)
        if row is None:
            return None
        try:
            md = json.loads(row.metadata) if row.metadata else {}
        except json.JSONDecodeError:
            md = {}
        return DocumentInfo(
            doc_id=row.doc_id,
            title=row.title,
            file_name=row.file_name,
            file_type=row.file_type,
            knowledge_base_id=row.knowledge_base_id,
            metadata=md,
            summary=row.summary,
            chunk_count=row.chunk_count,
            quality_score=row.quality_score,
            created_at=row.created_at,
        )

    async def delete_document(self, tenant_id: int, doc_id: str) -> bool:
        """软删文档 + 级联切片 + 删 VDB 向量"""
        row = KnowledgeDocumentDAO.get_by_doc_id(doc_id)
        if row is None or row.tenant_id != tenant_id:
            return False

        # 1. 软删 PG 切片
        KnowledgeChunkDAO.delete_by_doc(doc_id)
        # 2. 软删 PG Segment（DAO 未列出 delete，跳过；updated 时会被 doc_id 过滤失效）
        # 3. 软删 PG Document
        KnowledgeDocumentDAO.soft_delete(doc_id)
        # 4. 删除 VDB 向量
        try:
            self._vdb.delete_by_doc(str(tenant_id), doc_id)
        except Exception as exc:
            logger.warning("VDB delete failed (non-fatal): %s", exc)
        # 5. KB 统计 -1
        KnowledgeBaseDAO.update_stats(
            row.knowledge_base_id,
            doc_delta=-1,
            chunk_delta=-row.chunk_count,
        )
        logger.info("Document deleted: tenant=%s doc_id=%s", tenant_id, doc_id)
        return True

    async def get_ingest_status(self, task_id: str) -> dict | None:
        """查询入库任务进度（API 轮询用）"""
        queue_info = self._queue.get_status(task_id)
        log_row = KnowledgeIngestLogDAO.get_by_task_id(task_id)

        if queue_info is None and log_row is None:
            return None

        result: dict = {"task_id": task_id}
        if queue_info:
            result.update({
                "queue_status": queue_info["status"],
                "retry_count": queue_info["retry_count"],
                "max_retry": queue_info["max_retry"],
                "last_error": queue_info["last_error"],
            })
        if log_row:
            result.update({
                "doc_id": log_row.doc_id,
                "phase": log_row.phase,
                "status": log_row.status,
                "progress": log_row.progress,
                "quality_score": log_row.quality_score,
                "chunk_count": log_row.chunk_count,
                "segment_count": log_row.segment_count,
                "vector_count": log_row.vector_count,
                "total_duration_ms": log_row.total_duration_ms,
                "error_message": log_row.error_message,
            })
        return result
