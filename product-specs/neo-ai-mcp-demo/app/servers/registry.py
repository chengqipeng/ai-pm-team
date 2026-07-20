"""ServerRegistry — MCP Server 统一注册与路由

管理多个业务域 MCP Server，提供：
- Tool 路由：根据 tool_name 找到对应 Server 执行
- Server 管理：列出所有 Server 和 Tool
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class McpServer:
    """单个 MCP Server 定义"""

    def __init__(self, api_key: str, name: str, description: str, domain: str):
        self.api_key = api_key
        self.name = name
        self.description = description
        self.domain = domain
        self.tools: dict[str, dict[str, Any]] = {}
        self.handlers: dict[str, ToolHandler] = {}

    def add_tool(self, tool_name: str, description: str, input_schema: dict, handler: ToolHandler):
        """注册 Tool 到此 Server"""
        self.tools[tool_name] = {
            "name": tool_name,
            "description": description,
            "server_api_key": self.api_key,
            "input_schema": input_schema,
        }
        self.handlers[tool_name] = handler

    def to_info(self) -> dict[str, Any]:
        return {
            "api_key": self.api_key,
            "name": self.name,
            "description": self.description,
            "domain": self.domain,
            "status": "connected",
            "tool_count": len(self.tools),
            "tools": list(self.tools.keys()),
        }


class ServerRegistry:
    """MCP Server 注册中心"""

    def __init__(self):
        self._servers: dict[str, McpServer] = {}
        self._tool_to_server: dict[str, str] = {}

    def register_server(self, server: McpServer):
        """注册 MCP Server"""
        self._servers[server.api_key] = server
        for tool_name in server.tools:
            self._tool_to_server[tool_name] = server.api_key
        logger.info("[MCP] 注册 Server: %s (%d tools)", server.api_key, len(server.tools))

    def resolve_server(self, tool_name: str, server_api_key: str = "") -> McpServer:
        """根据 tool_name 或 server_api_key 找到 Server

        Args:
            tool_name: Tool 名称。
            server_api_key: 强制指定 Server（可选）。

        Raises:
            KeyError: 找不到对应 Server 或 Tool。
        """
        if server_api_key:
            server = self._servers.get(server_api_key)
            if not server:
                raise KeyError(f"MCP Server '{server_api_key}' 不存在，已注册: {list(self._servers.keys())}")
            if tool_name not in server.tools:
                raise KeyError(f"Tool '{tool_name}' 不在 Server '{server_api_key}' 中，可用: {list(server.tools.keys())}")
            return server

        # 自动路由
        target_key = self._tool_to_server.get(tool_name)
        if not target_key:
            raise KeyError(f"MCP Tool '{tool_name}' 未注册，可用: {list(self._tool_to_server.keys())}")
        return self._servers[target_key]

    async def call_tool(self, tool_name: str, arguments: dict, server_api_key: str = "") -> dict[str, Any]:
        """执行 MCP Tool"""
        server = self.resolve_server(tool_name, server_api_key)
        handler = server.handlers[tool_name]
        return await handler(arguments)

    def list_tools(self, server_api_key: str = "") -> list[dict[str, Any]]:
        """列出 Tool"""
        if server_api_key:
            server = self._servers.get(server_api_key)
            if not server:
                return []
            return list(server.tools.values())
        all_tools = []
        for server in self._servers.values():
            all_tools.extend(server.tools.values())
        return all_tools

    def list_servers(self) -> list[dict[str, Any]]:
        """列出所有 Server"""
        return [s.to_info() for s in self._servers.values()]
