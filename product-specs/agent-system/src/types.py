"""
核心类型定义
借鉴 Tool.ts / types/message.ts / types/permissions.ts
"""
from __future__ import annotations

import uuid
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import (
    Any, Callable, Optional, Protocol, TypeVar, Generic,
    AsyncIterator, Awaitable,
)


# ─── 基础 ID 类型 ───
AgentId = str


def create_agent_id() -> AgentId:
    return f"agent-{uuid.uuid4().hex[:8]}"


# ─── 消息类型 ───
class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class ToolUseBlock:
    """LLM 返回的工具调用块"""
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResultBlock:
    """工具执行结果块"""
    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    role: MessageRole
    content: str | list[Any] = ""
    tool_use_blocks: list[ToolUseBlock] = field(default_factory=list)
    tool_result_blocks: list[ToolResultBlock] = field(default_factory=list)
    uuid: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    # 元数据
    is_compact_boundary: bool = False
    api_error: str | None = None
    usage: dict[str, int] | None = None


# ─── 权限类型 ───
class PermissionMode(str, Enum):
    DEFAULT = "default"
    ACCEPT_EDITS = "acceptEdits"
    BYPASS = "bypassPermissions"
    AUTO = "auto"
    BUBBLE = "bubble"


class PermissionBehavior(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class PermissionDecision:
    behavior: PermissionBehavior
    reason: str | None = None
    updated_input: dict[str, Any] | None = None


@dataclass
class ToolPermissionContext:
    mode: PermissionMode = PermissionMode.DEFAULT
    always_allow_rules: list[str] = field(default_factory=list)
    always_deny_rules: list[str] = field(default_factory=list)
    should_avoid_prompts: bool = False


# ─── 验证结果 ───
@dataclass
class ValidationResult:
    valid: bool
    message: str = ""


# ─── 工具结果 ───
@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


# ─── API 错误分类 ───
class RetryCategory(str, Enum):
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    OVERLOADED = "overloaded"
    NETWORK = "network"
    NON_RETRYABLE = "non_retryable"


# ─── Task 类型 ───
class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"
