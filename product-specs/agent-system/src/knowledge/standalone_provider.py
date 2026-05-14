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
    KnowledgeBaseDAO, KnowledgeChunkDAO,
    KnowledgeDocumentDAO, KnowledgeIngestLogDAO,
)
from src.store.knowledge_models import (
    KnowledgeDocumentRow, KnowledgeIngestLogRow,
)

from .cos_client import TencentCOSClient
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
        cos_client: TencentCOSClient | None = None,
    ) -> None:
        self._lkeap = lkeap
        self._vdb = vector_store
        self._retriever = retriever
        self._queue = queue
        self._guard = guard
        self._upload_dir = Path(upload_dir)
        self._upload_dir.mkdir(parents=True, exist_ok=True)
        self._cos = cos_client

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
        # ── 0. 参数校验 + 诊断日志 ──
        logger.info(
            "ingest_document start: tenant=%s kb=%s file=%s path=%s hash=%s meta=%s",
            tenant_id, knowledge_base_id, file_name, file_path,
            file_hash[:16] + "…" if file_hash else "(auto)", user_metadata,
        )

        if not os.path.exists(file_path):
            logger.error("ingest_document: file not found: %s", file_path)
            raise FileNotFoundError(f"文件不存在: {file_path}")

        file_name = file_name or os.path.basename(file_path)
        file_type = os.path.splitext(file_name)[1].lstrip(".").lower()
        file_size = os.path.getsize(file_path)

        if file_size == 0:
            logger.error("ingest_document: empty file: %s", file_path)
            raise ValueError(f"文件大小为 0: {file_name}")

        # ── 1. 计算 hash ──
        if not file_hash:
            try:
                file_hash = self._compute_hash(file_path)
            except Exception as exc:
                logger.exception("ingest_document: hash compute failed: %s", exc)
                raise RuntimeError(f"计算文件 hash 失败: {exc}") from exc

        # ── 2. 查重 ──
        try:
            existing = self._guard.check_duplicate(
                tenant_id, knowledge_base_id, file_hash,
            )
        except DuplicateIngestionError as exc:
            logger.info(
                "ingest_document: duplicate detected, doc_id=%s status=%s",
                exc.doc_id, exc.status,
            )
            return IngestResult(
                task_id="",
                doc_id=exc.doc_id,
                status="running",
                reused=False,
                message=str(exc),
            )
        except Exception as exc:
            logger.exception("ingest_document: check_duplicate failed: %s", exc)
            raise RuntimeError(f"查重失败: {exc}") from exc

        if existing is not None and existing.parse_status == "parsed" \
                and existing.chunk_status == "indexed":
            logger.info(
                "ingest_document: reuse existing doc_id=%s (hash match, already indexed)",
                existing.doc_id,
            )
            return IngestResult(
                task_id="",
                doc_id=existing.doc_id,
                status="reused",
                reused=True,
                message=f"复用已入库文档 {existing.doc_id}",
            )

        # ── 3. 拷贝到 upload_dir（用 doc_id 命名） ──
        doc_id = f"doc_{uuid.uuid4().hex[:20]}"
        target_dir = self._upload_dir / str(tenant_id)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.exception(
                "ingest_document: mkdir failed: %s (upload_dir=%s)",
                exc, self._upload_dir,
            )
            raise RuntimeError(f"创建上传目录失败: {exc}") from exc

        target_path = target_dir / f"{doc_id}.{file_type}" if file_type else target_dir / doc_id
        try:
            shutil.copy2(file_path, target_path)
            logger.debug(
                "ingest_document: file saved to %s (size=%d)",
                target_path, file_size,
            )
        except Exception as exc:
            logger.exception(
                "ingest_document: copy file failed: %s → %s: %s",
                file_path, target_path, exc,
            )
            raise RuntimeError(f"保存文件到知识库目录失败: {exc}") from exc

        # ── 3.5. 上传到 COS（如果配置了 COS 客户端） ──
        cos_url = ""
        if self._cos is not None:
            try:
                object_key = self._cos.build_object_key(
                    tenant_id, knowledge_base_id, doc_id, file_name,
                )
                cos_url = self._cos.upload_file(
                    local_path=str(target_path),
                    object_key=object_key,
                )
                logger.info(
                    "ingest_document: COS upload success: doc_id=%s url=%s",
                    doc_id, cos_url,
                )
            except Exception as exc:
                logger.exception(
                    "ingest_document: COS upload failed (will use local path): "
                    "doc_id=%s file=%s: %s",
                    doc_id, file_name, exc,
                )
                # COS 上传失败不阻断流程，降级使用本地路径 + base64

        # ── 4. 写 PG document（pending）──
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
            raw_url=cos_url or str(target_path),
            parse_status="pending",
            clean_status="pending",
            chunk_status="pending",
            parse_engine="lkeap",
        )
        try:
            KnowledgeDocumentDAO.insert(doc_row)
        except Exception as exc:
            logger.exception(
                "ingest_document: DAO insert document failed: doc_id=%s tenant=%s kb=%s: %s",
                doc_id, tenant_id, knowledge_base_id, exc,
            )
            # 清理已写入的物理文件
            try:
                target_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise RuntimeError(
                f"写入 ai_knowledge_document 失败（可能是 uk_doc_hash 冲突 "
                f"或数据库不可用）: {exc}"
            ) from exc

        # ── 5. 构造任务 & 写 ingest_log ──
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
                "cos_url": cos_url,
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
        try:
            KnowledgeIngestLogDAO.insert(log_row)
        except Exception as exc:
            logger.exception(
                "ingest_document: DAO insert ingest_log failed: task_id=%s: %s",
                task.task_id, exc,
            )
            # 不中断流程 — log 失败不影响主流程

        # ── 6. 入队 ──
        try:
            self._queue.enqueue(task)
        except Exception as exc:
            logger.exception(
                "ingest_document: queue.enqueue failed: task_id=%s doc_id=%s: %s",
                task.task_id, doc_id, exc,
            )
            raise RuntimeError(f"入队失败: {exc}") from exc

        logger.info(
            "Ingest queued: tenant=%s kb=%s doc_id=%s task_id=%s file=%s size=%d type=%s",
            tenant_id, knowledge_base_id, doc_id,
            task.task_id, file_name, file_size, file_type,
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
        threshold: float | None = None,
        enable_self_query: bool = True,
        conversation_history: list | None = None,
        user_id: str = "",
        thread_id: str = "",
        trace_id: str = "",
    ) -> list[KnowledgeChunk]:
        return await self._retriever.search(
            tenant_id=tenant_id,
            query=query,
            knowledge_base_id=knowledge_base_id,
            filters=filters,
            top_k=top_k,
            threshold=threshold,
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
        self, tenant_id: int,
    ) -> list[KnowledgeBaseInfo]:
        rows = KnowledgeBaseDAO.list_by_tenant(tenant_id)
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
        """软删文档 + 级联切片 + 删 VDB 向量 + 更新 KB 统计"""
        row = KnowledgeDocumentDAO.get_by_doc_id(doc_id)
        if row is None or row.tenant_id != tenant_id:
            return False

        # 只有已成功入库（chunk_status=indexed）的文档才在 KB 统计中有贡献，
        # 删除时才从统计扣减；未入库成功的文档（pending/failed）不扣减。
        was_indexed = row.chunk_status == "indexed"

        # 1. 软删 PG 切片
        KnowledgeChunkDAO.delete_by_doc(doc_id)
        # 2. 软删 PG Document
        KnowledgeDocumentDAO.soft_delete(doc_id)
        # 3. 删除 VDB 向量（kb_chunks + kb_doc_metadata）
        try:
            self._vdb.delete_by_doc(str(tenant_id), doc_id)
        except Exception as exc:
            logger.warning("VDB delete failed (non-fatal): %s", exc)
        # 4. KB 统计扣减（只对已入库成功的文档扣）
        if was_indexed:
            KnowledgeBaseDAO.update_stats(
                row.knowledge_base_id,
                doc_delta=-1,
                chunk_delta=-row.chunk_count,
            )
            logger.info(
                "Document deleted: tenant=%s doc_id=%s kb=%s chunks=-%d",
                tenant_id, doc_id, row.knowledge_base_id, row.chunk_count,
            )
        else:
            # 未入库成功的文档也需要重算统计（确保前端显示一致）
            try:
                KnowledgeBaseDAO.recompute_stats(row.knowledge_base_id)
            except Exception as exc:
                logger.warning("recompute_stats after delete failed (non-fatal): %s", exc)
            logger.info(
                "Document deleted (not indexed, stats recomputed): "
                "tenant=%s doc_id=%s kb=%s chunk_status=%s",
                tenant_id, doc_id, row.knowledge_base_id, row.chunk_status,
            )
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
