"""MCP StreamableHTTP 对外接口 — 按业务域划分独立 MCP 端点

每个业务域一个独立的 MCP StreamableHTTP 入口：
    POST /mcp/v2.0/crm          → crm-data-mcp
    POST /mcp/v2.0/knowledge    → knowledge-mcp
    POST /mcp/v2.0/metadata     → metadata-mcp

外部 MCP Client 按需连接不同域的端点：
    Cursor 配置 CRM 数据：url = "http://host:8003/mcp/v2.0/crm"
    Cursor 配置知识库：  url = "http://host:8003/mcp/v2.0/knowledge"

协议格式：JSON-RPC 2.0 over StreamableHTTP
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse

from app.servers import server_registry
from app.servers.registry import McpServer

logger = logging.getLogger(__name__)

router = APIRouter()

MCP_PROTOCOL_VERSION = "2025-03-26"
SERVER_VERSION = "0.1.0"


# ═══════════════════════════════════════════════════════════
# JSON-RPC 通用处理
# ═══════════════════════════════════════════════════════════

def _jsonrpc_response(id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _jsonrpc_error(id: Any, code: int, message: str, data: Any = None) -> dict:
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": id, "error": error}


async def _handle_initialize(id: Any, server: McpServer) -> dict:
    """initialize — MCP 握手，返回该域 Server 的能力声明"""
    return _jsonrpc_response(id, {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {
            "tools": {"listChanged": False},
        },
        "serverInfo": {
            "name": server.api_key,
            "version": SERVER_VERSION,
            "description": server.description,
        },
    })


async def _handle_tools_list(id: Any, server: McpServer) -> dict:
    """tools/list — 列出该域 Server 的所有 Tool"""
    mcp_tools = []
    for tool in server.tools.values():
        mcp_tools.append({
            "name": tool["name"],
            "description": tool.get("description", ""),
            "inputSchema": tool.get("input_schema", {"type": "object", "properties": {}}),
        })
    return _jsonrpc_response(id, {"tools": mcp_tools})


async def _handle_tools_call(id: Any, server: McpServer, params: dict) -> dict:
    """tools/call — 在该域 Server 上执行 Tool"""
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if not tool_name:
        return _jsonrpc_error(id, -32602, "Missing required parameter: name")

    if tool_name not in server.handlers:
        available = list(server.tools.keys())
        return _jsonrpc_error(id, -32601, f"Tool '{tool_name}' not found in {server.api_key}", available)

    try:
        handler = server.handlers[tool_name]
        result = await handler(arguments)
    except Exception as e:
        return _jsonrpc_error(id, -32603, f"Tool execution failed: {e}")

    if "content" in result:
        return _jsonrpc_response(id, {"content": result["content"]})
    return _jsonrpc_response(id, {
        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]
    })


async def _dispatch(body: dict, server: McpServer) -> dict | None:
    """分发 JSON-RPC 请求到对应 handler"""
    method = body.get("method", "")
    params = body.get("params", {})
    id = body.get("id")

    # Notification（无 id）
    if id is None:
        logger.info("[MCP:%s] notification: %s", server.api_key, method)
        return None

    if method == "initialize":
        return await _handle_initialize(id, server)
    elif method == "tools/list":
        return await _handle_tools_list(id, server)
    elif method == "tools/call":
        return await _handle_tools_call(id, server, params)
    else:
        return _jsonrpc_error(id, -32601, f"Method not found: {method}")


def _create_mcp_post_handler(server_api_key: str):
    """工厂函数 — 为每个业务域创建 POST handler"""

    async def handler(request: Request):
        server = server_registry._servers.get(server_api_key)
        if not server:
            return JSONResponse(
                content=_jsonrpc_error(None, -32600, f"Server '{server_api_key}' not available"),
                status_code=500,
            )

        body = await request.json()

        # 批量请求
        if isinstance(body, list):
            responses = []
            for item in body:
                resp = await _dispatch(item, server)
                if resp is not None:
                    responses.append(resp)
            if responses:
                return JSONResponse(content=responses)
            return JSONResponse(content=None, status_code=202)

        # 单个请求
        response = await _dispatch(body, server)
        if response is None:
            return JSONResponse(content=None, status_code=202)
        return JSONResponse(content=response)

    return handler


def _create_mcp_get_handler(server_api_key: str):
    """工厂函数 — 为每个业务域创建 GET SSE handler"""

    async def handler(request: Request):
        async def event_stream():
            yield f"event: endpoint\ndata: /mcp/v2.0/{server_api_key.replace('-mcp', '')}\n\n"
        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    return handler


# ═══════════════════════════════════════════════════════════
# 按业务域注册路由
# ═══════════════════════════════════════════════════════════

# 域名 → server_api_key 映射
_DOMAIN_ROUTES = {
    "crm": "crm-data-mcp",
    "knowledge": "knowledge-mcp",
    "metadata": "metadata-mcp",
}

# 为每个业务域创建独立的 POST/GET 端点
for domain, server_key in _DOMAIN_ROUTES.items():
    router.add_api_route(
        f"/mcp/v2.0/{domain}",
        _create_mcp_post_handler(server_key),
        methods=["POST"],
        summary=f"MCP StreamableHTTP — {domain}",
        description=f"业务域 '{domain}' 的 MCP 协议入口（JSON-RPC 2.0）。Server: {server_key}",
    )
    router.add_api_route(
        f"/mcp/v2.0/{domain}",
        _create_mcp_get_handler(server_key),
        methods=["GET"],
        summary=f"MCP SSE — {domain}",
        description=f"业务域 '{domain}' 的 SSE 端点。",
    )
