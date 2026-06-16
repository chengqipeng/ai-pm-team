"""上下文存档 DAO — Legacy PG 实现（已废弃）

注意: ContextArchive 已迁移到纯 VDB 存储（见 src/middleware/context_archive.py）。
本 DAO 保留用于:
  1. 测试代码中 Mock 替换的目标模块
  2. 未来可能的 PG 备份/审计写入
  3. 兼容 __init__.py 导出

生产环境不再调用本模块的方法，所有读写通过 VDB 完成。
"""
from __future__ import annotations

import logging
from typing import Optional

from .context_archive_models import ContextArchiveRow
from .pg_pool import get_conn
from .snowflake import next_id

logger = logging.getLogger(__name__)


class ContextArchiveDAO:
    """上下文存档 CRUD — ai_context_archive 表（Legacy）"""

    @staticmethod
    def batch_insert(rows: list[ContextArchiveRow]) -> None:
        """批量写入存档行"""
        if not rows:
            return
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    for row in rows:
                        cur.execute("""
                            INSERT INTO ai_context_archive
                                (id, tenant_id, thread_id, turn_id, user_query,
                                 answer_preview, entities, keywords, tool_names,
                                 skill_names, tool_summaries, key_data,
                                 original_messages_json, message_count,
                                 message_range_start, message_range_end,
                                 has_decision, decision_fields, task_id,
                                 data_timestamp, delete_flg, created_at, updated_at)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """, (
                            row.id, row.tenant_id, row.thread_id, row.turn_id,
                            row.user_query, row.answer_preview, row.entities,
                            row.keywords, row.tool_names, row.skill_names,
                            row.tool_summaries, row.key_data,
                            row.original_messages_json, row.message_count,
                            row.message_range_start, row.message_range_end,
                            row.has_decision, row.decision_fields, row.task_id,
                            row.data_timestamp, row.delete_flg,
                            row.created_at, row.updated_at,
                        ))
        except Exception as e:
            logger.warning("[ContextArchiveDAO] batch_insert 失败: %s", e)

    @staticmethod
    def get_max_turn_id(tenant_id: int, thread_id: str) -> int:
        """获取当前会话最大 turn_id"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT COALESCE(MAX(turn_id), 0)
                        FROM ai_context_archive
                        WHERE tenant_id = %s AND thread_id = %s AND delete_flg = 0
                    """, (tenant_id, thread_id))
                    row = cur.fetchone()
                    return row[0] if row else 0
        except Exception as e:
            logger.warning("[ContextArchiveDAO] get_max_turn_id 失败: %s", e)
            return 0

    @staticmethod
    def get_by_turn_id(tenant_id: int, thread_id: str, turn_id: int) -> Optional[ContextArchiveRow]:
        """按 turn_id 精确获取"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, tenant_id, thread_id, turn_id, user_query,
                               answer_preview, entities, keywords, tool_names,
                               skill_names, tool_summaries, key_data,
                               original_messages_json, message_count,
                               message_range_start, message_range_end,
                               has_decision, decision_fields, task_id,
                               data_timestamp, delete_flg, created_at, updated_at
                        FROM ai_context_archive
                        WHERE tenant_id = %s AND thread_id = %s AND turn_id = %s
                          AND delete_flg = 0
                    """, (tenant_id, thread_id, turn_id))
                    row = cur.fetchone()
                    return _row_to_model(row) if row else None
        except Exception as e:
            logger.warning("[ContextArchiveDAO] get_by_turn_id 失败: %s", e)
            return None

    @staticmethod
    def list_by_thread(tenant_id: int, thread_id: str, limit: int = 100) -> list[ContextArchiveRow]:
        """按会话列出所有存档（按 turn_id 升序）"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, tenant_id, thread_id, turn_id, user_query,
                               answer_preview, entities, keywords, tool_names,
                               skill_names, tool_summaries, key_data,
                               original_messages_json, message_count,
                               message_range_start, message_range_end,
                               has_decision, decision_fields, task_id,
                               data_timestamp, delete_flg, created_at, updated_at
                        FROM ai_context_archive
                        WHERE tenant_id = %s AND thread_id = %s AND delete_flg = 0
                        ORDER BY turn_id ASC
                        LIMIT %s
                    """, (tenant_id, thread_id, limit))
                    return [_row_to_model(r) for r in cur.fetchall()]
        except Exception as e:
            logger.warning("[ContextArchiveDAO] list_by_thread 失败: %s", e)
            return []

    @staticmethod
    def search_by_keywords(tenant_id: int, thread_id: str,
                           keywords: list[str], top_k: int = 5) -> list[ContextArchiveRow]:
        """按关键词搜索（ILIKE 降级检索）"""
        if not keywords:
            return []
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    conditions = " OR ".join(
                        "user_query ILIKE %s OR entities ILIKE %s OR keywords ILIKE %s OR answer_preview ILIKE %s"
                        for _ in keywords
                    )
                    params: list = [tenant_id, thread_id]
                    for kw in keywords:
                        pattern = f"%{kw}%"
                        params.extend([pattern, pattern, pattern, pattern])
                    params.append(top_k)

                    cur.execute(f"""
                        SELECT id, tenant_id, thread_id, turn_id, user_query,
                               answer_preview, entities, keywords, tool_names,
                               skill_names, tool_summaries, key_data,
                               original_messages_json, message_count,
                               message_range_start, message_range_end,
                               has_decision, decision_fields, task_id,
                               data_timestamp, delete_flg, created_at, updated_at
                        FROM ai_context_archive
                        WHERE tenant_id = %s AND thread_id = %s AND delete_flg = 0
                          AND ({conditions})
                        ORDER BY turn_id DESC
                        LIMIT %s
                    """, params)
                    return [_row_to_model(r) for r in cur.fetchall()]
        except Exception as e:
            logger.warning("[ContextArchiveDAO] search_by_keywords 失败: %s", e)
            return []

    @staticmethod
    def search_by_entities(tenant_id: int, thread_id: str,
                           entity_names: list[str], top_k: int = 5) -> list[ContextArchiveRow]:
        """按实体名搜索"""
        if not entity_names:
            return []
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    conditions = " OR ".join("entities ILIKE %s" for _ in entity_names)
                    params: list = [tenant_id, thread_id]
                    for name in entity_names:
                        params.append(f"%{name}%")
                    params.append(top_k)

                    cur.execute(f"""
                        SELECT id, tenant_id, thread_id, turn_id, user_query,
                               answer_preview, entities, keywords, tool_names,
                               skill_names, tool_summaries, key_data,
                               original_messages_json, message_count,
                               message_range_start, message_range_end,
                               has_decision, decision_fields, task_id,
                               data_timestamp, delete_flg, created_at, updated_at
                        FROM ai_context_archive
                        WHERE tenant_id = %s AND thread_id = %s AND delete_flg = 0
                          AND ({conditions})
                        ORDER BY turn_id DESC
                        LIMIT %s
                    """, params)
                    return [_row_to_model(r) for r in cur.fetchall()]
        except Exception as e:
            logger.warning("[ContextArchiveDAO] search_by_entities 失败: %s", e)
            return []

    @staticmethod
    def search_decisions(tenant_id: int, thread_id: str, top_k: int = 20) -> list[ContextArchiveRow]:
        """搜索包含决策的存档"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, tenant_id, thread_id, turn_id, user_query,
                               answer_preview, entities, keywords, tool_names,
                               skill_names, tool_summaries, key_data,
                               original_messages_json, message_count,
                               message_range_start, message_range_end,
                               has_decision, decision_fields, task_id,
                               data_timestamp, delete_flg, created_at, updated_at
                        FROM ai_context_archive
                        WHERE tenant_id = %s AND thread_id = %s
                          AND has_decision = 1 AND delete_flg = 0
                        ORDER BY turn_id ASC
                        LIMIT %s
                    """, (tenant_id, thread_id, top_k))
                    return [_row_to_model(r) for r in cur.fetchall()]
        except Exception as e:
            logger.warning("[ContextArchiveDAO] search_decisions 失败: %s", e)
            return []


# ═══════════════════════════════════════════════════════════
# 内部工具函数
# ═══════════════════════════════════════════════════════════

def _row_to_model(row) -> ContextArchiveRow:
    """将查询结果行转为 ContextArchiveRow"""
    if not row:
        return ContextArchiveRow()
    return ContextArchiveRow(
        id=row[0],
        tenant_id=row[1],
        thread_id=row[2],
        turn_id=row[3],
        user_query=row[4] or "",
        answer_preview=row[5] or "",
        entities=row[6] or "",
        keywords=row[7] or "",
        tool_names=row[8] or "",
        skill_names=row[9] or "",
        tool_summaries=row[10] or "[]",
        key_data=row[11] or "{}",
        original_messages_json=row[12] or "",
        message_count=row[13] or 0,
        message_range_start=row[14] or 0,
        message_range_end=row[15] or 0,
        has_decision=row[16] or 0,
        decision_fields=row[17] or "[]",
        task_id=row[18] or "",
        data_timestamp=row[19] or 0,
        delete_flg=row[20] or 0,
        created_at=row[21] or 0,
        updated_at=row[22] or 0,
    )
