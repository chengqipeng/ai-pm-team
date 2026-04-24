"""数据模型 — 对应 paas_ai schema 的 7 张表"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .snowflake import next_id


@dataclass
class Conversation:
    id: int = 0
    tenant_id: int = 0
    user_id: int = 0
    thread_id: str = ""
    agent_name: str = "CRM-Agent"
    title: str = ""
    summary: str = ""
    model: str = ""
    status: str = "active"
    message_count: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    last_message_at: int = 0
    ext_info: str = "{}"
    delete_flg: int = 0
    created_at: int = 0
    created_by: int = 0
    updated_at: int = 0
    updated_by: int = 0

    def __post_init__(self):
        if not self.id:
            self.id = next_id()
        now = int(time.time() * 1000)
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


@dataclass
class Message:
    id: int = 0
    tenant_id: int = 0
    conversation_id: int = 0
    thread_id: str = ""
    sequence: int = 0
    role: str = "user"
    query: str = ""
    answer: str = ""
    masked_query: str = ""
    masked_answer: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    iteration_count: int = 0
    tool_count: int = 0
    duration_ms: int = 0
    trace_id: str = ""
    status: str = "success"
    error_message: str = ""
    ext_info: str = "{}"
    delete_flg: int = 0
    created_at: int = 0
    created_by: int = 0
    updated_at: int = 0
    updated_by: int = 0

    def __post_init__(self):
        if not self.id:
            self.id = next_id()
        now = int(time.time() * 1000)
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


@dataclass
class MessageExt:
    id: int = 0
    tenant_id: int = 0
    message_id: int = 0
    ext_type: str = ""
    ext_data: str = "{}"
    status: str = "active"
    delete_flg: int = 0
    created_at: int = 0
    updated_at: int = 0

    def __post_init__(self):
        if not self.id:
            self.id = next_id()
        now = int(time.time() * 1000)
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


@dataclass
class Trace:
    id: int = 0
    tenant_id: int = 0
    trace_id: str = ""
    thread_id: str = ""
    message_id: int = 0
    user_input: str = ""
    agent_output: str = ""
    model: str = ""
    agent_name: str = ""
    status: str = "running"
    total_tokens: int = 0
    total_cost: float = 0.0
    iteration_count: int = 0
    tool_count: int = 0
    span_count: int = 0
    duration_ms: int = 0
    start_time: int = 0
    end_time: int = 0
    ext_info: str = "{}"
    delete_flg: int = 0
    created_at: int = 0
    updated_at: int = 0

    def __post_init__(self):
        if not self.id:
            self.id = next_id()
        now = int(time.time() * 1000)
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        if not self.start_time:
            self.start_time = now


@dataclass
class TraceSpan:
    id: int = 0
    tenant_id: int = 0
    trace_id: str = ""
    span_id: str = ""
    parent_span_id: str = ""
    source: str = "agent"
    span_type: str = ""
    span_name: str = ""
    status: str = "running"
    duration_ms: int = 0
    start_time: int = 0
    end_time: int = 0
    input_data: str = "{}"
    output_data: str = "{}"
    metadata: str = "{}"
    delete_flg: int = 0
    created_at: int = 0

    def __post_init__(self):
        if not self.id:
            self.id = next_id()
        now = int(time.time() * 1000)
        if not self.created_at:
            self.created_at = now
        if not self.start_time:
            self.start_time = now


@dataclass
class ContentReviewLog:
    id: int = 0
    tenant_id: int = 0
    thread_id: str = ""
    message_id: int = 0
    review_type: str = ""
    original_content: str = ""
    blocked_keywords: str = "[]"
    blocked_reason: str = ""
    rule_id: int = 0
    delete_flg: int = 0
    created_at: int = 0

    def __post_init__(self):
        if not self.id:
            self.id = next_id()
        if not self.created_at:
            self.created_at = int(time.time() * 1000)


@dataclass
class TokenUsage:
    id: int = 0
    tenant_id: int = 0
    user_id: int = 0
    conversation_id: int = 0
    thread_id: str = ""
    trace_id: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    created_at: int = 0

    def __post_init__(self):
        if not self.id:
            self.id = next_id()
        if not self.created_at:
            self.created_at = int(time.time() * 1000)
