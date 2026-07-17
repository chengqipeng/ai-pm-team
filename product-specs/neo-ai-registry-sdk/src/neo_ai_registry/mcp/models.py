"""MCP 数据模型 — MCP Server 和 Tool 定义"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class McpToolDefinition(BaseModel):
    """MCP Tool 定义 — 从 MCP Server 发现的工具"""

    name: str = Field(..., description="Tool 名称（MCP 协议中的 tool name）")
    description: str = Field("", description="Tool 功能描述")
    server_api_key: str = Field("", description="所属 MCP Server 的 api_key")
    input_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema 入参定义（来自 MCP Tool.inputSchema）",
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema 出参定义（来自 MCP Tool.outputSchema，可选）",
    )


class McpServerInfo(BaseModel):
    """MCP Server 信息 — 已连接的 MCP Server 摘要"""

    api_key: str = Field(..., description="MCP Server 唯一标识")
    name: str = Field("", description="Server 显示名称")
    description: str = Field("", description="Server 功能描述")
    domain: str = Field("", description="所属业务域（crm/knowledge/metadata/platform/sandbox）")
    status: str = Field("unknown", description="连接状态（connected/disconnected/error）")
    tool_count: int = Field(0, description="该 Server 提供的 Tool 数量")
    tools: list[str] = Field(default_factory=list, description="Tool 名称列表")
