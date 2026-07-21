"""AgentLoader — 项目级薄包装（委托 SDK AgentRegistry）

项目级职责：
    - 决定 Transport 类型（NeoApiTransport）
    - 决定配置文件路径（config/registry.yaml）
    - 提供 MCP 调用（项目特有，不在 SDK 通用逻辑中）

SDK 负责的（AgentRegistry）：
    - 扫描 Builtin Tools/Middlewares
    - 注册 Remote Tools/Middlewares
    - execute_tool 统一分派
    - get_middlewares 返回 AgentMiddleware 列表
"""
from __future__ import annotations

import os
from typing import Any

from neo_ai_registry import ConfigLoader, AgentRegistry

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CONFIG = os.path.join(_PROJECT_ROOT, "config", "registry.yaml")


class AgentLoader:
    """项目级 Agent 加载器 — 薄包装 SDK AgentRegistry"""

    def __init__(self, config_path: str = ""):
        self._config_path = config_path or _DEFAULT_CONFIG
        self._registry: AgentRegistry | None = None

    def load(self) -> None:
        """加载注册数据"""
        from neo_ai_registry.feign.transport import NeoApiTransport

        # 1. 加载配置（SDK ConfigLoader）
        config = ConfigLoader.from_yaml(self._config_path)

        # 2. 创建 Transport（项目决策：使用 NeoApiTransport）
        transport = NeoApiTransport()

        # 3. 构建 AgentRegistry（SDK 核心）
        self._registry = AgentRegistry(transport=transport)
        self._registry.load(config, project_root=_PROJECT_ROOT)

    # ── 委托 SDK ──

    def get_middlewares(self) -> list:
        """获取 AgentMiddleware 列表（传给 create_agent）"""
        return self._registry.get_middlewares()

    async def async_execute_tool(self, api_key: str, input_data: dict, agent_state: dict | None = None, configurable: dict | None = None) -> dict:
        """执行 Tool（异步）"""
        return await self._registry.async_execute_tool(api_key, input_data, agent_state, configurable)

    def execute_tool(self, api_key: str, input_data: dict, agent_state: dict | None = None, configurable: dict | None = None) -> dict:
        """执行 Tool（同步）"""
        return self._registry.execute_tool(api_key, input_data, agent_state, configurable)

    # ── MCP（项目特有） ──

    async def async_call_mcp_tool(self, tool_name: str, arguments: dict, server_api_key: str = "", context: dict | None = None) -> dict:
        """调用 MCP Tool"""
        data: dict[str, Any] = {"tool_name": tool_name, "arguments": arguments}
        if server_api_key:
            data["server_api_key"] = server_api_key
        if context:
            data["context"] = context
        return await self._registry._transport.async_invoke(
            app_name="neo-ai-mcp-demo",
            service="/v2/mcp/tools/call",
            method="POST",
            data=data,
        )

    # ── 查询 ──

    def summary(self) -> dict:
        return self._registry.summary()

    @property
    def tool_keys(self) -> list[str]:
        return self._registry.tool_keys
