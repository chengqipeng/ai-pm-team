"""MCP 对外接口 — 统一路由层

所有 MCP 调用通过此路由层，内部根据 tool_name / server_api_key 路由到对应 Server。

接口规范（与 McpFeignClient 调用路径一致）：
    POST /v2/mcp/tools/call     → 调用 MCP Tool
    GET  /v2/mcp/tools          → 列出 MCP Tool
    GET  /v2/mcp/servers        → 列出 MCP Server
"""
from fastapi import APIRouter, HTTPException

from app.servers import server_registry

router = APIRouter()


@router.post("/v2/mcp/tools/call")
async def call_tool(request: dict):
    """调用 MCP Tool — 根据 tool_name 自动路由或按 server_api_key 指定

    请求体：
        {
            "tool_name": "query_records",
            "arguments": {"entity": "account", "limit": 5},
            "server_api_key": "",   (可选，为空自动路由)
            "context": {"tenant_id": 1, "user_id": 100}
        }
    """
    tool_name = request.get("tool_name", "")
    arguments = request.get("arguments", {})
    server_api_key = request.get("server_api_key", "")
    context = request.get("context", {})

    try:
        result = await server_registry.call_tool(tool_name, arguments, server_api_key)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"code": 0, "data": result}


@router.get("/v2/mcp/tools")
async def list_tools(server_api_key: str = ""):
    """列出 MCP Tool

    Query Params:
        server_api_key: 按 Server 过滤（可选）
    """
    tools = server_registry.list_tools(server_api_key)
    return {"code": 0, "data": tools}


@router.get("/v2/mcp/servers")
async def list_servers():
    """列出所有已注册的 MCP Server"""
    servers = server_registry.list_servers()
    return {"code": 0, "data": servers}
