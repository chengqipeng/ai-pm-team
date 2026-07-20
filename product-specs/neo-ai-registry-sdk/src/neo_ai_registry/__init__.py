"""neo-ai-registry-sdk — Agent 切面注册器

提供 Tool / Middleware / MCP 的定义与调用能力。
业务域服务使用 Registry 内置数据，Agent 运行时通过 FeignClient 远程调用。
"""

from neo_ai_registry.registry import Registry
from neo_ai_registry.models import (
    ToolDefinition,
    MiddlewareDefinition,
    ToolType,
    MiddlewareHook,
)
from neo_ai_registry.state import ToolState

__version__ = "0.1.0"

__all__ = [
    "Registry",
    "ToolDefinition",
    "MiddlewareDefinition",
    "ToolType",
    "MiddlewareHook",
    "ToolState",
]
