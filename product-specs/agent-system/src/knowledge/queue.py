"""入库任务队列 — 基于 PostgreSQL FOR UPDATE SKIP LOCKED

对应 doc/知识库体系设计方案.md §4.4.1。
本文件是薄封装层，业务语义集中在此；底层 SQL 都在 KnowledgeIngestQueueDAO。

提供给 Worker 使用的接口：
    q = PgIngestQueue()
    q.enqueue(task)                # 入队
    tasks = q.dequeue(worker_id, 4)# 出队（SKIP LOCKED 多 Worker 安全）
    q.ack(task_id)                 # 成功归档
    q.nack(task_id, error)         # 失败重试 / 死信
    q.reclaim_stuck()              # 崩溃恢复
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from src.store.knowledge_dao import KnowledgeIngestQueueDAO
from src.store.knowledge_models import KnowledgeIngestQueueRow

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# IngestTask — 业务侧任务对象（比 Row 更易用）
# ═══════════════════════════════════════════════════════════

@dataclass
class IngestTask:
    """入库任务 — 内存对象

    payload 字段语义（JSON）：
        {
            "file_path":   "data/knowledge/uploads/xxx.pdf",
            "file_name":   "产品手册.pdf",
            "file_type":   "pdf",
            "file_size":   102400,
            "file_hash":   "abc123...",
            "title":       "XXX 产品手册（v2）",
            "user_metadata": {...},    # 用户手动指定的元数据
            "doc_id":      "doc_yyy"   # 由 API 层生成后写入，Worker 读取
        }
    """
    task_id: str
    tenant_id: int
    knowledge_base_id: int
    dataset_id: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    retry_count: int = 0
    max_retry: int = 3
    available_at: int = 0
    visibility_timeout_ms: int = 600_000  # 10 min

    @classmethod
    def new(
        cls,
        tenant_id: int,
        knowledge_base_id: int,
        payload: dict[str, Any],
        dataset_id: int = 0,
        priority: int = 0,
        max_retry: int = 3,
        delay_ms: int = 0,
    ) -> "IngestTask":
        """创建新任务（生成 task_id + 默认 available_at）"""
        task_id = f"kbi_{uuid.uuid4().hex[:20]}"
        now = int(time.time() * 1000)
        return cls(
            task_id=task_id,
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
            dataset_id=dataset_id,
            payload=payload,
            priority=priority,
            max_retry=max_retry,
            available_at=now + delay_ms,
        )

    @classmethod
    def from_row(cls, row: KnowledgeIngestQueueRow) -> "IngestTask":
        """从 PG 行对象构造（payload 自动反序列化）"""
        try:
            payload = json.loads(row.payload) if row.payload else {}
        except json.JSONDecodeError:
            logger.warning("Invalid payload JSON for task %s", row.task_id)
            payload = {}
        return cls(
            task_id=row.task_id,
            tenant_id=row.tenant_id,
            knowledge_base_id=row.knowledge_base_id,
            dataset_id=row.dataset_id,
            payload=payload,
            priority=row.priority,
            retry_count=row.retry_count,
            max_retry=row.max_retry,
            available_at=row.available_at,
            visibility_timeout_ms=row.visibility_timeout_ms,
        )

    def to_row(self) -> KnowledgeIngestQueueRow:
        return KnowledgeIngestQueueRow(
            task_id=self.task_id,
            tenant_id=self.tenant_id,
            knowledge_base_id=self.knowledge_base_id,
            dataset_id=self.dataset_id,
            payload=json.dumps(self.payload, ensure_ascii=False),
            status="pending",
            priority=self.priority,
            available_at=self.available_at,
            retry_count=self.retry_count,
            max_retry=self.max_retry,
            visibility_timeout_ms=self.visibility_timeout_ms,
        )


# ═══════════════════════════════════════════════════════════
# PgIngestQueue — 队列门面
# ═══════════════════════════════════════════════════════════

class PgIngestQueue:
    """知识库入库任务队列

    所有状态都存在 ai_knowledge_ingest_queue 表中，
    多 Worker / 多进程共享时依赖 FOR UPDATE SKIP LOCKED 保证正确性。
    """

    def enqueue(self, task: IngestTask) -> bool:
        """入队

        依赖 uk_queue_task 唯一索引保证幂等：
        同一 task_id 重复入队时 INSERT ON CONFLICT DO NOTHING，返回 False。
        """
        inserted = KnowledgeIngestQueueDAO.enqueue(task.to_row())
        if inserted:
            logger.info(
                "Enqueued task %s (tenant=%s kb=%s priority=%s)",
                task.task_id, task.tenant_id, task.knowledge_base_id, task.priority,
            )
        else:
            logger.debug("Task %s already in queue", task.task_id)
        return inserted

    def dequeue(self, worker_id: str, batch: int = 1) -> list[IngestTask]:
        """出队（FOR UPDATE SKIP LOCKED，多 Worker 并发安全）

        Args:
            worker_id: Worker 标识，通常为 "{hostname}_{pid}_{thread}"
            batch: 一次拉取数量
        """
        rows = KnowledgeIngestQueueDAO.dequeue(worker_id, batch)
        tasks = [IngestTask.from_row(r) for r in rows]
        if tasks:
            logger.info(
                "Dequeued %d tasks by worker=%s (ids=%s)",
                len(tasks), worker_id, [t.task_id for t in tasks],
            )
        return tasks

    def ack(self, task_id: str) -> None:
        """任务成功 — status 置 success"""
        KnowledgeIngestQueueDAO.ack(task_id)
        logger.info("Task %s acked", task_id)

    def nack(self, task_id: str, error: str) -> None:
        """任务失败 — 指数退避重试，耗尽后进死信

        重试间隔：2^retry × 60s（1min, 2min, 4min, 8min, ...）

        如果是「配置性错误」（凭证缺失、依赖未装、不支持的文件类型等），
        直接进死信，不浪费资源反复重试。
        """
        # 简单关键字识别配置性错误
        lower = (error or "").lower()
        config_markers = [
            "no module named", "importerror",
            "invalidcredential", "secret id should not",
            "凭证未配置", "sdk 未安装",
            "unsupported file type", "不支持的文件类型",
        ]
        if any(m in lower for m in config_markers):
            KnowledgeIngestQueueDAO.mark_dead(task_id, error)
            logger.warning(
                "Task %s → DEAD (config error, no retry): %s",
                task_id, error[:200],
            )
            return

        KnowledgeIngestQueueDAO.nack(task_id, error)
        logger.warning("Task %s nacked: %s", task_id, error[:200])

    def reclaim_stuck(self) -> int:
        """回收被 Worker 卡死的任务（崩溃恢复）

        扫描 status=running 且超过 visibility_timeout_ms 的任务，复位为 pending。
        建议在独立协程里每 30s 调用一次。
        """
        count = KnowledgeIngestQueueDAO.reclaim_stuck()
        if count > 0:
            logger.warning("Reclaimed %d stuck tasks", count)
        return count

    def get_status(self, task_id: str) -> dict | None:
        """查询任务状态（供 API 返回给用户 poll）"""
        row = KnowledgeIngestQueueDAO.get_by_task_id(task_id)
        if row is None:
            return None
        return {
            "task_id": row.task_id,
            "status": row.status,
            "retry_count": row.retry_count,
            "max_retry": row.max_retry,
            "last_error": row.last_error,
            "available_at": row.available_at,
            "picked_at": row.picked_at,
            "completed_at": row.completed_at,
        }

    def stats(self, tenant_id: int = 0) -> dict[str, int]:
        """队列各状态数量（监控用）"""
        return KnowledgeIngestQueueDAO.stats_by_status(tenant_id)
