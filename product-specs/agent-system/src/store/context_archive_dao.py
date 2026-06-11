"""上下文压缩存档 DAO — ai_context_archive 表的 CRUD 操作

设计原则:
  1. 原文持久化 — 不再依赖 Checkpointer Redis 24h TTL，原始消息直接存入 PG
  2. 数据时效性 — 每条存档带 data_timestamp，恢复时标注数据年龄
  3. 多信号检索 — 支持 turn_id 精确查询、关键词模糊匹配、实体搜索
  4. 租户隔离 — 所有查询强制 tenant_id 条件
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .pg_pool import get_conn
from .context_archive_models import ContextArchiveRow

logger = logging.getLogger(__name__)


class ContextArchiveDAO:
    """ai_context_archive 表访问层"""

    @staticmethod
    def insert(row: ContextArchiveRow) -> None:
        """插入单条存档记录"""
        with get_conn() as conn:
            conn.cursor().execute("""
                INSERT INTO ai_context_archive
                (id, tenant_id, thread_id, turn_id,
                 user_query, answer_preview, entities, keywords,
                 tool_names, skill_names, tool_summaries, key_data,
                 message_count, message_range_start, message_range_end,
                 original_messages, data_timestamp, archived_at,
                 delete_flg, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                row.id, row.tenant_id, row.thread_id, row.turn_id,
                row.user_query, row.answer_preview, row.entities, row.keywords,
                row.tool_names, row.skill_names, row.tool_summaries, row.key_data,
                row.message_count, row.message_range_start, row.message_range_end,
                row.original_messages, row.data_timestamp, row.archived_at,
                row.delete_flg, row.created_at,
            ))

    @staticmethod
    def batch_insert(rows: list[ContextArchiveRow]) -> None:
        """批量插入存档记录（一次压缩可能产生多个轮次）"""
        if not rows:
            return
        with get_conn() as conn:
            cur = conn.cursor()
            args = [(
                r.id, r.tenant_id, r.thread_id, r.turn_id,
                r.user_query, r.answer_preview, r.entities, r.keywords,
                r.tool_names, r.skill_names, r.tool_summaries, r.key_data,
                r.message_count, r.message_range_start, r.message_range_end,
                r.original_messages, r.data_timestamp, r.archived_at,
                r.delete_flg, r.created_at,
            ) for r in rows]
            cur.executemany("""
                INSERT INTO ai_context_archive
                (id, tenant_id, thread_id, turn_id,
                 user_query, answer_preview, entities, keywords,
                 tool_names, skill_names, tool_summaries, key_data,
                 message_count, message_range_start, message_range_end,
                 original_messages, data_timestamp, archived_at,
                 delete_flg, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, args)

    @staticmethod
    def get_by_turn_id(tenant_id: int, thread_id: str, turn_id: int) -> ContextArchiveRow | None:
        """按 turn_id 精确查询"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM ai_context_archive
                WHERE tenant_id=%s AND thread_id=%s AND turn_id=%s AND delete_flg=0
            """, (tenant_id, thread_id, turn_id))
            row = cur.fetchone()
            if not row:
                return None
            return _row_to_model(cur.description, row)

    @staticmethod
    def list_by_thread(tenant_id: int, thread_id: str, limit: int = 100) -> list[ContextArchiveRow]:
        """获取会话的所有存档记录（按 turn_id 升序）"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM ai_context_archive
                WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0
                ORDER BY turn_id ASC LIMIT %s
            """, (tenant_id, thread_id, limit))
            return [_row_to_model(cur.description, r) for r in cur.fetchall()]

    @staticmethod
    def search_by_keywords(
        tenant_id: int, thread_id: str, keywords: list[str], top_k: int = 5
    ) -> list[ContextArchiveRow]:
        """按关键词模糊搜索（利用 PG 的 LIKE + 评分排序）

        搜索范围: user_query, entities, keywords, tool_names, skill_names
        """
        if not keywords:
            return []

        with get_conn() as conn:
            cur = conn.cursor()
            # 构建 OR 条件（每个关键词匹配多个字段）
            conditions = []
            params: list[Any] = [tenant_id, thread_id]
            for kw in keywords[:10]:  # 限制关键词数量防止 SQL 过长
                kw_pattern = f"%{kw}%"
                conditions.append(
                    "(user_query ILIKE %s OR entities ILIKE %s "
                    "OR keywords ILIKE %s OR tool_names ILIKE %s "
                    "OR skill_names ILIKE %s OR answer_preview ILIKE %s)"
                )
                params.extend([kw_pattern] * 6)

            where_clause = " OR ".join(conditions)
            cur.execute(f"""
                SELECT * FROM ai_context_archive
                WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0
                AND ({where_clause})
                ORDER BY turn_id DESC LIMIT %s
            """, params + [top_k])
            return [_row_to_model(cur.description, r) for r in cur.fetchall()]

    @staticmethod
    def search_by_entities(
        tenant_id: int, thread_id: str, entity_names: list[str], top_k: int = 5
    ) -> list[ContextArchiveRow]:
        """按实体名搜索"""
        if not entity_names:
            return []
        with get_conn() as conn:
            cur = conn.cursor()
            conditions = []
            params: list[Any] = [tenant_id, thread_id]
            for entity in entity_names[:10]:
                conditions.append("entities ILIKE %s")
                params.append(f"%{entity}%")

            where_clause = " OR ".join(conditions)
            cur.execute(f"""
                SELECT * FROM ai_context_archive
                WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0
                AND ({where_clause})
                ORDER BY turn_id DESC LIMIT %s
            """, params + [top_k])
            return [_row_to_model(cur.description, r) for r in cur.fetchall()]

    @staticmethod
    def get_max_turn_id(tenant_id: int, thread_id: str) -> int:
        """获取当前会话最大 turn_id（用于自增）"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT COALESCE(MAX(turn_id), 0)
                FROM ai_context_archive
                WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0
            """, (tenant_id, thread_id))
            return cur.fetchone()[0]

    @staticmethod
    def delete_by_thread(tenant_id: int, thread_id: str) -> int:
        """软删除会话所有存档（会话结束时调用）"""
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE ai_context_archive SET delete_flg=1
                WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0
            """, (tenant_id, thread_id))
            return cur.rowcount


def _row_to_model(desc, row) -> ContextArchiveRow:
    """将数据库行映射为 ContextArchiveRow"""
    import dataclasses
    col_names = [d[0] for d in desc]
    field_names = {f.name for f in dataclasses.fields(ContextArchiveRow)}
    kwargs = {}
    for i, name in enumerate(col_names):
        if name in field_names:
            kwargs[name] = row[i]
    return ContextArchiveRow(**kwargs)
