"""TraceWriter — 将内存 Trace 持久化到 PG

设计原则：
- Agent 执行期间不写 PG（避免影响延迟）
- 执行完成后批量写入（一次 trace 的所有 span 一次性 INSERT）
- 写入失败不影响主流程（降级为仅内存，记录 error 日志）
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from .models import Trace as TraceModel, TraceSpan as TraceSpanModel
from .dao import TraceDAO, TraceSpanDAO

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
        except Exception as e:
            logger.error("TraceWriter.on_trace_finish failed: %s", e)

    def read_traces(self, limit: int = 50) -> list[dict]:
        """从 PG 读取 trace 列表"""
        try:
            from .pg_pool import get_conn
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT trace_id, thread_id, user_input, agent_output, model, agent_name,
                           status, total_tokens, total_cost, iteration_count, tool_count,
                           span_count, duration_ms, start_time, end_time
                    FROM ai_trace WHERE delete_flg=0
                    ORDER BY start_time DESC LIMIT %s
                """, (limit,))
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
                if not row:
                    return None
                cols = [d[0] for d in cur.description]
                trace = dict(zip(cols, row))
                trace['total_duration_ms'] = trace.pop('duration_ms', 0)

                # Spans
                cur.execute("""
                    SELECT span_id, parent_span_id, source, span_type, span_name,
                           status, duration_ms, start_time, end_time,
                           input_data, output_data, metadata
                    FROM ai_trace_span WHERE trace_id=%s AND delete_flg=0
                    ORDER BY start_time
                """, (trace_id,))
                span_rows = cur.fetchall()
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
                    sp['input'] = sp.pop('input_data', {})
                    sp['output'] = sp.pop('output_data', {})
                    spans.append(sp)

                trace['spans'] = spans
                return trace
        except Exception as e:
            logger.error("TraceWriter.read_trace_detail failed: %s", e)
            return None
