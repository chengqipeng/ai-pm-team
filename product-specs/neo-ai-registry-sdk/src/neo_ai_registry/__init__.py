"""neo-ai-registry-sdk — Agent 切面注册器

目录结构：
    agent/       → Agent 运行时侧（AgentRegistry / discover / middleware_adapter）
    provider/    → Provider 服务侧（ProviderRegistry / create_provider_app）
    feign/       → 远程调用层（FeignClient / Transport / ServiceResolver）
    mcp/         → MCP 相关
    models.py    → ToolDefinition / MiddlewareDefinition
    state.py     → ToolState / set_state / get_state
    config.py    → ConfigLoader / RegistryConfig
"""

from neo_ai_registry.models import ToolDefinition, MiddlewareDefinition, ToolType, MiddlewareHook
from neo_ai_registry.state import ToolState, set_state, get_state
from neo_ai_registry.config import ConfigLoader, RegistryConfig
from neo_ai_registry.agent import AgentRegistry, discover_tools, discover_middlewares
from neo_ai_registry.provider import ProviderRegistry, create_provider_app

__version__ = "0.1.0"

__all__ = [
    # Models
    "ToolDefinition",
    "MiddlewareDefinition",
    "ToolType",
    "MiddlewareHook",
    # State
    "ToolState",
    "set_state",
    "get_state",
    # Config
    "ConfigLoader",
    "RegistryConfig",
    # Agent 侧
    "AgentRegistry",
    "discover_tools",
    "discover_middlewares",
    # Provider 侧
    "ProviderRegistry",
    "create_provider_app",
]
