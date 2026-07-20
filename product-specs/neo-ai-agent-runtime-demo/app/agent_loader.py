"""AgentLoader — 从配置文件加载注册数据，通过 Transport 远程执行

启动流程：
    1. 从 config/registry.yaml 加载注册数据
    2. 构建 ServiceResolver + HttpxTransport（生产环境替换为 NeoApiTransport）
    3. 按 api_key 查找对应服务，通过 FeignClient 远程执行 Tool/Middleware/MCP
"""
from __future__ import annotations

import logging
from typing import Any

from neo_ai_registry.feign import ToolFeignClient, MiddlewareFeignClient, ServiceResolver
from neo_ai_registry.feign.transport import NeoApiTransport

from app.config_loader import load_registry_config, RegistryConfig, ToolConfig, MiddlewareConfig

logger = logging.getLogger(__name__)


class AgentLoader:
    """Agent 运行时的 Tool/Middleware/MCP 远程执行器

    从配置文件初始化注册数据，运行时按 api_key 路由到对应服务执行。
    开发环境用 HttpxTransport 直连，生产环境替换为 NeoApiTransport（自动带上下文+trace）。
    """

    def __init__(self, config_path: str = ""):
        """初始化 AgentLoader

        Args:
            config_path: 注册配置文件路径。为空时使用默认 config/registry.yaml。
        """
        self._config: RegistryConfig | None = None
        self._resolver: ServiceResolver | None = None
        self._tool_map: dict[str, ToolConfig] = {}
        self._middleware_map: dict[str, MiddlewareConfig] = {}
        self._tool_clients: dict[str, ToolFeignClient] = {}
        self._mw_clients: dict[str, MiddlewareFeignClient] = {}
        self._config_path = config_path

    def load(self) -> None:
        """从配置文件加载注册数据并初始化

        根据 eureka.enabled 决定使用 Eureka 发现还是静态映射。
        """
        self._config = load_registry_config(self._config_path)

        # 构建 Transport（NeoApiTransport — 通过 NeoApiClient + Eureka 自动发现服务）
        self._transport = NeoApiTransport()
        logger.info("[AgentLoader] 使用 NeoApiTransport（NeoApiClient + Eureka）")

        # 构建 Tool 映射
        for tool in self._config.tools:
            self._tool_map[tool.api_key] = tool

        # 构建 Middleware 映射
        for mw in self._config.middlewares:
            self._middleware_map[mw.api_key] = mw

        logger.info(
            "[AgentLoader] 加载完成: %d tools, %d middlewares, %d services",
            len(self._tool_map), len(self._middleware_map), len(self._config.services),
        )

    def _get_tool_client(self, service_name: str) -> ToolFeignClient:
        """获取或创建 ToolFeignClient（连接复用）"""
        if service_name not in self._tool_clients:
            self._tool_clients[service_name] = ToolFeignClient(
                app_name=service_name,
                transport=self._transport,
            )
        return self._tool_clients[service_name]

    def _get_mw_client(self, service_name: str) -> MiddlewareFeignClient:
        """获取或创建 MiddlewareFeignClient（连接复用）"""
        if service_name not in self._mw_clients:
            self._mw_clients[service_name] = MiddlewareFeignClient(
                app_name=service_name,
                transport=self._transport,
            )
        return self._mw_clients[service_name]

    def execute_tool(
        self,
        api_key: str,
        input_data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """根据 api_key 远程执行 Tool

        从配置中查找 Tool 对应的服务名，通过 FeignClient 远程调用。

        Args:
            api_key: Tool 唯一标识。
            input_data: Tool 入参字典。
            context: 执行上下文（tenant_id/user_id/thread_id 等）。

        Returns:
            Tool 执行结果。

        Raises:
            KeyError: api_key 未在配置中注册时抛出。
        """
        tool_config = self._tool_map.get(api_key)
        if not tool_config:
            raise KeyError(
                f"Tool '{api_key}' 未注册，已配置: {list(self._tool_map.keys())}"
            )

        client = self._get_tool_client(tool_config.service)
        logger.info("[AgentLoader] execute_tool: %s → %s", api_key, tool_config.service)
        return client.execute_tool(api_key, input_data, context)

    def execute_middleware(
        self,
        api_key: str,
        hook: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """根据 api_key 远程执行 Middleware 钩子

        从配置中查找 Middleware 对应的服务名，通过 FeignClient 远程调用。

        Args:
            api_key: Middleware 唯一标识。
            hook: 生命周期钩子名称。
            payload: 钩子入参。
            context: 执行上下文。

        Returns:
            Middleware 执行结果（action + patch/message）。

        Raises:
            KeyError: api_key 未在配置中注册时抛出。
        """
        mw_config = self._middleware_map.get(api_key)
        if not mw_config:
            raise KeyError(
                f"Middleware '{api_key}' 未注册，已配置: {list(self._middleware_map.keys())}"
            )

        client = self._get_mw_client(mw_config.service)
        logger.info("[AgentLoader] execute_middleware: %s/%s → %s", api_key, hook, mw_config.service)
        return client.execute_middleware(api_key, hook, payload, context)

    @property
    def tool_keys(self) -> list[str]:
        """已注册的 Tool api_key 列表"""
        return list(self._tool_map.keys())

    @property
    def middleware_keys(self) -> list[str]:
        """已注册的 Middleware api_key 列表"""
        return list(self._middleware_map.keys())

    # ═══════════════════════════════════════════════════════════
    # MCP 调用（通过 McpFeignClient → neo-ai-mcp-service）
    # ═══════════════════════════════════════════════════════════

    def call_mcp_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        server_api_key: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """调用 MCP Tool

        通过 McpFeignClient 远程调用 neo-ai-mcp-demo 服务。
        """
        from neo_ai_registry.mcp import McpFeignClient
        if not hasattr(self, '_mcp_client'):
            self._mcp_client = McpFeignClient(
                app_name="neo-ai-mcp-demo",
                transport=self._transport,
            )
        return self._mcp_client.call_tool(tool_name, arguments, server_api_key, context)

    def list_mcp_tools(self, server_api_key: str = ""):
        """列出 MCP Tool"""
        from neo_ai_registry.mcp import McpFeignClient
        if not hasattr(self, '_mcp_client'):
            self._mcp_client = McpFeignClient(
                app_name="neo-ai-mcp-demo",
                transport=self._transport,
            )
        return self._mcp_client.list_tools(server_api_key)

    def list_mcp_servers(self):
        """列出 MCP Server"""
        from neo_ai_registry.mcp import McpFeignClient
        if not hasattr(self, '_mcp_client'):
            self._mcp_client = McpFeignClient(
                app_name="neo-ai-mcp-demo",
                transport=self._transport,
            )
        return self._mcp_client.list_servers()

    def summary(self) -> dict[str, Any]:
        """注册数据汇总"""
        return {
            "tools": len(self._tool_map),
            "middlewares": len(self._middleware_map),
            "services": list((self._config.services or {}).keys()),
        }
