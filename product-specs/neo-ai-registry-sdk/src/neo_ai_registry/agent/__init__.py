"""Agent 侧 — 消费方（Agent Runtime 使用）"""

from neo_ai_registry.agent.registry import AgentRegistry
from neo_ai_registry.agent.discover import discover_tools, discover_middlewares
from neo_ai_registry.agent.middleware_adapter import create_remote_middleware, create_remote_middlewares

__all__ = [
    "AgentRegistry",
    "discover_tools",
    "discover_middlewares",
    "create_remote_middleware",
    "create_remote_middlewares",
]
