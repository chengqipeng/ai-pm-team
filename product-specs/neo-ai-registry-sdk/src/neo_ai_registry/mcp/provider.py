"""McpProvider — neo-ai-mcp-service 暴露的抽象接口"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from neo_ai_registry.mcp.models import McpToolDefinition, McpServerInfo


class McpProvider(ABC):
    """MCP Provider 抽象接口

    neo-ai-mcp-service 实现此接口，对外暴露 MCP Tool 调用和管理能力。
    Agent 运行时通过 McpFeignClient 远程调用。
    """

    @abstractmethod
    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        server_api_key: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """调用 MCP Tool

        Args:
            tool_name: MCP Tool 名称（如 "query_records"、"search_knowledge"）。
                       对应 MCP 协议中 tools/call 的 name 字段。
            arguments: Tool 入参字典，字段由 McpToolDefinition.input_schema 约束。
                       对应 MCP 协议中 tools/call 的 arguments 字段。
            server_api_key: 指定 MCP Server（可选）。为空时由 mcp-service 根据 tool_name 自动路由。
                            指定时强制在该 Server 上执行。
            context: 执行上下文（可选），包含：
                     - tenant_id (int): 租户 ID — MCP Service 用于租户隔离
                     - user_id (int): 用户 ID — MCP Service 用于权限校验
                     - thread_id (str): Agent 会话 ID
                     - message_id (str): 当前消息 ID
                     - trace_id (str): 链路追踪 ID

        Returns:
            MCP Tool 执行结果字典，格式由各 MCP Server 的 Tool 实现决定。
            通常包含 content 字段（MCP 协议标准返回）。

        Raises:
            KeyError: tool_name 在所有已连接的 MCP Server 中未找到。
            Exception: MCP Server 调用失败。
        """
        ...

    @abstractmethod
    def list_tools(self, server_api_key: str = "") -> list[McpToolDefinition]:
        """列出可用的 MCP Tool

        Args:
            server_api_key: 按 MCP Server 过滤（可选）。为空时返回所有已连接 Server 的全部 Tool。

        Returns:
            McpToolDefinition 列表。
        """
        ...

    @abstractmethod
    def list_servers(self) -> list[McpServerInfo]:
        """列出所有已连接的 MCP Server

        Returns:
            McpServerInfo 列表，包含各 Server 的连接状态和 Tool 数量。
        """
        ...
