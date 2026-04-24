"""数据访问层 — 7 张表的 CRUD 操作"""
from __future__ import annotations

import json
import logging
from typing import Any

from .pg_pool import get_conn
from .models import (
    Conversation, Message, MessageExt, Trace, TraceSpan,
    ContentReviewLog, TokenUsage,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# ConversationDAO
# ═══════════════════════════════════════════════════════════

class ConversationDAO:

    @staticmethod
    def insert(c: Conversation) -> None:
        with get_conn() as conn:
            conn.cursor().execute("""
                INSERT INTO ai_conversation
                (id, tenant_id, user_id, thread_id, agent_name, title, summary,
                 model, status, message_count, total_tokens, total_cost,
                 last_message_at, ext_info, delete_flg, created_at, created_by, updated_at, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (c.id, c.tenant_id, c.user_id, c.thread_id, c.agent_name,
                  c.title, c.summary, c.model, c.status, c.message_count,
                  c.total_tokens, c.total_cost, c.last_message_at, c.ext_info,
                  c.delete_flg, c.created_at, c.created_by, c.updated_at, c.updated_by))

    @staticmethod
    def get_by_thread(tenant_id: int, thread_id: str) -> Conversation | None:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM ai_conversation WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0",
                (tenant_id, thread_id))
            row = cur.fetchone()
            if not row:
                return None
            return _row_to_conversation(cur.description, row)

    @staticmethod
    def update_after_message(conversation_id: int, tokens: int, cost: float, now: int) -> None:
        with get_conn() as conn:
            conn.cursor().execute("""
                UPDATE ai_conversation
                SET message_count = message_count + 1,
                    total_tokens = total_tokens + %s,
                    total_cost = total_cost + %s,
                    last_message_at = %s,
                    updated_at = %s
                WHERE id = %s
            """, (tokens, cost, now, now, conversation_id))

    @staticmethod
    def update_title(conversation_id: int, title: str, now: int) -> None:
        with get_conn() as conn:
            conn.cursor().execute(
                "UPDATE ai_conversation SET title=%s, updated_at=%s WHERE id=%s",
                (title, now, conversation_id))

    @staticmethod
    def list_by_user(tenant_id: int, user_id: int, limit: int = 50, offset: int = 0) -> list[Conversation]:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM ai_conversation
                WHERE tenant_id=%s AND user_id=%s AND delete_flg=0
                ORDER BY last_message_at DESC LIMIT %s OFFSET %s
            """, (tenant_id, user_id, limit, offset))
            return [_row_to_conversation(cur.description, r) for r in cur.fetchall()]



# ═══════════════════════════════════════════════════════════
# MessageDAO
# ═══════════════════════════════════════════════════════════

class MessageDAO:

    @staticmethod
    def insert(m: Message) -> None:
        with get_conn() as conn:
            conn.cursor().execute("""
                INSERT INTO ai_message
                (id, tenant_id, conversation_id, thread_id, sequence, role,
                 query, answer, masked_query, masked_answer, model,
                 input_tokens, output_tokens, total_tokens,
                 iteration_count, tool_count, duration_ms, trace_id,
                 status, error_message, ext_info, delete_flg,
                 created_at, created_by, updated_at, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (m.id, m.tenant_id, m.conversation_id, m.thread_id, m.sequence,
                  m.role, m.query, m.answer, m.masked_query, m.masked_answer,
                  m.model, m.input_tokens, m.output_tokens, m.total_tokens,
                  m.iteration_count, m.tool_count, m.duration_ms, m.trace_id,
                  m.status, m.error_message, m.ext_info, m.delete_flg,
                  m.created_at, m.created_by, m.updated_at, m.updated_by))

    @staticmethod
    def list_by_conversation(conversation_id: int, limit: int = 100) -> list[Message]:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM ai_message
                WHERE conversation_id=%s AND delete_flg=0
                ORDER BY sequence ASC LIMIT %s
            """, (conversation_id, limit))
            return [_row_to_model(cur.description, r, Message) for r in cur.fetchall()]

    @staticmethod
    def get_next_sequence(conversation_id: int) -> int:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM ai_message WHERE conversation_id=%s",
                (conversation_id,))
            return cur.fetchone()[0]


# ═══════════════════════════════════════════════════════════
# MessageExtDAO
# ═══════════════════════════════════════════════════════════

class MessageExtDAO:

    @staticmethod
    def insert(e: MessageExt) -> None:
        with get_conn() as conn:
            conn.cursor().execute("""
                INSERT INTO ai_message_ext
                (id, tenant_id, message_id, ext_type, ext_data, status, delete_flg, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (e.id, e.tenant_id, e.message_id, e.ext_type, e.ext_data,
                  e.status, e.delete_flg, e.created_at, e.updated_at))

    @staticmethod
    def list_by_message(message_id: int) -> list[MessageExt]:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM ai_message_ext WHERE message_id=%s AND delete_flg=0",
                (message_id,))
            return [_row_to_model(cur.description, r, MessageExt) for r in cur.fetchall()]


# ═══════════════════════════════════════════════════════════
# TraceDAO
# ═══════════════════════════════════════════════════════════

class TraceDAO:

    @staticmethod
    def insert(t: Trace) -> None:
        with get_conn() as conn:
            conn.cursor().execute("""
                INSERT INTO ai_trace
                (id, tenant_id, trace_id, thread_id, message_id, user_input, agent_output,
                 model, agent_name, status, total_tokens, total_cost,
                 iteration_count, tool_count, span_count, duration_ms,
                 start_time, end_time, ext_info, delete_flg, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (t.id, t.tenant_id, t.trace_id, t.thread_id, t.message_id,
                  t.user_input, t.agent_output, t.model, t.agent_name, t.status,
                  t.total_tokens, t.total_cost, t.iteration_count, t.tool_count,
                  t.span_count, t.duration_ms, t.start_time, t.end_time,
                  t.ext_info, t.delete_flg, t.created_at, t.updated_at))

    @staticmethod
    def finish(trace_id: str, status: str, agent_output: str,
               total_tokens: int, duration_ms: int, iteration_count: int,
               tool_count: int, span_count: int, now: int) -> None:
        with get_conn() as conn:
            conn.cursor().execute("""
                UPDATE ai_trace
                SET status=%s, agent_output=%s, total_tokens=%s, duration_ms=%s,
                    iteration_count=%s, tool_count=%s, span_count=%s,
                    end_time=%s, updated_at=%s
                WHERE trace_id=%s
            """, (status, agent_output[:5000], total_tokens, duration_ms,
                  iteration_count, tool_count, span_count, now, now, trace_id))

    @staticmethod
    def get_by_trace_id(trace_id: str) -> Trace | None:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM ai_trace WHERE trace_id=%s AND delete_flg=0", (trace_id,))
            row = cur.fetchone()
            if not row:
                return None
            return _row_to_model(cur.description, row, Trace)

    @staticmethod
    def list_by_thread(tenant_id: int, thread_id: str, limit: int = 50) -> list[Trace]:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM ai_trace
                WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0
                ORDER BY start_time DESC LIMIT %s
            """, (tenant_id, thread_id, limit))
            return [_row_to_model(cur.description, r, Trace) for r in cur.fetchall()]


# ═══════════════════════════════════════════════════════════
# TraceSpanDAO
# ═══════════════════════════════════════════════════════════

class TraceSpanDAO:

    @staticmethod
    def insert(s: TraceSpan) -> None:
        with get_conn() as conn:
            conn.cursor().execute("""
                INSERT INTO ai_trace_span
                (id, tenant_id, trace_id, span_id, parent_span_id, source, span_type, span_name,
                 status, duration_ms, start_time, end_time,
                 input_data, output_data, metadata, delete_flg, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (s.id, s.tenant_id, s.trace_id, s.span_id, s.parent_span_id,
                  s.source, s.span_type, s.span_name, s.status, s.duration_ms,
                  s.start_time, s.end_time, s.input_data, s.output_data,
                  s.metadata, s.delete_flg, s.created_at))

    @staticmethod
    def batch_insert(spans: list[TraceSpan]) -> None:
        if not spans:
            return
        with get_conn() as conn:
            cur = conn.cursor()
            args = [(s.id, s.tenant_id, s.trace_id, s.span_id, s.parent_span_id,
                     s.source, s.span_type, s.span_name, s.status, s.duration_ms,
                     s.start_time, s.end_time, s.input_data, s.output_data,
                     s.metadata, s.delete_flg, s.created_at) for s in spans]
            cur.executemany("""
                INSERT INTO ai_trace_span
                (id, tenant_id, trace_id, span_id, parent_span_id, source, span_type, span_name,
                 status, duration_ms, start_time, end_time,
                 input_data, output_data, metadata, delete_flg, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, args)

    @staticmethod
    def list_by_trace(trace_id: str) -> list[TraceSpan]:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM ai_trace_span WHERE trace_id=%s ORDER BY start_time",
                (trace_id,))
            return [_row_to_model(cur.description, r, TraceSpan) for r in cur.fetchall()]


# ═══════════════════════════════════════════════════════════
# ContentReviewLogDAO
# ═══════════════════════════════════════════════════════════

class ContentReviewLogDAO:

    @staticmethod
    def insert(log: ContentReviewLog) -> None:
        with get_conn() as conn:
            conn.cursor().execute("""
                INSERT INTO ai_content_review_log
                (id, tenant_id, thread_id, message_id, review_type,
                 original_content, blocked_keywords, blocked_reason, rule_id,
                 delete_flg, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (log.id, log.tenant_id, log.thread_id, log.message_id,
                  log.review_type, log.original_content, log.blocked_keywords,
                  log.blocked_reason, log.rule_id, log.delete_flg, log.created_at))


# ═══════════════════════════════════════════════════════════
# TokenUsageDAO
# ═══════════════════════════════════════════════════════════

class TokenUsageDAO:

    @staticmethod
    def insert(u: TokenUsage) -> None:
        with get_conn() as conn:
            conn.cursor().execute("""
                INSERT INTO ai_token_usage
                (id, tenant_id, user_id, conversation_id, thread_id, trace_id,
                 model, input_tokens, output_tokens, total_tokens, cost, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (u.id, u.tenant_id, u.user_id, u.conversation_id, u.thread_id,
                  u.trace_id, u.model, u.input_tokens, u.output_tokens,
                  u.total_tokens, u.cost, u.created_at))

    @staticmethod
    def sum_by_user(tenant_id: int, user_id: int) -> dict:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT COALESCE(SUM(total_tokens), 0), COALESCE(SUM(cost), 0)
                FROM ai_token_usage WHERE tenant_id=%s AND user_id=%s
            """, (tenant_id, user_id))
            row = cur.fetchone()
            return {"total_tokens": row[0], "total_cost": float(row[1])}


# ═══════════════════════════════════════════════════════════
# 通用行映射
# ═══════════════════════════════════════════════════════════

def _row_to_conversation(desc, row) -> Conversation:
    return _row_to_model(desc, row, Conversation)


def _row_to_model(desc, row, cls):
    """将数据库行映射为 dataclass 实例"""
    col_names = [d[0] for d in desc]
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(cls)}
    kwargs = {}
    for i, name in enumerate(col_names):
        if name in field_names:
            kwargs[name] = row[i]
    return cls(**kwargs)
