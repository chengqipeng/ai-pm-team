"""入库守卫 — 去重 + LKEAP 并发限流

对应 doc/知识库体系设计方案.md §4.4.3。
不依赖 Redis，全部基于 PG 行锁 + 进程内 asyncio.Semaphore。
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from src.store.knowledge_dao import KnowledgeDocumentDAO
from src.store.knowledge_models import KnowledgeDocumentRow

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 异常定义
# ═══════════════════════════════════════════════════════════

class DuplicateIngestionError(Exception):
    """相同文件已入库或正在入库（非错误，调用方可复用已有 doc_id）"""
    def __init__(self, message: str, doc_id: str = "", status: str = "") -> None:
        super().__init__(message)
        self.doc_id = doc_id
        self.status = status


class ConcurrentIngestionError(Exception):
    """相同文件被另一事务锁定，稍后重试即可"""


# ═══════════════════════════════════════════════════════════
# IngestionGuard
# ═══════════════════════════════════════════════════════════

class IngestionGuard:
    """入库守卫

    职责：
        1. 按 file_hash 去重（走 uk_doc_hash 唯一索引）
        2. 通过 asyncio.Semaphore 控制对 LKEAP 的并发调用

    用法：
        guard = IngestionGuard(lkeap_concurrency=3)

        # 入队前检查
        existing = guard.check_duplicate(tenant_id, kb_id, file_hash)
        if existing:
            return {"doc_id": existing.doc_id, "status": "reused"}

        # 调 LKEAP 时限流
        async with guard.acquire_lkeap_slot():
            task_id = await lkeap.create_parse_task(...)
    """

    def __init__(self, lkeap_concurrency: int = 3) -> None:
        self._lkeap_sem = asyncio.Semaphore(lkeap_concurrency)

    # ── 去重 ──

    def check_duplicate(
        self,
        tenant_id: int,
        knowledge_base_id: int,
        file_hash: str,
    ) -> KnowledgeDocumentRow | None:
        """按 file_hash 查是否已入库。

        行为：
            - 完全相同且已索引完成（未删除）→ 返回该 document 行，调用方应复用 doc_id
            - 相同但正在入库（未删除）→ 抛 DuplicateIngestionError（避免并发重复入库）
            - 已软删除 → 物理删除旧行，释放唯一约束，返回 None（允许重新入库）
            - 不存在 → 返回 None

        本方法走只读查询，不加锁，性能最优。在入队后的 Worker 环节
        会用 lock_by_hash_nowait 做行锁保护。
        """
        if not file_hash:
            return None

        row = KnowledgeDocumentDAO.find_by_hash(tenant_id, knowledge_base_id, file_hash)
        if row is None:
            return None

        # 已软删除 → 物理删除旧行，释放 uk_doc_hash 唯一约束，允许重新入库
        if getattr(row, 'delete_flg', 0) == 1:
            logger.info(
                "Dedup: found soft-deleted doc for hash=%s, hard-deleting doc_id=%s to allow re-ingest",
                file_hash[:8], row.doc_id,
            )
            try:
                KnowledgeDocumentDAO.hard_delete(row.doc_id)
            except Exception as exc:
                logger.warning(
                    "hard_delete failed for doc_id=%s (will retry insert): %s",
                    row.doc_id, exc,
                )
            return None

        # 已完成 → 可复用
        if row.parse_status == "parsed" and row.chunk_status == "indexed":
            logger.info("Dedup hit: tenant=%s kb=%s hash=%s → reuse doc_id=%s",
                        tenant_id, knowledge_base_id, file_hash[:8], row.doc_id)
            return row

        # 正在入库 → 拒绝重复提交
        if row.parse_status in ("pending", "parsing"):
            raise DuplicateIngestionError(
                f"文档 {row.doc_id} 正在入库中（parse_status={row.parse_status}）",
                doc_id=row.doc_id,
                status=row.parse_status,
            )

        # 解析失败的情况 → 物理删除旧行，允许重新入库
        logger.info(
            "Found failed document for hash=%s (parse_status=%s), "
            "hard-deleting doc_id=%s to allow re-ingest",
            file_hash[:8], row.parse_status, row.doc_id,
        )
        try:
            KnowledgeDocumentDAO.hard_delete(row.doc_id)
        except Exception as exc:
            logger.warning(
                "hard_delete failed for stale doc_id=%s: %s", row.doc_id, exc,
            )
            # 如果物理删除失败，尝试软删除后再继续
            try:
                KnowledgeDocumentDAO.soft_delete(row.doc_id)
            except Exception:
                logger.exception("guard.py L131 异常")
        return None

    # ── LKEAP 并发限流 ──

    @asynccontextmanager
    async def acquire_lkeap_slot(self):
        """控制对 LKEAP 的并发调用。

        单进程内有效。多实例部署时各进程各自限流（简单够用）；
        若需全局限流，可替换为 PG 计数器 / Redis 令牌桶。
        """
        await self._lkeap_sem.acquire()
        try:
            yield
        finally:
            self._lkeap_sem.release()

    @property
    def lkeap_concurrency_available(self) -> int:
        """当前可用的 LKEAP 并发槽位数（用于监控）"""
        # asyncio.Semaphore 暴露 _value 作为可用计数
        return getattr(self._lkeap_sem, "_value", 0)
