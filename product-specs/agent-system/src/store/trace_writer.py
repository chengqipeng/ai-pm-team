"""TraceWriter — 将内存 Trace 持久化到 PG

设计原则：
- Agent 执行期间不写 PG（避免影响延迟）
- 执行完成后批量写入（一次 trace 的所有 span 一次性 INSERT）
- 写入失败不影响主流程（降级为仅内存，记录 error 日志）
- on_trace_finish 同时写入 ai_message（对话历史）+ ai_token_usage（用量统计）
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from .models import Trace as TraceModel, TraceSpan as TraceSpanModel, Message, TokenUsage
from .dao import TraceDAO, TraceSpanDAO, MessageDAO, TokenUsageDAO

logger = logging.getLogger(__name__)

# source 推断规则
_AGENT_TYPES = {'request', 'response', 'llm_call'}
_TOOL_TYPES = {'tool_call'}
_SKILL_TYPES = {'skill_select', 'skill_execute'}
_SUBAGENT_TYPES = {'subagent'}


def _infer_source(span_type: str) -> str:
    if span_type in _AGENT_TYPES:
        return 'agent'
    if span_type in _TOOL_TYPES:
        return 'tool'
    if span_type in _SKILL_TYPES:
        return 'skill'
    if span_type in _SUBAGENT_TYPES:
        return 'subagent'
    return 'middleware'


class TraceWriter:
    """将内存 Trace 对象持久化到 PG"""

    def __init__(self, tenant_id: int = 1) -> None:
        self._tenant_id = tenant_id
        self._user_id: int = 0  # 由请求上下文动态设置

    def on_trace_start(self, trace: Any) -> None:
        """trace 开始时写入 ai_trace（status=running）"""
        try:
            now = int(time.time() * 1000)
            t = TraceModel(
                tenant_id=self._tenant_id,
                trace_id=trace.trace_id,
                thread_id=trace.thread_id,
                user_input=trace.user_input[:5000] if trace.user_input else '',
                model=trace.model or '',
                agent_name=trace.agent_name or '',
                status='running',
                start_time=int(trace.start_time * 1000) if trace.start_time else now,
                created_at=now,
                updated_at=now,
            )
            TraceDAO.insert(t)
            logger.debug("TraceWriter: trace started %s", trace.trace_id)
        except Exception as e:
            logger.error("TraceWriter.on_trace_start failed: %s", e)

    def on_trace_finish(self, trace: Any) -> None:
        """trace 完成时：批量写入所有 span + 更新 trace"""
        try:
            now = int(time.time() * 1000)

            # 1. 批量写入所有 span
            span_models = []
            for s in trace.spans:
                # Normalize type
                span_type = s.type
                if hasattr(span_type, 'value'):
                    span_type = span_type.value
                elif isinstance(span_type, str) and span_type.startswith('SpanType.'):
                    span_type = span_type.split('.', 1)[1].lower()

                source = _infer_source(span_type)

                # Serialize metadata/input/output
                metadata = s.metadata if isinstance(s.metadata, str) else json.dumps(s.metadata or {}, ensure_ascii=False, default=str)
                input_data = s.input_data if isinstance(s.input_data, str) else json.dumps(s.input_data or {}, ensure_ascii=False, default=str)
                output_data = s.output_data if isinstance(s.output_data, str) else json.dumps(s.output_data or {}, ensure_ascii=False, default=str)

                span_models.append(TraceSpanModel(
                    tenant_id=self._tenant_id,
                    trace_id=trace.trace_id,
                    span_id=s.span_id,
                    parent_span_id=s.parent_id or '',
                    source=source,
                    span_type=span_type,
                    span_name=s.name or '',
                    status=s.status or 'success',
                    duration_ms=int(s.duration_ms) if s.duration_ms else 0,
                    start_time=int(s.start_time * 1000) if s.start_time else now,
                    end_time=int(s.end_time * 1000) if s.end_time else now,
                    input_data=input_data,
                    output_data=output_data,
                    metadata=metadata,
                ))

            if span_models:
                TraceSpanDAO.batch_insert(span_models)

            # 2. 更新 trace
            TraceDAO.finish(
                trace_id=trace.trace_id,
                status=trace.status or 'success',
                agent_output=(trace.agent_output or '')[:5000],
                total_tokens=trace.total_tokens or 0,
                duration_ms=int(trace.total_duration_ms) if trace.total_duration_ms else 0,
                iteration_count=trace.iteration_count or 0,
                tool_count=trace.tool_count or 0,
                span_count=len(trace.spans),
                now=now,
            )

            logger.info("TraceWriter: trace finished %s (%d spans)", trace.trace_id, len(span_models))

            # 3. Upsert conversation（创建或更新会话记录 + 标题）
            conv_id = self._upsert_conversation(trace, now)

            # 4. 写入 ai_message（对话历史）
            self._persist_message(trace, conv_id, now)

            # 5. 写入 ai_token_usage（用量统计）
            self._persist_token_usage(trace, conv_id, now)

        except Exception as e:
            logger.error("TraceWriter.on_trace_finish failed: %s", e)

    def _upsert_conversation(self, trace: Any, now: int) -> int:
        """创建或更新 ai_conversation 记录，持久化会话标题

        标题优先级：
        1. TitleMiddleware 已持久化的 LLM 标题（直接跳过更新）
        2. trace.title（由 TitleMiddleware 通过 state 传递）
        3. 规则截取（fallback）

        Returns:
            conv_id: 会话记录 ID（用于关联 ai_message）
        """
        try:
            from .pg_pool import get_conn
            thread_id = trace.thread_id or ''
            if not thread_id:
                return 0

            # 从请求上下文获取 user_id
            user_id = self._user_id
            try:
                from src.core.context import get_context
                ctx = get_context()
                if ctx.user_id:
                    user_id = int(ctx.user_id) if str(ctx.user_id).isdigit() else 0
            except Exception:
                logger.exception("_upsert_conversation 异常")

            with get_conn() as conn:
                cur = conn.cursor()
                # 检查是否已存在
                cur.execute(
                    "SELECT id, title FROM ai_conversation WHERE tenant_id=%s AND thread_id=%s AND delete_flg=0",
                    (self._tenant_id, thread_id))
                row = cur.fetchone()

                total_tokens = trace.total_tokens or 0
                user_input = (trace.user_input or '')[:500]

                if row:
                    # 已存在 → 更新统计
                    conv_id, existing_title = row
                    cur.execute("""
                        UPDATE ai_conversation
                        SET message_count = message_count + 1,
                            total_tokens = total_tokens + %s,
                            last_message_at = %s,
                            updated_at = %s
                        WHERE id = %s
                    """, (total_tokens, now, now, conv_id))

                    # 标题更新：只在标题为空/默认值且 TitleMiddleware 未更新时才用规则生成
                    if not existing_title or existing_title in ('', '新对话', '对话'):
                        # 优先使用 trace 中传递的 LLM 标题
                        title = getattr(trace, 'title', '') or ''
                        if not title:
                            title = self._generate_title(user_input)
                        cur.execute(
                            "UPDATE ai_conversation SET title=%s WHERE id=%s",
                            (title, conv_id))
                else:
                    # 不存在 → 创建新会话
                    from .snowflake import next_id
                    conv_id = next_id()
                    # 优先使用 trace 中传递的 LLM 标题
                    title = getattr(trace, 'title', '') or ''
                    if not title:
                        title = self._generate_title(user_input)
                    cur.execute("""
                        INSERT INTO ai_conversation
                        (id, tenant_id, user_id, thread_id, agent_name, title, model,
                         status, message_count, total_tokens, last_message_at,
                         delete_flg, created_at, created_by, updated_at, updated_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (conv_id, self._tenant_id, user_id, thread_id,
                          trace.agent_name or 'CRM-Agent', title, trace.model or '',
                          'active', 1, total_tokens, now,
                          0, now, user_id, now, user_id))

            return conv_id

        except Exception as e:
            logger.warning("_upsert_conversation failed (non-fatal): %s", e)
            return 0

    @staticmethod
    def _generate_title(user_input: str) -> str:
        """从用户输入生成简短标题（规则方式，LLM 标题由 TitleMiddleware 异步更新）"""
        text = (user_input or '').strip()
        for prefix in ("帮我", "请帮我", "请", "帮忙", "麻烦"):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        text = text.strip()
        if len(text) > 25:
            return text[:25] + "..."
        return text or "新对话"

    def _persist_message(self, trace: Any, conv_id: int, now: int) -> None:
        """将对话历史（query + answer）写入 ai_message 表

        一次 trace 对应一条 ai_message 记录：
        - query: 用户原始输入（trace.user_input）
        - answer: Agent 最终回复（trace.agent_output）
        - trace_id: 关联链路，可追溯完整执行过程
        - iteration_count / tool_count / duration_ms: 执行统计
        """
        if not conv_id:
            return
        try:
            from .pg_pool import get_conn
            from .snowflake import next_id

            thread_id = trace.thread_id or ''
            user_input = trace.user_input or ''
            agent_output = trace.agent_output or ''

            # 去重：同一个 trace_id 只写入一条消息
            trace_id_val = trace.trace_id or ''
            if trace_id_val:
                with get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT id FROM ai_message WHERE conversation_id=%s AND trace_id=%s AND delete_flg=0",
                        (conv_id, trace_id_val))
                    if cur.fetchone():
                        logger.debug("TraceWriter: message already exists for trace=%s, skip", trace_id_val)
                        return

            # 获取 user_id
            user_id = self._user_id
            try:
                from src.core.context import get_context
                ctx = get_context()
                if ctx.user_id:
                    user_id = int(ctx.user_id) if str(ctx.user_id).isdigit() else 0
            except Exception:
                pass

            # 计算 sequence（该会话的第 N 条消息）
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM ai_message WHERE conversation_id=%s",
                    (conv_id,))
                sequence = cur.fetchone()[0]

            # 从 trace spans 中提取 token 统计
            input_tokens = 0
            output_tokens = 0
            for s in (trace.spans or []):
                span_type = s.type
                if hasattr(span_type, 'value'):
                    span_type = span_type.value
                if span_type == 'llm_call' and s.metadata:
                    meta = s.metadata if isinstance(s.metadata, dict) else {}
                    input_tokens += meta.get('input_tokens', 0)
                    output_tokens += meta.get('output_tokens', 0)

            total_tokens = input_tokens + output_tokens
            if not total_tokens:
                total_tokens = trace.total_tokens or 0

            # 获取脱敏后的内容（如果 InputTransformMiddleware 有记录）
            masked_query = ''
            masked_answer = ''
            try:
                from src.core.context import get_context
                ctx = get_context()
                input_meta = getattr(ctx, 'input_metadata', None) or {}
                if isinstance(input_meta, dict):
                    masked_query = input_meta.get('masked_query', '')
            except Exception:
                pass

            # 判断状态
            status = 'success'
            error_message = ''
            if trace.status == 'error':
                status = 'error'
                # 从最后一个 error span 提取错误信息
                for s in reversed(trace.spans or []):
                    s_type = s.type
                    if hasattr(s_type, 'value'):
                        s_type = s_type.value
                    if s_type == 'error':
                        err_data = s.input_data if isinstance(s.input_data, dict) else {}
                        error_message = str(err_data.get('error', ''))[:2000]
                        break

            msg = Message(
                tenant_id=self._tenant_id,
                conversation_id=conv_id,
                thread_id=thread_id,
                sequence=sequence,
                role='user',
                query=user_input[:10000],
                answer=agent_output[:50000],
                masked_query=masked_query[:10000],
                masked_answer=masked_answer[:50000],
                model=trace.model or '',
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                iteration_count=trace.iteration_count or 0,
                tool_count=trace.tool_count or 0,
                duration_ms=int(trace.total_duration_ms) if hasattr(trace, 'total_duration_ms') and trace.total_duration_ms else 0,
                trace_id=trace.trace_id,
                status=status,
                error_message=error_message,
                created_at=now,
                created_by=user_id,
                updated_at=now,
                updated_by=user_id,
            )
            MessageDAO.insert(msg)
            logger.debug("TraceWriter: message persisted conv=%s seq=%d trace=%s",
                         conv_id, sequence, trace.trace_id)

        except Exception as e:
            logger.warning("_persist_message failed (non-fatal): %s", e)

    def _persist_token_usage(self, trace: Any, conv_id: int, now: int) -> None:
        """将 Token 用量写入 ai_token_usage 表（按 trace 粒度）"""
        total_tokens = trace.total_tokens or 0
        if not total_tokens:
            return
        try:
            # 获取 user_id
            user_id = self._user_id
            try:
                from src.core.context import get_context
                ctx = get_context()
                if ctx.user_id:
                    user_id = int(ctx.user_id) if str(ctx.user_id).isdigit() else 0
            except Exception:
                pass

            # 从 spans 中汇总 input/output tokens
            input_tokens = 0
            output_tokens = 0
            for s in (trace.spans or []):
                span_type = s.type
                if hasattr(span_type, 'value'):
                    span_type = span_type.value
                if span_type == 'llm_call' and s.metadata:
                    meta = s.metadata if isinstance(s.metadata, dict) else {}
                    input_tokens += meta.get('input_tokens', 0)
                    output_tokens += meta.get('output_tokens', 0)

            if not input_tokens and not output_tokens:
                # 无法拆分，全部算 output
                output_tokens = total_tokens

            # 简单成本估算（DeepSeek V4: input $0.27/M, output $1.10/M）
            cost = (input_tokens * 0.27 + output_tokens * 1.10) / 1_000_000

            usage = TokenUsage(
                tenant_id=self._tenant_id,
                user_id=user_id,
                conversation_id=conv_id or 0,
                thread_id=trace.thread_id or '',
                trace_id=trace.trace_id,
                model=trace.model or '',
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cost=cost,
                created_at=now,
            )
            TokenUsageDAO.insert(usage)
            logger.debug("TraceWriter: token_usage persisted trace=%s tokens=%d",
                         trace.trace_id, total_tokens)

        except Exception as e:
            logger.warning("_persist_token_usage failed (non-fatal): %s", e)

    def read_traces(self, limit: int = 50) -> list[dict]:
        """从 PG 读取 trace 列表（按 tenant_id 隔离）"""
        try:
            from .pg_pool import get_conn
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT trace_id, thread_id, user_input, agent_output, model, agent_name,
                           status, total_tokens, total_cost, iteration_count, tool_count,
                           span_count, duration_ms, start_time, end_time
                    FROM ai_trace WHERE tenant_id=%s AND delete_flg=0
                    ORDER BY start_time DESC LIMIT %s
                """, (self._tenant_id, limit))
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r)) for r in rows]
        except Exception as e:
            logger.error("TraceWriter.read_traces failed: %s", e)
            return []

    def read_trace_detail(self, trace_id: str) -> dict | None:
        """从 PG 读取单条 trace + 所有 span"""
        try:
            from .pg_pool import get_conn
            with get_conn() as conn:
                cur = conn.cursor()
                # Trace
                cur.execute("""
                    SELECT trace_id, thread_id, user_input, agent_output, model, agent_name,
                           status, total_tokens, total_cost, iteration_count, tool_count,
                           span_count, duration_ms, start_time, end_time
                    FROM ai_trace WHERE trace_id=%s AND delete_flg=0
                """, (trace_id,))
                row = cur.fetchone()
                if row:
                    cols = [d[0] for d in cur.description]
                    trace = dict(zip(cols, row))
                    trace['total_duration_ms'] = trace.pop('duration_ms', 0)
                else:
                    # ai_trace 记录不存在（兼容旧数据 / AG-UI 模式早期 bug），
                    # 仍尝试从 ai_trace_span 表读取 spans
                    trace = {
                        "trace_id": trace_id,
                        "thread_id": "",
                        "user_input": "",
                        "agent_output": "",
                        "model": "",
                        "agent_name": "",
                        "status": "success",
                        "total_tokens": 0,
                        "total_cost": 0,
                        "iteration_count": 0,
                        "tool_count": 0,
                        "span_count": 0,
                        "total_duration_ms": 0,
                        "start_time": 0,
                        "end_time": 0,
                    }

                # Spans
                cur.execute("""
                    SELECT span_id, parent_span_id, source, span_type, span_name,
                           status, duration_ms, start_time, end_time,
                           input_data, output_data, metadata
                    FROM ai_trace_span WHERE trace_id=%s AND delete_flg=0
                    ORDER BY start_time
                """, (trace_id,))
                span_rows = cur.fetchall()
                if not span_rows and not row:
                    # 既没有 trace 记录也没有 span 记录，返回 None
                    return None
                span_cols = [d[0] for d in cur.description]
                spans = []
                for sr in span_rows:
                    sp = dict(zip(span_cols, sr))
                    sp['type'] = sp.pop('span_type', '')
                    sp['name'] = sp.pop('span_name', '')
                    sp['parent_id'] = sp.pop('parent_span_id', '')
                    # Parse JSON fields
                    for jf in ('input_data', 'output_data', 'metadata'):
                        val = sp.get(jf, '{}')
                        if isinstance(val, str):
                            try:
                                sp[jf] = json.loads(val)
                            except (json.JSONDecodeError, TypeError):
                                sp[jf] = {}

                    # 从 metadata 中提取前端需要的顶层字段
                    # （持久化时 step_name/step_name_en/detail/phase/children 存入 metadata）
                    md = sp.get('metadata') or {}
                    if md.get('step_name') and 'step_name' not in sp:
                        sp['step_name'] = md['step_name']
                    if md.get('step_name_en') and 'step_name_en' not in sp:
                        sp['step_name_en'] = md['step_name_en']
                    if md.get('detail') and 'detail' not in sp:
                        sp['detail'] = md['detail']
                    if md.get('phase') and 'phase' not in sp:
                        sp['phase'] = md['phase']
                    if md.get('children') and 'children' not in sp:
                        sp['children'] = md['children']

                    spans.append(sp)

                trace['spans'] = spans
                return trace
        except Exception as e:
            logger.error("TraceWriter.read_trace_detail failed: %s", e)
            return None
