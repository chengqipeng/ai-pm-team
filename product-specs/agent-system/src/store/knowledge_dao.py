"""知识库数据访问层 — 10 张 ai_knowledge_* 表的 CRUD + 专用查询

对齐 src/store/dao.py 的风格：
- 使用 get_conn() 上下文管理器，自动 commit/rollback
- 所有 DAO 为 staticmethod
- 行 → dataclass 的映射复用通用 _row_to_model
"""
from __future__ import annotations

import dataclasses
import logging
import time
from typing import Any

from .pg_pool import get_conn
from .knowledge_models import (
    KnowledgeBaseRow,
    KnowledgeDatasetRow,
    KnowledgeSchemaRow,
    KnowledgeDocumentRow,
    KnowledgeSegmentRow,
    KnowledgeChunkRow,
    KnowledgeIngestQueueRow,
    KnowledgeIngestLogRow,
    KnowledgeSearchLogRow,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# KnowledgeBaseDAO
# ═══════════════════════════════════════════════════════════

class KnowledgeBaseDAO:

    @staticmethod
    def insert(kb: KnowledgeBaseRow) -> None:
        with get_conn() as conn:
            conn.cursor().execute("""
                INSERT INTO ai_knowledge_base
                (id, tenant_id, api_key, name, description, owner,
                 default_top_k, min_score, enable_rerank, enable_self_query, enable_query_rewrite,
                 vdb_database, vdb_collection, schema_id,
                 document_count, chunk_count, total_tokens,
                 status, ext_info, delete_flg,
                 created_at, created_by, updated_at, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (kb.id, kb.tenant_id, kb.api_key, kb.name, kb.description, kb.owner,
                  kb.default_top_k, kb.min_score, kb.enable_rerank,
                  kb.enable_self_query, kb.enable_query_rewrite,
                  kb.vdb_database, kb.vdb_collection, kb.schema_id,
                  kb.document_count, kb.chunk_count, kb.total_tokens,
                  kb.status, kb.ext_info, kb.delete_flg,
                  kb.created_at, kb.created_by, kb.updated_at, kb.updated_by))

    @staticmethod
    def get_by_api_key(tenant_id: int, api_key: str) -> KnowledgeBaseRow | None:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM ai_knowledge_base
                WHERE tenant_id=%s AND api_key=%s AND delete_flg=0
            """, (tenant_id, api_key))
            row = cur.fetchone()
            return _row_to_model(cur.description, row, KnowledgeBaseRow) if row else None

    @staticmethod
    def get_by_id(kb_id: int) -> KnowledgeBaseRow | None:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ai_knowledge_base WHERE id=%s AND delete_flg=0", (kb_id,))
            row = cur.fetchone()
            return _row_to_model(cur.description, row, KnowledgeBaseRow) if row else None

    @staticmethod
    def list_by_tenant(tenant_id: int) -> list[KnowledgeBaseRow]:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM ai_knowledge_base
                WHERE tenant_id=%s AND delete_flg=0
                ORDER BY created_at DESC
            """, (tenant_id,))
            return [_row_to_model(cur.description, r, KnowledgeBaseRow) for r in cur.fetchall()]

    @staticmethod
    def update_stats(kb_id: int, doc_delta: int = 0, chunk_delta: int = 0,
                     token_delta: int = 0) -> None:
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute("""
                UPDATE ai_knowledge_base
                SET document_count = document_count + %s,
                    chunk_count = chunk_count + %s,
                    total_tokens = total_tokens + %s,
                    updated_at = %s
                WHERE id = %s
            """, (doc_delta, chunk_delta, token_delta, now, kb_id))

    @staticmethod
    def soft_delete(kb_id: int) -> bool:
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE ai_knowledge_base SET delete_flg=1, updated_at=%s
                WHERE id=%s AND delete_flg=0
            """, (now, kb_id))
            return cur.rowcount > 0


# ═══════════════════════════════════════════════════════════
# KnowledgeDatasetDAO
# ═══════════════════════════════════════════════════════════

class KnowledgeDatasetDAO:

    @staticmethod
    def insert(d: KnowledgeDatasetRow) -> None:
        with get_conn() as conn:
            conn.cursor().execute("""
                INSERT INTO ai_knowledge_dataset
                (id, tenant_id, knowledge_base_id, name, description,
                 default_metadata, chunk_strategy, chunk_size, chunk_overlap,
                 document_count, chunk_count,
                 status, ext_info, delete_flg,
                 created_at, created_by, updated_at, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (d.id, d.tenant_id, d.knowledge_base_id, d.name, d.description,
                  d.default_metadata, d.chunk_strategy, d.chunk_size, d.chunk_overlap,
                  d.document_count, d.chunk_count,
                  d.status, d.ext_info, d.delete_flg,
                  d.created_at, d.created_by, d.updated_at, d.updated_by))

    @staticmethod
    def list_by_kb(tenant_id: int, knowledge_base_id: int) -> list[KnowledgeDatasetRow]:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM ai_knowledge_dataset
                WHERE tenant_id=%s AND knowledge_base_id=%s AND delete_flg=0
                ORDER BY created_at DESC
            """, (tenant_id, knowledge_base_id))
            return [_row_to_model(cur.description, r, KnowledgeDatasetRow) for r in cur.fetchall()]

    @staticmethod
    def get_by_id(dataset_id: int) -> KnowledgeDatasetRow | None:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ai_knowledge_dataset WHERE id=%s AND delete_flg=0",
                        (dataset_id,))
            row = cur.fetchone()
            return _row_to_model(cur.description, row, KnowledgeDatasetRow) if row else None


# ═══════════════════════════════════════════════════════════
# KnowledgeSchemaDAO
# ═══════════════════════════════════════════════════════════

class KnowledgeSchemaDAO:

    @staticmethod
    def insert(s: KnowledgeSchemaRow) -> None:
        with get_conn() as conn:
            conn.cursor().execute("""
                INSERT INTO ai_knowledge_schema
                (id, tenant_id, name, knowledge_base_id, fields, version,
                 status, delete_flg, created_at, created_by, updated_at, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (s.id, s.tenant_id, s.name, s.knowledge_base_id, s.fields, s.version,
                  s.status, s.delete_flg,
                  s.created_at, s.created_by, s.updated_at, s.updated_by))

    @staticmethod
    def get_by_id(schema_id: int) -> KnowledgeSchemaRow | None:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ai_knowledge_schema WHERE id=%s AND delete_flg=0",
                        (schema_id,))
            row = cur.fetchone()
            return _row_to_model(cur.description, row, KnowledgeSchemaRow) if row else None

    @staticmethod
    def get_for_kb(tenant_id: int, knowledge_base_id: int) -> KnowledgeSchemaRow | None:
        """查找知识库专属 Schema；若无则回退到租户默认 (knowledge_base_id=0)"""
        with get_conn() as conn:
            cur = conn.cursor()
            # 1. 尝试 KB 专属
            cur.execute("""
                SELECT * FROM ai_knowledge_schema
                WHERE tenant_id=%s AND knowledge_base_id=%s
                  AND status='active' AND delete_flg=0
                ORDER BY version DESC LIMIT 1
            """, (tenant_id, knowledge_base_id))
            row = cur.fetchone()
            if row:
                return _row_to_model(cur.description, row, KnowledgeSchemaRow)
            # 2. 回退到租户默认
            cur.execute("""
                SELECT * FROM ai_knowledge_schema
                WHERE tenant_id=%s AND knowledge_base_id=0
                  AND status='active' AND delete_flg=0
                ORDER BY version DESC LIMIT 1
            """, (tenant_id,))
            row = cur.fetchone()
            return _row_to_model(cur.description, row, KnowledgeSchemaRow) if row else None


# ═══════════════════════════════════════════════════════════
# KnowledgeDocumentDAO
# ═══════════════════════════════════════════════════════════

class KnowledgeDocumentDAO:

    @staticmethod
    def insert(d: KnowledgeDocumentRow) -> None:
        with get_conn() as conn:
            conn.cursor().execute("""
                INSERT INTO ai_knowledge_document
                (id, doc_id, tenant_id, knowledge_base_id, dataset_id,
                 title, file_name, file_type, file_size, file_hash,
                 raw_url, parsed_md_url, parsed_json_url, page_count, total_chars,
                 parse_status, parse_task_id, parse_engine, parse_error, failed_pages,
                 clean_status, clean_error,
                 chunk_status, chunk_count, segment_count,
                 summary, keywords, metadata, metadata_tagged,
                 quality_score, quality_signals,
                 date_published, search_hit_count,
                 status, ext_info, delete_flg,
                 created_at, created_by, updated_at, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (d.id, d.doc_id, d.tenant_id, d.knowledge_base_id, d.dataset_id,
                  d.title, d.file_name, d.file_type, d.file_size, d.file_hash,
                  d.raw_url, d.parsed_md_url, d.parsed_json_url, d.page_count, d.total_chars,
                  d.parse_status, d.parse_task_id, d.parse_engine, d.parse_error, d.failed_pages,
                  d.clean_status, d.clean_error,
                  d.chunk_status, d.chunk_count, d.segment_count,
                  d.summary, d.keywords, d.metadata, d.metadata_tagged,
                  d.quality_score, d.quality_signals,
                  d.date_published, d.search_hit_count,
                  d.status, d.ext_info, d.delete_flg,
                  d.created_at, d.created_by, d.updated_at, d.updated_by))

    @staticmethod
    def get_by_doc_id(doc_id: str) -> KnowledgeDocumentRow | None:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ai_knowledge_document WHERE doc_id=%s AND delete_flg=0",
                        (doc_id,))
            row = cur.fetchone()
            return _row_to_model(cur.description, row, KnowledgeDocumentRow) if row else None

    @staticmethod
    def find_by_hash(tenant_id: int, knowledge_base_id: int,
                     file_hash: str) -> KnowledgeDocumentRow | None:
        """按 file_hash 查找（走 uk_doc_hash 唯一索引）"""
        if not file_hash:
            return None
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM ai_knowledge_document
                WHERE tenant_id=%s AND knowledge_base_id=%s
                  AND file_hash=%s AND delete_flg=0
            """, (tenant_id, knowledge_base_id, file_hash))
            row = cur.fetchone()
            return _row_to_model(cur.description, row, KnowledgeDocumentRow) if row else None

    @staticmethod
    def lock_by_hash_nowait(tenant_id: int, knowledge_base_id: int,
                            file_hash: str) -> KnowledgeDocumentRow | None:
        """行锁版 find_by_hash — 用 FOR UPDATE NOWAIT 防止并发入库

        需要在调用方的事务内使用（with get_conn() 外层管理事务）。
        如果被其他事务锁住会抛 psycopg2.errors.LockNotAvailable。
        """
        if not file_hash:
            return None
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM ai_knowledge_document
                WHERE tenant_id=%s AND knowledge_base_id=%s
                  AND file_hash=%s AND delete_flg=0
                FOR UPDATE NOWAIT
            """, (tenant_id, knowledge_base_id, file_hash))
            row = cur.fetchone()
            return _row_to_model(cur.description, row, KnowledgeDocumentRow) if row else None

    @staticmethod
    def list_by_kb(tenant_id: int, knowledge_base_id: int,
                   limit: int = 50, offset: int = 0) -> list[KnowledgeDocumentRow]:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM ai_knowledge_document
                WHERE tenant_id=%s AND knowledge_base_id=%s AND delete_flg=0
                ORDER BY created_at DESC LIMIT %s OFFSET %s
            """, (tenant_id, knowledge_base_id, limit, offset))
            return [_row_to_model(cur.description, r, KnowledgeDocumentRow)
                    for r in cur.fetchall()]

    @staticmethod
    def update_parse_status(doc_id: str, parse_status: str,
                            parse_task_id: str = "", parse_error: str = "",
                            parsed_md_url: str = "", parsed_json_url: str = "",
                            page_count: int = 0, total_chars: int = 0) -> None:
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute("""
                UPDATE ai_knowledge_document
                SET parse_status = %s,
                    parse_task_id = COALESCE(NULLIF(%s, ''), parse_task_id),
                    parse_error = %s,
                    parsed_md_url = COALESCE(NULLIF(%s, ''), parsed_md_url),
                    parsed_json_url = COALESCE(NULLIF(%s, ''), parsed_json_url),
                    page_count = CASE WHEN %s > 0 THEN %s ELSE page_count END,
                    total_chars = CASE WHEN %s > 0 THEN %s ELSE total_chars END,
                    updated_at = %s
                WHERE doc_id = %s
            """, (parse_status, parse_task_id, parse_error[:5000],
                  parsed_md_url, parsed_json_url,
                  page_count, page_count, total_chars, total_chars,
                  now, doc_id))

    @staticmethod
    def update_clean_status(doc_id: str, clean_status: str,
                            clean_error: str = "") -> None:
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute("""
                UPDATE ai_knowledge_document
                SET clean_status = %s, clean_error = %s, updated_at = %s
                WHERE doc_id = %s
            """, (clean_status, clean_error[:5000], now, doc_id))

    @staticmethod
    def update_metadata(doc_id: str, summary: str, keywords: str,
                        metadata: str, quality_score: float,
                        quality_signals: str, date_published: int = 0) -> None:
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute("""
                UPDATE ai_knowledge_document
                SET summary = %s, keywords = %s, metadata = %s,
                    metadata_tagged = 1,
                    quality_score = %s, quality_signals = %s,
                    date_published = CASE WHEN %s > 0 THEN %s ELSE date_published END,
                    updated_at = %s
                WHERE doc_id = %s
            """, (summary, keywords, metadata,
                  quality_score, quality_signals,
                  date_published, date_published,
                  now, doc_id))

    @staticmethod
    def update_chunk_status(doc_id: str, chunk_status: str,
                            chunk_count: int = 0, segment_count: int = 0) -> None:
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute("""
                UPDATE ai_knowledge_document
                SET chunk_status = %s,
                    chunk_count = CASE WHEN %s > 0 THEN %s ELSE chunk_count END,
                    segment_count = CASE WHEN %s > 0 THEN %s ELSE segment_count END,
                    updated_at = %s
                WHERE doc_id = %s
            """, (chunk_status,
                  chunk_count, chunk_count,
                  segment_count, segment_count,
                  now, doc_id))

    @staticmethod
    def increment_hit(doc_id: str) -> None:
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute("""
                UPDATE ai_knowledge_document
                SET search_hit_count = search_hit_count + 1, updated_at = %s
                WHERE doc_id = %s
            """, (now, doc_id))

    @staticmethod
    def soft_delete(doc_id: str) -> bool:
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE ai_knowledge_document SET delete_flg=1, updated_at=%s
                WHERE doc_id=%s AND delete_flg=0
            """, (now, doc_id))
            return cur.rowcount > 0


# ═══════════════════════════════════════════════════════════
# KnowledgeSegmentDAO
# ═══════════════════════════════════════════════════════════

class KnowledgeSegmentDAO:

    @staticmethod
    def batch_insert(segments: list[KnowledgeSegmentRow]) -> None:
        if not segments:
            return
        with get_conn() as conn:
            cur = conn.cursor()
            args = [(s.segment_id, s.tenant_id, s.knowledge_base_id, s.doc_id,
                     s.title, s.section_path, s.content, s.content_tokens,
                     s.segment_index, s.heading_level, s.page_start, s.page_end,
                     s.start_offset, s.end_offset, s.chunk_count,
                     s.delete_flg, s.created_at, s.updated_at)
                    for s in segments]
            cur.executemany("""
                INSERT INTO ai_knowledge_segment
                (segment_id, tenant_id, knowledge_base_id, doc_id,
                 title, section_path, content, content_tokens,
                 segment_index, heading_level, page_start, page_end,
                 start_offset, end_offset, chunk_count,
                 delete_flg, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, args)

    @staticmethod
    def get_by_segment_id(segment_id: str) -> KnowledgeSegmentRow | None:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ai_knowledge_segment WHERE segment_id=%s AND delete_flg=0",
                        (segment_id,))
            row = cur.fetchone()
            return _row_to_model(cur.description, row, KnowledgeSegmentRow) if row else None

    @staticmethod
    def list_by_doc(doc_id: str) -> list[KnowledgeSegmentRow]:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM ai_knowledge_segment
                WHERE doc_id=%s AND delete_flg=0
                ORDER BY segment_index
            """, (doc_id,))
            return [_row_to_model(cur.description, r, KnowledgeSegmentRow)
                    for r in cur.fetchall()]

    @staticmethod
    def delete_by_doc(doc_id: str) -> int:
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE ai_knowledge_segment SET delete_flg=1, updated_at=%s
                WHERE doc_id=%s AND delete_flg=0
            """, (now, doc_id))
            return cur.rowcount


# ═══════════════════════════════════════════════════════════
# KnowledgeChunkDAO
# ═══════════════════════════════════════════════════════════

class KnowledgeChunkDAO:

    @staticmethod
    def batch_insert(chunks: list[KnowledgeChunkRow]) -> None:
        if not chunks:
            return
        with get_conn() as conn:
            cur = conn.cursor()
            args = [(c.chunk_id, c.tenant_id, c.knowledge_base_id, c.dataset_id, c.doc_id,
                     c.content, c.display_content, c.content_hash, c.content_tokens,
                     c.chunk_index, c.chunk_type, c.section_title, c.section_path,
                     c.page_number, c.start_offset, c.end_offset,
                     c.doc_category, c.industry, c.business_stage,
                     c.target_audience, c.product_service, c.date_published,
                     c.parent_chunk_id, c.parent_segment_id, c.is_summary,
                     c.vector_synced, c.vector_error, c.vector_retry_count,
                     c.embedding_model, c.embedding_dim,
                     c.hit_count, c.last_hit_at,
                     c.metadata, c.status, c.delete_flg,
                     c.created_at, c.updated_at)
                    for c in chunks]
            cur.executemany("""
                INSERT INTO ai_knowledge_chunk
                (chunk_id, tenant_id, knowledge_base_id, dataset_id, doc_id,
                 content, display_content, content_hash, content_tokens,
                 chunk_index, chunk_type, section_title, section_path,
                 page_number, start_offset, end_offset,
                 doc_category, industry, business_stage,
                 target_audience, product_service, date_published,
                 parent_chunk_id, parent_segment_id, is_summary,
                 vector_synced, vector_error, vector_retry_count,
                 embedding_model, embedding_dim,
                 hit_count, last_hit_at,
                 metadata, status, delete_flg,
                 created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s)
            """, args)

    @staticmethod
    def get_by_chunk_id(chunk_id: str) -> KnowledgeChunkRow | None:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ai_knowledge_chunk WHERE chunk_id=%s AND delete_flg=0",
                        (chunk_id,))
            row = cur.fetchone()
            return _row_to_model(cur.description, row, KnowledgeChunkRow) if row else None

    @staticmethod
    def get_by_chunk_ids(chunk_ids: list[str]) -> list[KnowledgeChunkRow]:
        """批量按 chunk_id 获取（检索命中后回填全文）"""
        if not chunk_ids:
            return []
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM ai_knowledge_chunk
                WHERE chunk_id = ANY(%s) AND delete_flg=0
            """, (chunk_ids,))
            return [_row_to_model(cur.description, r, KnowledgeChunkRow)
                    for r in cur.fetchall()]

    @staticmethod
    def list_by_doc(doc_id: str, start: int = 0, end: int = -1) -> list[KnowledgeChunkRow]:
        """按文档拉取切片（Parent-Child 扩展用）"""
        with get_conn() as conn:
            cur = conn.cursor()
            if end < 0:
                cur.execute("""
                    SELECT * FROM ai_knowledge_chunk
                    WHERE doc_id=%s AND chunk_index>=%s AND delete_flg=0
                    ORDER BY chunk_index
                """, (doc_id, start))
            else:
                cur.execute("""
                    SELECT * FROM ai_knowledge_chunk
                    WHERE doc_id=%s AND chunk_index BETWEEN %s AND %s AND delete_flg=0
                    ORDER BY chunk_index
                """, (doc_id, start, end))
            return [_row_to_model(cur.description, r, KnowledgeChunkRow)
                    for r in cur.fetchall()]

    @staticmethod
    def list_by_segment(segment_id: str) -> list[KnowledgeChunkRow]:
        """按 Segment 拉取所有切片（Parent-Child 重扩展用）"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM ai_knowledge_chunk
                WHERE parent_segment_id=%s AND delete_flg=0
                ORDER BY chunk_index
            """, (segment_id,))
            return [_row_to_model(cur.description, r, KnowledgeChunkRow)
                    for r in cur.fetchall()]

    @staticmethod
    def list_pending_vector_sync(limit: int = 100) -> list[KnowledgeChunkRow]:
        """补偿任务：查未同步到向量库的切片（vector_synced IN (0, 2)）"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM ai_knowledge_chunk
                WHERE vector_synced IN (0, 2) AND delete_flg=0
                ORDER BY updated_at
                LIMIT %s
            """, (limit,))
            return [_row_to_model(cur.description, r, KnowledgeChunkRow)
                    for r in cur.fetchall()]

    @staticmethod
    def mark_vector_synced(chunk_ids: list[str],
                           embedding_model: str, embedding_dim: int) -> None:
        if not chunk_ids:
            return
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute("""
                UPDATE ai_knowledge_chunk
                SET vector_synced = 1,
                    vector_error = '',
                    embedding_model = %s,
                    embedding_dim = %s,
                    updated_at = %s
                WHERE chunk_id = ANY(%s)
            """, (embedding_model, embedding_dim, now, chunk_ids))

    @staticmethod
    def mark_vector_failed(chunk_id: str, error: str,
                           max_retry: int = 5) -> None:
        """向量同步失败 — 递增 retry_count，超过 max_retry 进死信 (vector_synced=3)"""
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute("""
                UPDATE ai_knowledge_chunk
                SET vector_synced = CASE
                        WHEN vector_retry_count + 1 >= %s THEN 3
                        ELSE 2
                    END,
                    vector_retry_count = vector_retry_count + 1,
                    vector_error = %s,
                    updated_at = %s
                WHERE chunk_id = %s
            """, (max_retry, error[:500], now, chunk_id))

    @staticmethod
    def increment_hit(chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute("""
                UPDATE ai_knowledge_chunk
                SET hit_count = hit_count + 1, last_hit_at = %s
                WHERE chunk_id = ANY(%s)
            """, (now, chunk_ids))

    @staticmethod
    def delete_by_doc(doc_id: str) -> int:
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE ai_knowledge_chunk SET delete_flg=1, updated_at=%s
                WHERE doc_id=%s AND delete_flg=0
            """, (now, doc_id))
            return cur.rowcount


# ═══════════════════════════════════════════════════════════
# KnowledgeIngestQueueDAO — PG 任务队列
# 基于 FOR UPDATE SKIP LOCKED，无 MQ/Redis 依赖
# ═══════════════════════════════════════════════════════════

class KnowledgeIngestQueueDAO:

    @staticmethod
    def enqueue(q: KnowledgeIngestQueueRow) -> bool:
        """入队，依赖 uk_queue_task 保证幂等。返回是否新插入。"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO ai_knowledge_ingest_queue
                (task_id, tenant_id, knowledge_base_id, dataset_id,
                 payload, status, priority, available_at,
                 picked_at, picked_by, completed_at,
                 retry_count, max_retry, last_error,
                 visibility_timeout_ms, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (task_id) DO NOTHING
            """, (q.task_id, q.tenant_id, q.knowledge_base_id, q.dataset_id,
                  q.payload, q.status, q.priority, q.available_at,
                  q.picked_at, q.picked_by, q.completed_at,
                  q.retry_count, q.max_retry, q.last_error,
                  q.visibility_timeout_ms, q.created_at, q.updated_at))
            return cur.rowcount > 0

    @staticmethod
    def dequeue(worker_id: str, batch: int = 1) -> list[KnowledgeIngestQueueRow]:
        """出队 — 核心 SQL：FOR UPDATE SKIP LOCKED

        多 Worker 并发调用本方法是安全的，PG 自动分配不冲突的行。
        """
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE ai_knowledge_ingest_queue
                SET status = 'running',
                    picked_at = %s,
                    picked_by = %s,
                    updated_at = %s
                WHERE id IN (
                    SELECT id FROM ai_knowledge_ingest_queue
                    WHERE status = 'pending' AND available_at <= %s
                    ORDER BY priority DESC, id
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *
            """, (now, worker_id, now, now, batch))
            return [_row_to_model(cur.description, r, KnowledgeIngestQueueRow)
                    for r in cur.fetchall()]

    @staticmethod
    def ack(task_id: str) -> None:
        """任务成功"""
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute("""
                UPDATE ai_knowledge_ingest_queue
                SET status = 'success',
                    completed_at = %s,
                    updated_at = %s
                WHERE task_id = %s
            """, (now, now, task_id))

    @staticmethod
    def nack(task_id: str, error: str) -> None:
        """任务失败 — 指数退避重试（2^retry × 60s），耗尽后进死信"""
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute("""
                UPDATE ai_knowledge_ingest_queue
                SET status = CASE
                        WHEN retry_count + 1 >= max_retry THEN 'dead'
                        ELSE 'pending'
                    END,
                    retry_count = retry_count + 1,
                    available_at = %s + (POWER(2, retry_count) * 60 * 1000)::BIGINT,
                    last_error = %s,
                    updated_at = %s
                WHERE task_id = %s AND status = 'running'
            """, (now, error[:2000], now, task_id))

    @staticmethod
    def reclaim_stuck() -> int:
        """回收 running 超过 visibility_timeout 的任务（Worker 崩溃场景）

        将 status 从 running 复位为 pending，available_at 改为立即可执行。
        建议每 30s 调用一次。
        """
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE ai_knowledge_ingest_queue
                SET status = 'pending',
                    picked_by = '',
                    available_at = %s,
                    updated_at = %s
                WHERE status = 'running'
                  AND picked_at + visibility_timeout_ms < %s
            """, (now, now, now))
            return cur.rowcount

    @staticmethod
    def get_by_task_id(task_id: str) -> KnowledgeIngestQueueRow | None:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ai_knowledge_ingest_queue WHERE task_id=%s",
                        (task_id,))
            row = cur.fetchone()
            return _row_to_model(cur.description, row, KnowledgeIngestQueueRow) if row else None

    @staticmethod
    def stats_by_status(tenant_id: int = 0) -> dict[str, int]:
        """各状态任务数量统计（运维可视化用）"""
        with get_conn() as conn:
            cur = conn.cursor()
            if tenant_id:
                cur.execute("""
                    SELECT status, COUNT(*) FROM ai_knowledge_ingest_queue
                    WHERE tenant_id = %s
                    GROUP BY status
                """, (tenant_id,))
            else:
                cur.execute("""
                    SELECT status, COUNT(*) FROM ai_knowledge_ingest_queue
                    GROUP BY status
                """)
            return {row[0]: row[1] for row in cur.fetchall()}


# ═══════════════════════════════════════════════════════════
# KnowledgeIngestLogDAO
# ═══════════════════════════════════════════════════════════

class KnowledgeIngestLogDAO:

    @staticmethod
    def insert(log: KnowledgeIngestLogRow) -> None:
        with get_conn() as conn:
            conn.cursor().execute("""
                INSERT INTO ai_knowledge_ingest_log
                (id, tenant_id, knowledge_base_id, dataset_id, doc_id,
                 task_id, file_name, file_size, file_type,
                 phase, status, progress,
                 parse_duration_ms, clean_duration_ms, tagging_duration_ms,
                 split_duration_ms, index_duration_ms, total_duration_ms,
                 total_chars, segment_count, chunk_count, vector_count,
                 quality_score, error_message, retry_count,
                 start_time, end_time, delete_flg,
                 created_at, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (log.id, log.tenant_id, log.knowledge_base_id, log.dataset_id, log.doc_id,
                  log.task_id, log.file_name, log.file_size, log.file_type,
                  log.phase, log.status, log.progress,
                  log.parse_duration_ms, log.clean_duration_ms, log.tagging_duration_ms,
                  log.split_duration_ms, log.index_duration_ms, log.total_duration_ms,
                  log.total_chars, log.segment_count, log.chunk_count, log.vector_count,
                  log.quality_score, log.error_message, log.retry_count,
                  log.start_time, log.end_time, log.delete_flg,
                  log.created_at, log.created_by))

    @staticmethod
    def update_phase(task_id: str, phase: str, progress: int,
                     duration_field: str | None = None,
                     duration_ms: int = 0) -> None:
        """更新任务阶段和进度；可选累加某阶段耗时"""
        now = int(time.time() * 1000)
        set_parts = ["phase = %s", "progress = %s"]
        args: list[Any] = [phase, progress]
        if duration_field and duration_ms > 0:
            # 白名单防 SQL 注入
            allowed = {
                "parse_duration_ms", "clean_duration_ms", "tagging_duration_ms",
                "split_duration_ms", "index_duration_ms",
            }
            if duration_field in allowed:
                set_parts.append(f"{duration_field} = {duration_field} + %s")
                args.append(duration_ms)
        args.append(task_id)
        sql = f"UPDATE ai_knowledge_ingest_log SET {', '.join(set_parts)} WHERE task_id = %s"
        with get_conn() as conn:
            conn.cursor().execute(sql, tuple(args))

    @staticmethod
    def finish(task_id: str, status: str, error_message: str = "",
               total_chars: int = 0, segment_count: int = 0,
               chunk_count: int = 0, vector_count: int = 0,
               quality_score: float = 0.0) -> None:
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute("""
                UPDATE ai_knowledge_ingest_log
                SET status = %s,
                    progress = CASE WHEN %s = 'success' THEN 100 ELSE progress END,
                    phase = CASE WHEN %s = 'success' THEN 'done' ELSE 'failed' END,
                    error_message = %s,
                    total_chars = CASE WHEN %s > 0 THEN %s ELSE total_chars END,
                    segment_count = CASE WHEN %s > 0 THEN %s ELSE segment_count END,
                    chunk_count = CASE WHEN %s > 0 THEN %s ELSE chunk_count END,
                    vector_count = CASE WHEN %s > 0 THEN %s ELSE vector_count END,
                    quality_score = CASE WHEN %s > 0 THEN %s ELSE quality_score END,
                    end_time = %s,
                    total_duration_ms = %s - start_time
                WHERE task_id = %s
            """, (status, status, status, error_message[:2000],
                  total_chars, total_chars,
                  segment_count, segment_count,
                  chunk_count, chunk_count,
                  vector_count, vector_count,
                  quality_score, quality_score,
                  now, now, task_id))

    @staticmethod
    def get_by_task_id(task_id: str) -> KnowledgeIngestLogRow | None:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ai_knowledge_ingest_log WHERE task_id=%s AND delete_flg=0",
                        (task_id,))
            row = cur.fetchone()
            return _row_to_model(cur.description, row, KnowledgeIngestLogRow) if row else None


# ═══════════════════════════════════════════════════════════
# KnowledgeSearchLogDAO
# ═══════════════════════════════════════════════════════════

class KnowledgeSearchLogDAO:

    @staticmethod
    def insert(log: KnowledgeSearchLogRow) -> None:
        with get_conn() as conn:
            conn.cursor().execute("""
                INSERT INTO ai_knowledge_search_log
                (id, tenant_id, knowledge_base_id, user_id, thread_id, trace_id,
                 raw_query, rewritten_query, semantic_query, filters,
                 hit_chunk_ids, hit_count, top_score, vector_hit_count, bm25_hit_count,
                 rewrite_ms, self_query_ms, vector_search_ms, bm25_search_ms,
                 rerank_ms, total_ms,
                 user_feedback, feedback_comment, delete_flg, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (log.id, log.tenant_id, log.knowledge_base_id,
                  log.user_id, log.thread_id, log.trace_id,
                  log.raw_query, log.rewritten_query, log.semantic_query, log.filters,
                  log.hit_chunk_ids, log.hit_count, log.top_score,
                  log.vector_hit_count, log.bm25_hit_count,
                  log.rewrite_ms, log.self_query_ms, log.vector_search_ms,
                  log.bm25_search_ms, log.rerank_ms, log.total_ms,
                  log.user_feedback, log.feedback_comment,
                  log.delete_flg, log.created_at))

    @staticmethod
    def update_feedback(trace_id: str, user_feedback: str,
                        feedback_comment: str = "") -> bool:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE ai_knowledge_search_log
                SET user_feedback = %s, feedback_comment = %s
                WHERE trace_id = %s
            """, (user_feedback, feedback_comment[:2000], trace_id))
            return cur.rowcount > 0


# ═══════════════════════════════════════════════════════════
# 通用行映射
# ═══════════════════════════════════════════════════════════

def _row_to_model(desc, row, cls):
    """将数据库行映射为 dataclass 实例（复用 dao.py 的模式）

    注意：psycopg2 对 DECIMAL 列默认返回 Decimal，dataclass 期望 float 时需要显式转换。
    dataclass 字段的 type 存储为字符串注解或类型对象（依赖 from __future__ import annotations）。
    """
    if row is None:
        return None
    col_names = [d[0] for d in desc]
    fields_by_name = {f.name: f for f in dataclasses.fields(cls)}
    kwargs = {}
    for i, name in enumerate(col_names):
        if name not in fields_by_name:
            continue
        val = row[i]
        field_def = fields_by_name[name]
        # 处理 DECIMAL → float：type 既可能是 "float" 字符串，也可能是 float 类型对象
        if val is not None and field_def.type in (float, "float"):
            val = float(val)
        kwargs[name] = val
    return cls(**kwargs)
