"""MCP 封装 — Agent 调用 neo-ai-mcp-service 的统一接口

提供：
    - McpToolDefinition: MCP Tool 数据模型
    - McpFeignClient: Agent 调用 MCP Service 的 FeignClient
    - McpProvider: MCP Service 暴露的抽象接口

调用链路：
    Agent 运行时 → McpFeignClient(app_name="neo-ai-mcp-service")
        → POST /v2/mcp/tools/{tool_name}/call
        → neo-ai-mcp-service → MCP Server → 返回结果

Usage:
    from neo_ai_registry.mcp import McpFeignClient, McpToolDefinition

    client = McpFeignClient(app_name="neo-ai-mcp-service", transport=transport)
    result = client.call_tool("query_records", {"entity": "account", "limit": 10}, context)
    tools = client.list_tools(server_api_key="crm-data-mcp")
"""

from neo_ai_registry.mcp.models import McpToolDefinition, McpServerInfo
from neo_ai_registry.mcp.client import McpFeignClient
from neo_ai_registry.mcp.provider import McpProvider

__all__ = [
    "McpToolDefinition",
    "McpServerInfo",
    "McpFeignClient",
    "McpProvider",
]
