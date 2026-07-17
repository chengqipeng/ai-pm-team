"""McpFeignClient — Agent 调用 neo-ai-mcp-service 的 FeignClient

Agent 运行时通过此客户端调用 MCP Service 执行 MCP Tool。
底层通过 Transport 传输（生产走 NeoApiTransport 自动带上下文+trace）。

路由规范：
    POST /v2/mcp/tools/call                → call_tool
    GET  /v2/mcp/tools                     → list_tools
    GET  /v2/mcp/servers                   → list_servers

Usage:
    from neo_ai_registry.mcp import McpFeignClient
    from neo_ai_registry.feign.transport import HttpxTransport

    client = McpFeignClient(app_name="neo-ai-mcp-service", transport=transport)
    result = client.call_tool("query_records", {"entity": "account", "limit": 10})
    tools = client.list_tools(server_api_key="crm-data-mcp")
    servers = client.list_servers()
"""
from __future__ import annotations

import logging
from typing import Any

from neo_ai_registry.mcp.models import McpToolDefinition, McpServerInfo
from neo_ai_registry.mcp.provider import McpProvider

logger = logging.getLogger(__name__)


class McpFeignClient(McpProvider):
    """MCP Provider 的 FeignClient 实现

    Agent 运行时通过此客户端远程调用 neo-ai-mcp-service。
    与 ToolFeignClient / MiddlewareFeignClient 同模式，基于 Transport 抽象。

    Usage:
        # 生产环境
        from neo_ai_registry.feign.transport import NeoApiTransport
        client = McpFeignClient(app_name="neo-ai-mcp-service", transport=NeoApiTransport())

        # 开发环境
        from neo_ai_registry.feign import ServiceResolver
        from neo_ai_registry.feign.transport import HttpxTransport
        resolver = ServiceResolver(static_map={"neo-ai-mcp-service": "http://localhost:8003"})
        client = McpFeignClient(app_name="neo-ai-mcp-service", transport=HttpxTransport(resolver=resolver))
    """

    def __init__(
        self,
        app_name: str = "neo-ai-mcp-service",
        transport: Any = None,
        resolver: Any = None,
    ):
        """初始化 McpFeignClient

        Args:
            app_name: MCP 服务名（默认 "neo-ai-mcp-service"）。
                      生产环境通过 NeoApiTransport 走 Eureka 解析。
            transport: 传输层实例（Transport 子类）。
                       传 None 时自动创建 HttpxTransport。
            resolver: 服务名解析器（transport=None 时用于创建默认 HttpxTransport）。
        """
        self._app_name = app_name
        if transport:
            self._transport = transport
        else:
            from neo_ai_registry.feign.transport import HttpxTransport
            self._transport = HttpxTransport(resolver=resolver)

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        server_api_key: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """远程调用 MCP Tool

        通过 POST /v2/mcp/tools/call 调用 neo-ai-mcp-service，
        由 MCP Service 路由到对应的 MCP Server 执行。

        Args:
            tool_name: MCP Tool 名称（如 "query_records"、"search_knowledge"）。
                       MCP Service 根据此名称路由到对应 Server。
            arguments: Tool 入参字典。对应 MCP 协议 tools/call 的 arguments。
            server_api_key: 指定 MCP Server（可选）。为空时自动路由。
            context: 执行上下文（可选）：
                     - tenant_id (int): 租户 ID
                     - user_id (int): 用户 ID
                     - thread_id (str): 会话 ID
                     - message_id (str): 消息 ID
                     - trace_id (str): 链路 ID

        Returns:
            MCP Tool 执行结果字典。

        Raises:
            Exception: MCP Service 调用失败时抛出。
        """
        payload: dict[str, Any] = {
            "tool_name": tool_name,
            "arguments": arguments,
        }
        if server_api_key:
            payload["server_api_key"] = server_api_key
        if context:
            payload["context"] = context

        return self._transport.invoke(
            app_name=self._app_name,
            service="/v2/mcp/tools/call",
            method="POST",
            data=payload,
        )

    def list_tools(self, server_api_key: str = "") -> list[McpToolDefinition]:
        """远程获取可用的 MCP Tool 列表

        通过 GET /v2/mcp/tools 调用 neo-ai-mcp-service。

        Args:
            server_api_key: 按 MCP Server 过滤（可选）。为空返回全部。

        Returns:
            McpToolDefinition 列表。
        """
        params = {"server_api_key": server_api_key} if server_api_key else None
        # GET 请求通过 query params 传递
        service = "/v2/mcp/tools"
        if server_api_key:
            service = f"/v2/mcp/tools?server_api_key={server_api_key}"

        data = self._transport.invoke(
            app_name=self._app_name,
            service=service,
            method="GET",
        )
        if isinstance(data, list):
            return [McpToolDefinition.model_validate(item) for item in data]
        return []

    def list_servers(self) -> list[McpServerInfo]:
        """远程获取已连接的 MCP Server 列表

        通过 GET /v2/mcp/servers 调用 neo-ai-mcp-service。

        Returns:
            McpServerInfo 列表。
        """
        data = self._transport.invoke(
            app_name=self._app_name,
            service="/v2/mcp/servers",
            method="GET",
        )
        if isinstance(data, list):
            return [McpServerInfo.model_validate(item) for item in data]
        return []
