"""Tracer — 完整的执行链路追踪

记录 Agent 执行过程中每一个步骤：
- request/response: 用户输入/最终输出
- before_agent/after_agent: 中间件前后处理
- before_model/after_model: LLM 调用前后
- llm_call: LLM 推理（含 token 消耗）
- tool_call: 工具调用（含耗时）
- skill_select: 技能选择（inline/fork）
- memory_retrieve/memory_extract: 记忆检索/提取
- compression: 上下文压缩
- error: 异常
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SpanType(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"
    BEFORE_AGENT = "before_agent"
    AFTER_AGENT = "after_agent"
    BEFORE_MODEL = "before_model"
    AFTER_MODEL = "after_model"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    SKILL_SELECT = "skill_select"
    SKILL_EXECUTE = "skill_execute"
    MEMORY_RETRIEVE = "memory_retrieve"
    MEMORY_EXTRACT = "memory_extract"
    COMPRESSION = "compression"
    SUBAGENT = "subagent"
    ERROR = "error"
    # 对齐 index.html 新增
    CONTEXT_BUILD = "context_build"
    INTENT_ANALYSIS = "intent_analysis"
    HIERARCHICAL_SEARCH = "hierarchical_search"


@dataclass
class Span:
    """单个执行步骤"""
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    parent_id: str = ""
    type: str = ""
    name: str = ""
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    duration_ms: float = 0.0
    status: str = "running"  # running / success / error
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    children: list[str] = field(default_factory=list)

    def finish(self, status: str = "success", output: dict | None = None) -> None:
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.status = status
        if output:
            self.output_data = output

    def to_dict(self) -> dict[str, Any]:
        # Normalize type: strip "SpanType." prefix if present
        span_type = self.type
        if isinstance(span_type, str) and span_type.startswith("SpanType."):
            span_type = span_type.split(".", 1)[1].lower()
        elif hasattr(span_type, 'value'):
            span_type = span_type.value
        return {
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "type": span_type,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 1),
            "status": self.status,
            "input": self.input_data,
            "output": self.output_data,
            "metadata": self.metadata,
            "children": self.children,
        }


@dataclass
class Trace:
    """一次完整的 Agent 执行链路"""
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    thread_id: str = ""
    user_id: str = ""
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    total_duration_ms: float = 0.0
    status: str = "running"
    total_tokens: int = 0
    total_cost: float = 0.0
    iteration_count: int = 0
    tool_count: int = 0
    spans: list[Span] = field(default_factory=list)
    user_input: str = ""
    agent_output: str = ""
    model: str = ""
    agent_name: str = ""

    def finish(self, status: str = "success") -> None:
        self.end_time = time.time()
        self.total_duration_ms = (self.end_time - self.start_time) * 1000
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        # Sort spans by start_time for correct chronological order
        sorted_spans = sorted(self.spans, key=lambda s: s.start_time)
        return {
            "trace_id": self.trace_id,
            "thread_id": self.thread_id,
            "user_id": self.user_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_duration_ms": round(self.total_duration_ms, 1),
            "status": self.status,
            "total_tokens": self.total_tokens,
            "total_cost": round(self.total_cost, 4),
            "iteration_count": self.iteration_count,
            "tool_count": self.tool_count,
            "user_input": self.user_input,
            "agent_output": self.agent_output[:500],
            "model": self.model,
            "agent_name": self.agent_name,
            "spans": [s.to_dict() for s in sorted_spans],
        }

    def to_timeline(self) -> list[dict]:
        """生成时间线视图（前端渲染用）"""
        if not self.spans:
            return []
        sorted_spans = sorted(self.spans, key=lambda s: s.start_time)
        base_time = self.start_time
        return [{
            "span_id": s.span_id,
            "type": s.to_dict()["type"],  # use normalized type
            "name": s.name,
            "offset_ms": round((s.start_time - base_time) * 1000, 1),
            "duration_ms": round(s.duration_ms, 1),
            "status": s.status,
            "metadata": s.metadata,
        } for s in sorted_spans]


class Tracer:
    """全局 Tracer — 管理所有 Trace"""

    def __init__(self) -> None:
        self._traces: dict[str, Trace] = {}  # trace_id → Trace
        self._thread_traces: dict[str, list[str]] = {}  # thread_id → [trace_id, ...]
        self._active_trace: dict[str, str] = {}  # thread_id → active trace_id

    def start_trace(self, thread_id: str, user_input: str,
                    user_id: str = "", model: str = "", agent_name: str = "") -> Trace:
        trace = Trace(
            thread_id=thread_id, user_id=user_id,
            user_input=user_input, model=model, agent_name=agent_name,
        )
        self._traces[trace.trace_id] = trace
        self._thread_traces.setdefault(thread_id, []).append(trace.trace_id)
        self._active_trace[thread_id] = trace.trace_id

        # 记录 request span
        span = self.start_span(trace.trace_id, SpanType.REQUEST, "user_input",
                               input_data={"message": user_input[:500]})
        span.finish("success")
        return trace

    def finish_trace(self, trace_id: str, status: str = "success", output: str = "") -> None:
        trace = self._traces.get(trace_id)
        if trace:
            trace.agent_output = output
            trace.finish(status)
            span = self.start_span(trace_id, SpanType.RESPONSE, "agent_output",
                                   metadata={"content_length": len(output)})
            span.finish("success")

    def start_span(self, trace_id: str, span_type: str | SpanType, name: str,
                   parent_id: str = "", input_data: dict | None = None,
                   metadata: dict | None = None) -> Span:
        trace = self._traces.get(trace_id)
        if trace is None:
            logger.warning("Trace not found: %s", trace_id)
            return Span(type=str(span_type), name=name)

        # Normalize type to plain lowercase string
        if isinstance(span_type, SpanType):
            type_str = span_type.value
        else:
            type_str = str(span_type)
            if type_str.startswith("SpanType."):
                type_str = type_str.split(".", 1)[1].lower()

        span = Span(
            type=type_str,
            name=name, parent_id=parent_id,
            input_data=input_data or {}, metadata=metadata or {},
        )
        trace.spans.append(span)
        return span

    def get_trace(self, trace_id: str) -> Trace | None:
        return self._traces.get(trace_id)

    def get_traces_by_thread(self, thread_id: str) -> list[Trace]:
        trace_ids = self._thread_traces.get(thread_id, [])
        return [self._traces[tid] for tid in trace_ids if tid in self._traces]

    def get_active_trace(self, thread_id: str) -> Trace | None:
        trace_id = self._active_trace.get(thread_id)
        return self._traces.get(trace_id) if trace_id else None

    def get_all_traces(self, limit: int = 50) -> list[Trace]:
        traces = sorted(self._traces.values(), key=lambda t: t.start_time, reverse=True)
        return traces[:limit]

    def add_tokens(self, trace_id: str, tokens: int, cost: float = 0.0) -> None:
        trace = self._traces.get(trace_id)
        if trace:
            trace.total_tokens += tokens
            trace.total_cost += cost

    def increment_iteration(self, trace_id: str) -> None:
        trace = self._traces.get(trace_id)
        if trace:
            trace.iteration_count += 1

    def increment_tool(self, trace_id: str) -> None:
        trace = self._traces.get(trace_id)
        if trace:
            trace.tool_count += 1


# 全局单例
tracer = Tracer()
