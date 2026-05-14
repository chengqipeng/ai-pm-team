"""入库 Worker 与 Reclaimer — 协程池 + 崩溃恢复

对应 doc/知识库体系设计方案.md §4.4.4 部署模型。

一个进程内运行 N 个 IngestWorker 协程 + 1 个 Reclaimer 协程：

    supervisor = IngestSupervisor(
        pipeline=my_pipeline,
        worker_count=4,
        poll_interval_ms=500,
    )
    await supervisor.start()
    ...
    await supervisor.stop()

pipeline 只需实现一个方法：
    async def run(task: IngestTask) -> None: ...

失败时 pipeline 抛异常，supervisor 会自动 nack 并按指数退避重试。
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import traceback
from typing import Protocol, runtime_checkable

from .queue import IngestTask, PgIngestQueue

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Pipeline 协议
# ═══════════════════════════════════════════════════════════

@runtime_checkable
class IngestPipeline(Protocol):
    """入库流水线协议 — Worker 只要求这一个方法"""
    async def run(self, task: IngestTask) -> None: ...


# ═══════════════════════════════════════════════════════════
# IngestWorker — 单个 Worker 协程
# ═══════════════════════════════════════════════════════════

class IngestWorker:
    """单个 Worker 协程：循环 dequeue → run → ack/nack

    每次只取 1 个任务串行处理，确保 LKEAP 连接池（max=10）不被打满。
    并发度由 IngestSupervisor 的 worker_count 控制。
    """

    def __init__(
        self,
        worker_id: str,
        queue: PgIngestQueue,
        pipeline: IngestPipeline,
        batch: int = 1,
        poll_interval_ms: int = 500,
    ) -> None:
        self._worker_id = worker_id
        self._queue = queue
        self._pipeline = pipeline
        self._batch = batch
        self._poll_interval = poll_interval_ms / 1000.0
        self._stopped = False

    async def run_forever(self) -> None:
        """主循环 — 取任务、逐个执行、ack/nack。

        串行处理确保单 Worker 同一时刻只占用 1 个 LKEAP 连接槽位，
        总并发 = worker_count（由 Supervisor 控制，默认 2）。
        """
        logger.info("IngestWorker %s started", self._worker_id)
        while not self._stopped:
            try:
                tasks = self._queue.dequeue(self._worker_id, self._batch)
            except Exception as exc:
                logger.exception("Dequeue failed for worker=%s: %s", self._worker_id, exc)
                await asyncio.sleep(self._poll_interval)
                continue

            if not tasks:
                await asyncio.sleep(self._poll_interval)
                continue

            # 逐个串行执行（不再 asyncio.gather 并发，避免打满连接池）
            for task in tasks:
                await self._run_one(task)
        logger.info("IngestWorker %s stopped", self._worker_id)

    async def _run_one(self, task: IngestTask) -> None:
        start = time.time()
        try:
            await self._pipeline.run(task)
            self._queue.ack(task.task_id)
            elapsed_ms = int((time.time() - start) * 1000)
            logger.info(
                "Task %s completed in %dms (worker=%s tenant=%s kb=%s doc=%s)",
                task.task_id, elapsed_ms, self._worker_id,
                task.tenant_id, task.knowledge_base_id,
                task.payload.get("doc_id", ""),
            )
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error(
                "Task %s FAILED (worker=%s tenant=%s kb=%s doc=%s retry=%d/%d): %s",
                task.task_id, self._worker_id,
                task.tenant_id, task.knowledge_base_id,
                task.payload.get("doc_id", ""),
                task.retry_count, task.max_retry,
                exc,
            )
            # DEBUG 级别打印完整堆栈（避免正常日志被刷屏）
            logger.debug("Task %s traceback:\n%s", task.task_id, tb)
            error_msg = f"{type(exc).__name__}: {exc}\n{tb}"
            try:
                self._queue.nack(task.task_id, error_msg)
            except Exception as nack_exc:
                logger.error("Nack also failed for %s: %s", task.task_id, nack_exc)

    def stop(self) -> None:
        self._stopped = True


# ═══════════════════════════════════════════════════════════
# Reclaimer — 崩溃恢复
# ═══════════════════════════════════════════════════════════

class Reclaimer:
    """定时扫描 running 超时的任务，复位为 pending"""

    def __init__(self, queue: PgIngestQueue, interval_ms: int = 30_000) -> None:
        self._queue = queue
        self._interval = interval_ms / 1000.0
        self._stopped = False

    async def run_forever(self) -> None:
        logger.info("Reclaimer started (interval=%ss)", self._interval)
        while not self._stopped:
            try:
                self._queue.reclaim_stuck()
            except Exception as exc:
                logger.exception("Reclaim failed: %s", exc)
            await asyncio.sleep(self._interval)
        logger.info("Reclaimer stopped")

    def stop(self) -> None:
        self._stopped = True


# ═══════════════════════════════════════════════════════════
# IngestSupervisor — 统一管理所有 Worker + Reclaimer
# ═══════════════════════════════════════════════════════════

class IngestSupervisor:
    """入库 Worker 协程池监督者

    用法：
        supervisor = IngestSupervisor(pipeline, worker_count=4)
        await supervisor.start()  # 返回一个 Task，管理所有子协程
        # 应用退出时
        await supervisor.stop()
    """

    def __init__(
        self,
        pipeline: IngestPipeline,
        worker_count: int = 4,
        batch: int = 4,
        poll_interval_ms: int = 500,
        reclaim_interval_ms: int = 30_000,
        queue: PgIngestQueue | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._queue = queue or PgIngestQueue()
        self._worker_count = worker_count
        self._batch = batch
        self._poll_interval_ms = poll_interval_ms
        self._reclaim_interval_ms = reclaim_interval_ms

        self._workers: list[IngestWorker] = []
        self._reclaimer: Reclaimer | None = None
        self._tasks: list[asyncio.Task] = []
        self._started = False

    async def start(self) -> None:
        """启动所有 Worker 和 Reclaimer（非阻塞，立即返回）"""
        if self._started:
            logger.warning("IngestSupervisor already started")
            return

        hostname = socket.gethostname()
        pid = os.getpid()

        for i in range(self._worker_count):
            worker = IngestWorker(
                worker_id=f"{hostname}_{pid}_{i}",
                queue=self._queue,
                pipeline=self._pipeline,
                batch=self._batch,
                poll_interval_ms=self._poll_interval_ms,
            )
            self._workers.append(worker)
            self._tasks.append(asyncio.create_task(
                worker.run_forever(),
                name=f"ingest-worker-{i}",
            ))

        self._reclaimer = Reclaimer(self._queue, self._reclaim_interval_ms)
        self._tasks.append(asyncio.create_task(
            self._reclaimer.run_forever(),
            name="ingest-reclaimer",
        ))

        self._started = True
        logger.info(
            "IngestSupervisor started: %d workers + 1 reclaimer (host=%s pid=%s)",
            self._worker_count, hostname, pid,
        )

    async def stop(self, timeout: float = 30.0) -> None:
        """优雅停止 — 通知所有 Worker 退出，等待当前任务完成"""
        if not self._started:
            return

        logger.info("IngestSupervisor stopping...")
        for w in self._workers:
            w.stop()
        if self._reclaimer:
            self._reclaimer.stop()

        try:
            await asyncio.wait_for(
                asyncio.gather(*self._tasks, return_exceptions=True),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("IngestSupervisor stop timeout; cancelling tasks")
            for t in self._tasks:
                if not t.done():
                    t.cancel()

        self._started = False
        logger.info("IngestSupervisor stopped")

    def stats(self) -> dict:
        """运行时统计（监控用）"""
        queue_stats = {}
        try:
            queue_stats = self._queue.stats()
        except Exception as exc:
            logger.warning("Failed to fetch queue stats: %s", exc)
        return {
            "started": self._started,
            "worker_count": self._worker_count,
            "queue": queue_stats,
        }
