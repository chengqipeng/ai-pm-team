"""
核心类型定义 — DeepAgent 架构
"""
from __future__ import annotations

import uuid
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Any


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
    is_compact_boundary: bool = False
    api_error: str | None = None
    usage: dict[str, int] | None = None


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


# ─── LLM 客户端抽象 ───

class LLMClient:
    """LLM API 客户端抽象 (可替换为任意 LLM 后端)"""

    async def call(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str = "deepseek-chat",
        max_tokens: int = 8192,
    ) -> dict:
        raise NotImplementedError("Subclass must implement call()")
