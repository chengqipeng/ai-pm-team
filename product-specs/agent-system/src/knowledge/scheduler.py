"""知识库调度任务执行器

支持的任务类型：
    - decay_hit_counts：热度衰减（PG + VDB 同步）。默认全局衰减；
      params 可配 `per_tenant=true` 启用按租户独立衰减。
    - sync_vdb_hit_count：PG → VDB 的 hit_count 准实时同步（默认每 15 分钟）。
    - rebuild_doc_metadata：将 PG 文档元数据批量同步到 VDB kb_doc_metadata
      （如 KB 改名/dataset 改名后，重建 toc/title 等字段）。
    - vdb_health_check：对比 PG 文档数 vs VDB 文档数，不一致时告警 + 自动补录。

调度模式：基于 interval_ms 的简单定时（非 cron 表达式）。
由 IngestSupervisor 内的一个协程定期检查 next_run_at 并执行。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Any

from src.store.pg_pool import get_conn
from src.store.knowledge_dao import (
    KnowledgeBaseDAO, KnowledgeChunkDAO, KnowledgeDatasetDAO,
    KnowledgeDocumentDAO,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 调度任务 DAO
# ═══════════════════════════════════════════════════════════

class ScheduleDAO:

    @staticmethod
    def list_all() -> list[dict]:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, name, description, task_type, cron_expr, interval_ms,
                       params, enabled, last_run_at, last_run_status, last_run_result,
                       next_run_at, run_count, created_at, updated_at
                FROM ai_knowledge_schedule
                WHERE delete_flg = 0
                ORDER BY created_at
            """)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    @staticmethod
    def get_by_name(name: str) -> dict | None:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, name, description, task_type, cron_expr, interval_ms,
                       params, enabled, last_run_at, last_run_status, last_run_result,
                       next_run_at, run_count, created_at, updated_at
                FROM ai_knowledge_schedule
                WHERE name = %s AND delete_flg = 0
            """, (name,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))

    @staticmethod
    def update_config(name: str, enabled: int | None = None,
                      interval_ms: int | None = None,
                      params: str | None = None) -> bool:
        now = int(time.time() * 1000)
        sets = ["updated_at = %s"]
        args: list[Any] = [now]
        if enabled is not None:
            sets.append("enabled = %s")
            args.append(enabled)
        if interval_ms is not None:
            sets.append("interval_ms = %s")
            args.append(interval_ms)
            # 更新 next_run_at
            sets.append("next_run_at = %s")
            args.append(now + interval_ms)
        if params is not None:
            sets.append("params = %s")
            args.append(params)
        args.append(name)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE ai_knowledge_schedule SET {', '.join(sets)} WHERE name = %s AND delete_flg = 0",
                tuple(args),
            )
            return cur.rowcount > 0

    @staticmethod
    def mark_run(name: str, status: str, result: str, next_run_at: int) -> None:
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute("""
                UPDATE ai_knowledge_schedule
                SET last_run_at = %s, last_run_status = %s, last_run_result = %s,
                    next_run_at = %s, run_count = run_count + 1, updated_at = %s
                WHERE name = %s AND delete_flg = 0
            """, (now, status, result[:2000], next_run_at, now, name))

    @staticmethod
    def get_due_tasks() -> list[dict]:
        """获取到期需要执行的任务"""
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, name, task_type, interval_ms, params
                FROM ai_knowledge_schedule
                WHERE enabled = 1 AND next_run_at <= %s AND delete_flg = 0
            """, (now,))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


# ═══════════════════════════════════════════════════════════
# 任务执行器
# ═══════════════════════════════════════════════════════════

class ScheduleExecutor:
    """调度任务执行器 — 检查到期任务并执行"""

    def __init__(self, vdb: Any | None = None) -> None:
        """vdb: KnowledgeVectorStore 实例。None 时 VDB 相关任务降级为 noop。"""
        self._vdb = vdb

    async def tick(self) -> int:
        """检查并执行所有到期任务，返回执行数量"""
        due = ScheduleDAO.get_due_tasks()
        if not due:
            return 0

        executed = 0
        for task in due:
            name = task["name"]
            task_type = task["task_type"]
            interval_ms = task["interval_ms"]
            try:
                params = json.loads(task.get("params") or "{}")
            except json.JSONDecodeError:
                params = {}

            try:
                result = await self._execute(task_type, params)
                next_run = int(time.time() * 1000) + interval_ms
                ScheduleDAO.mark_run(name, "success", json.dumps(result, ensure_ascii=False), next_run)
                logger.info("Schedule executed: name=%s type=%s result=%s", name, task_type, result)
                executed += 1
            except Exception as exc:
                next_run = int(time.time() * 1000) + interval_ms
                ScheduleDAO.mark_run(name, "failed", str(exc)[:2000], next_run)
                logger.exception("Schedule failed: name=%s type=%s: %s", name, task_type, exc)

        return executed

    async def _execute(self, task_type: str, params: dict) -> dict:
        """根据 task_type 分发执行"""
        if task_type == "decay_hit_counts":
            return await self._run_decay(params)
        elif task_type == "sync_vdb_hit_count":
            return await self._run_sync_vdb_hit_count(params)
        elif task_type == "rebuild_doc_metadata":
            return await self._run_rebuild_doc_metadata(params)
        elif task_type == "vdb_health_check":
            return await self._run_vdb_health_check(params)
        else:
            raise ValueError(f"Unknown task_type: {task_type}")

    async def _run_decay(self, params: dict) -> dict:
        """衰减 PG 热度，并把衰减后的结果同步到 VDB。

        params:
          decay_factor: 保留系数（默认 0.7）
          per_tenant:   true 时按租户独立衰减（逐租户 UPDATE）
        """
        factor = float(params.get("decay_factor", 0.7))
        per_tenant = bool(params.get("per_tenant", False))

        if per_tenant:
            tenants = await asyncio.to_thread(
                KnowledgeDocumentDAO.list_tenants_with_hits,
            )
            doc_total = 0
            chunk_total = 0
            for tid in tenants:
                doc_total += await asyncio.to_thread(
                    KnowledgeDocumentDAO.decay_hit_counts, factor, tid,
                )
                chunk_total += await asyncio.to_thread(
                    KnowledgeChunkDAO.decay_hit_counts, factor, tid,
                )
            doc_count = doc_total
            chunk_count = chunk_total
            mode = f"per_tenant ({len(tenants)} tenants)"
        else:
            doc_count = await asyncio.to_thread(
                KnowledgeDocumentDAO.decay_hit_counts, factor,
            )
            chunk_count = await asyncio.to_thread(
                KnowledgeChunkDAO.decay_hit_counts, factor,
            )
            mode = "global"

        vdb_synced = 0
        if self._vdb is not None and doc_count > 0:
            try:
                vdb_synced = await self._sync_hit_count_to_vdb(all_docs=True)
            except Exception as exc:
                logger.warning("Decay VDB sync failed (PG 已更新): %s", exc)

        return {
            "decay_factor": factor,
            "mode": mode,
            "documents_decayed": doc_count,
            "chunks_decayed": chunk_count,
            "vdb_docs_synced": vdb_synced,
        }

    async def _run_sync_vdb_hit_count(self, params: dict) -> dict:
        """增量同步 PG → VDB 的 search_hit_count。"""
        if self._vdb is None:
            return {"synced": 0, "note": "vdb not available"}

        all_docs = bool(params.get("all", False))
        synced = await self._sync_hit_count_to_vdb(
            all_docs=all_docs,
            since_ms=params.get("since_ms"),
            max_docs=int(params.get("max_docs", 1000)),
        )
        return {"synced": synced, "all": all_docs}

    async def _run_rebuild_doc_metadata(self, params: dict) -> dict:
        """批量同步 PG 文档元数据到 VDB kb_doc_metadata。

        场景：KB 改名/dataset 改名/文档 summary 被手动修正后，VDB 的 toc/title 会失效。
        此任务扫描近期（默认 1 小时内）有变动的文档，读 PG 全字段后重写 VDB 记录。
        **会重新编码 BM25 sparse_vector**（因 toc/summary 等字段变了）。

        params:
          since_minutes: 扫描多久之前的变动（默认 60 分钟，即"上次调度后的增量"）
          max_docs: 单次处理上限（默认 500）
          all: true 时全量重建（小心使用）
        """
        if self._vdb is None:
            return {"rebuilt": 0, "note": "vdb not available"}

        all_docs = bool(params.get("all", False))
        max_docs = int(params.get("max_docs", 500))
        if all_docs:
            since_ms = 0
        else:
            since_minutes = int(params.get("since_minutes", 60))
            since_ms = int(time.time() * 1000) - since_minutes * 60 * 1000

        rows = await asyncio.to_thread(
            KnowledgeDocumentDAO.list_docs_needing_rebuild, since_ms, max_docs,
        )
        if not rows:
            return {"rebuilt": 0, "scanned": 0}

        rebuilt = 0
        failed = 0
        for row in rows:
            did = row["doc_id"]
            try:
                await self._rebuild_single_doc_metadata(did)
                rebuilt += 1
            except Exception as exc:
                logger.warning("rebuild_doc_metadata failed doc=%s: %s", did, exc)
                failed += 1
        return {
            "scanned": len(rows),
            "rebuilt": rebuilt,
            "failed": failed,
            "all": all_docs,
        }

    async def _rebuild_single_doc_metadata(self, doc_id: str) -> None:
        """单个文档的 doc_metadata 重建。

        读 PG → 通过 DocumentIngestionPipeline._build_doc_metadata_record 构造
        完整 record → upsert 到 VDB。不重新生成 embedding（保留原 vector）。
        """
        from src.knowledge.ingestion import DocumentIngestionPipeline
        from src.store.knowledge_models import KnowledgeChunkRow as _ChunkRow

        doc = await asyncio.to_thread(KnowledgeDocumentDAO.get_by_doc_id, doc_id)
        if not doc:
            return

        # 取原 VDB 记录的 vector（避免重新调 embedding）
        existing = await asyncio.to_thread(
            self._vdb.get_doc_metadata,
            str(doc.tenant_id),
            [doc_id],
            None,  # 默认 output_fields 不含 vector，下面用 query 直接拉
        )
        # 单独查 vector（get_doc_metadata 没带 vector）
        try:
            from tcvectordb.model.document import Filter  # noqa
            raw = await asyncio.to_thread(
                self._vdb._doc_meta_coll.query,  # type: ignore[attr-defined]
                document_ids=[doc_id],
                retrieve_vector=True,
                output_fields=["id", "tenant_id"],
                limit=1,
            )
            existing_vec = None
            if raw:
                existing_vec = raw[0].get("vector")
        except Exception:
            existing_vec = None

        if not existing_vec:
            # 没有原 vector，跳过（通常不该发生；如 doc_metadata 未同步）
            logger.debug("rebuild: doc=%s has no existing vector, skipping", doc_id)
            return

        # 构造 record（从 chunks 取 Schema 冗余字段，没有就建个空样本）
        sample = _ChunkRow(
            doc_category="", industry="", business_stage="",
            target_audience="", product_service="",
        )
        rec = DocumentIngestionPipeline._build_doc_metadata_record(  # noqa: SLF001
            doc_row=doc,
            summary_vector=existing_vec,
            chunks=[sample],
        )
        await asyncio.to_thread(self._vdb.upsert_doc_metadata, [rec])

    async def _run_vdb_health_check(self, params: dict) -> dict:
        """对比 PG ↔ VDB 的文档数，发现不一致告警 + 可选自动修复。

        params:
          auto_repair: true 时自动触发 rebuild/sync（默认 false，只告警）
          per_tenant: true 时按租户分别对比（默认 true）
        """
        if self._vdb is None:
            return {"checked": 0, "note": "vdb not available"}

        auto_repair = bool(params.get("auto_repair", False))
        per_tenant = bool(params.get("per_tenant", True))

        report: dict[str, dict] = {}
        repaired = 0
        issues = 0

        if per_tenant:
            tenants = await asyncio.to_thread(
                KnowledgeDocumentDAO.list_tenants_with_hits,
            )
            # 同时考虑 hit=0 的租户（可能新建未检索过）
            try:
                with get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT DISTINCT tenant_id FROM ai_knowledge_document
                        WHERE delete_flg=0 AND chunk_status='indexed'
                    """)
                    all_tenants = [r[0] for r in cur.fetchall()]
                tenants = sorted(set(tenants) | set(all_tenants))
            except Exception:
                pass
        else:
            tenants = [0]  # 0 代表不区分

        for tid in tenants:
            pg_count = await asyncio.to_thread(
                KnowledgeDocumentDAO.count_indexed_docs,
                tid if per_tenant else None,
            )
            vdb_count = await asyncio.to_thread(
                self._vdb.count_docs, str(tid),
            ) if per_tenant else -1

            diff = pg_count - vdb_count if vdb_count >= 0 else None
            report[str(tid)] = {
                "pg_docs": pg_count,
                "vdb_docs": vdb_count,
                "diff": diff,
            }
            if diff is not None and diff != 0:
                issues += 1
                if auto_repair and diff > 0:
                    # PG 有但 VDB 缺 → 触发 rebuild
                    try:
                        await self._run_rebuild_doc_metadata(
                            {"all": True, "max_docs": 500}
                        )
                        repaired += 1
                    except Exception as exc:
                        logger.warning("health_check auto_repair failed: %s", exc)

        return {
            "issues": issues,
            "repaired": repaired,
            "report": report,
        }

    async def _sync_hit_count_to_vdb(
        self,
        all_docs: bool = False,
        since_ms: int | None = None,
        max_docs: int = 1000,
    ) -> int:
        """核心同步逻辑：从 PG 读 hit_count，按 tenant 分组 upsert 到 VDB。"""
        if self._vdb is None:
            return 0

        # 决定增量 vs 全量
        if all_docs:
            rows = await asyncio.to_thread(
                KnowledgeDocumentDAO.list_all_hit_counts, max_docs,
            )
        else:
            if since_ms is None:
                # 默认 24 小时内的变更
                since_ms = int(time.time() * 1000) - 24 * 60 * 60 * 1000
            rows = await asyncio.to_thread(
                KnowledgeDocumentDAO.list_hit_counts_since, since_ms, max_docs,
            )

        if not rows:
            return 0

        # 按 tenant 分组（VDB 必须按租户过滤）
        per_tenant: dict[str, dict[str, dict]] = defaultdict(dict)
        for r in rows:
            tid = str(r.get("tenant_id", ""))
            did = r.get("doc_id", "")
            if not tid or not did:
                continue
            per_tenant[tid][did] = {
                "search_hit_count": int(r.get("search_hit_count") or 0),
            }

        total_synced = 0
        for tid, updates in per_tenant.items():
            try:
                n = await asyncio.to_thread(
                    self._vdb.batch_update_doc_fields,
                    tenant_id=tid,
                    updates=updates,
                )
                total_synced += n
            except Exception as exc:
                logger.warning("VDB batch sync failed for tenant=%s: %s", tid, exc)
        return total_synced


# ═══════════════════════════════════════════════════════════
# 调度循环协程（嵌入 IngestSupervisor 或独立运行）
# ═══════════════════════════════════════════════════════════

class ScheduleRunner:
    """定时检查调度任务的协程"""

    def __init__(self, check_interval_ms: int = 60_000, vdb: Any | None = None) -> None:
        self._interval = check_interval_ms / 1000.0
        self._executor = ScheduleExecutor(vdb=vdb)
        self._stopped = False

    async def run_forever(self) -> None:
        logger.info("ScheduleRunner started (check every %.0fs)", self._interval)
        while not self._stopped:
            try:
                await self._executor.tick()
            except Exception as exc:
                logger.exception("ScheduleRunner tick failed: %s", exc)
            await asyncio.sleep(self._interval)
        logger.info("ScheduleRunner stopped")

    def stop(self) -> None:
        self._stopped = True
