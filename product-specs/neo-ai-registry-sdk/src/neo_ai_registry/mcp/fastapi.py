"""MCP FastAPI 集成 — 一行代码创建 MCP Service 应用

从 YAML 配置加载 Server/Tool 定义，自动：
- 按域划分 StreamableHTTP 对外接口
- 内部 REST 接口供 Agent FeignClient 调用
- 所有 Tool handler 自动生成（调下游 Provider）

Usage:
    from neo_ai_registry.mcp.fastapi import create_mcp_app

    app = create_mcp_app(config_path="config/registry.yaml")
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse

logger = logging.getLogger(__name__)


def create_mcp_app(
    config_path: str = "config/registry.yaml",
    title: str = "Neo AI MCP Service",
    version: str = "0.1.0",
) -> FastAPI:
    """一行代码创建完整 MCP Service 应用

    自动处理：
    - 从 YAML 加载 Server/Tool 定义 + 服务发现配置
    - 为每个 Tool 自动生成 handler（FeignClient 调下游 Provider）
    - 生成按域划分的 StreamableHTTP 对外接口（/mcp/v2.0/{domain}）
    - 生成内部 REST 接口（/v2/mcp/tools/call + /v2/mcp/tools + /v2/mcp/servers）

    Args:
        config_path: registry.yaml 配置文件路径。
        title: FastAPI 标题。
        version: 版本号。

    Returns:
        完整配置的 FastAPI 应用实例。
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"MCP 配置文件不存在: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # 解析配置 → 构建内部数据结构
    servers, tool_index, clients = _build_from_config(raw)

    # 创建 FastAPI app
    app = FastAPI(title=title, version=version)

    # 对外 MCP StreamableHTTP 接口（按域划分）
    mcp_router = _create_mcp_protocol_router(servers, tool_index, clients)
    app.include_router(mcp_router)

    # 内部 REST 接口（Agent FeignClient 调用）
    internal_router = _create_internal_router(servers, tool_index, clients)
    app.include_router(internal_router)

    # health
    @app.get("/health")
    def health():
        endpoints = {s["domain"]: f"/mcp/v2.0/{s['domain']}" for s in servers.values()}
        return {
            "status": "ok",
            "mcp_endpoints": endpoints,
            "servers": len(servers),
            "total_tools": sum(len(s["tools"]) for s in servers.values()),
        }

    return app


# ═══════════════════════════════════════════════════════════
# 内部构建
# ═══════════════════════════════════════════════════════════

def _build_from_config(raw: dict) -> tuple[dict, dict, dict]:
    """从 YAML 配置构建内部数据结构

    服务发现策略：
    - 开发环境：从 service_discovery 读取静态映射
    - 生产环境：ServiceResolver 自动通过 Eureka/K8s DNS 解析

    Returns:
        servers: {server_api_key: {name, domain, tools: {tool_name: {desc, schema}}}}
        tool_index: {tool_name: server_api_key}
        clients: {server_api_key: ToolFeignClient}
    """
    from neo_ai_registry.feign import ToolFeignClient, ServiceResolver
    from neo_ai_registry.feign.transport import HttpxTransport

    # 读取服务发现静态映射（开发环境）
    static_map = raw.get("service_discovery", {}) or {}

    # 构建统一的 ServiceResolver（所有 server 共用）
    resolver = ServiceResolver(static_map=static_map) if static_map else ServiceResolver()
    transport = HttpxTransport(resolver=resolver)

    servers: dict[str, dict[str, Any]] = {}
    tool_index: dict[str, str] = {}
    clients: dict[str, ToolFeignClient] = {}

    for server_cfg in raw.get("servers", []):
        server_key = server_cfg["api_key"]
        backend = server_cfg.get("backend", {})

        # 通过 service_name 构建 FeignClient（无需 url）
        service_name = backend.get("service_name", "")
        if service_name:
            clients[server_key] = ToolFeignClient(app_name=service_name, transport=transport)

        # 解析 Tools
        tools = {}
        for tool_cfg in server_cfg.get("tools", []):
            tool_name = tool_cfg["name"]
            tools[tool_name] = {
                "name": tool_name,
                "description": tool_cfg.get("description", ""),
                "input_schema": tool_cfg.get("input_schema", {"type": "object", "properties": {}}),
            }
            tool_index[tool_name] = server_key

        servers[server_key] = {
            "api_key": server_key,
            "name": server_cfg.get("name", ""),
            "description": server_cfg.get("description", ""),
            "domain": server_cfg.get("domain", ""),
            "tools": tools,
        }

    logger.info("MCP app 构建完成: %d servers, %d tools", len(servers), len(tool_index))
    return servers, tool_index, clients


async def _call_backend(clients: dict, tool_index: dict, tool_name: str, arguments: dict) -> dict:
    """调用下游 Provider"""
    server_key = tool_index.get(tool_name)
    if not server_key:
        raise KeyError(f"MCP Tool '{tool_name}' 未注册，可用: {list(tool_index.keys())}")
    client = clients.get(server_key)
    if not client:
        raise RuntimeError(f"Server '{server_key}' 无 Backend 客户端")
    return client.execute_tool(tool_name, arguments)


# ═══════════════════════════════════════════════════════════
# 内部 REST 路由（Agent FeignClient 调用）
# ═══════════════════════════════════════════════════════════

def _create_internal_router(servers: dict, tool_index: dict, clients: dict) -> APIRouter:
    router = APIRouter()

    @router.post("/v2/mcp/tools/call")
    async def call_tool(request: dict):
        tool_name = request.get("tool_name", "")
        arguments = request.get("arguments", {})
        try:
            result = await _call_backend(clients, tool_index, tool_name, arguments)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        return {"code": 0, "data": result}

    @router.get("/v2/mcp/tools")
    async def list_tools(server_api_key: str = ""):
        all_tools = []
        for sk, s in servers.items():
            if server_api_key and sk != server_api_key:
                continue
            for t in s["tools"].values():
                all_tools.append({**t, "server_api_key": sk})
        return {"code": 0, "data": all_tools}

    @router.get("/v2/mcp/servers")
    async def list_servers():
        result = []
        for s in servers.values():
            result.append({
                "api_key": s["api_key"],
                "name": s["name"],
                "description": s["description"],
                "domain": s["domain"],
                "status": "connected",
                "tool_count": len(s["tools"]),
                "tools": list(s["tools"].keys()),
            })
        return {"code": 0, "data": result}

    return router


# ═══════════════════════════════════════════════════════════
# 对外 MCP StreamableHTTP 路由（按域划分）
# ═══════════════════════════════════════════════════════════

def _create_mcp_protocol_router(servers: dict, tool_index: dict, clients: dict) -> APIRouter:
    router = APIRouter()

    MCP_VERSION = "2025-03-26"

    # 收集 domain → server_key 映射
    domain_map: dict[str, str] = {}
    for s in servers.values():
        if s["domain"]:
            domain_map[s["domain"]] = s["api_key"]

    def _jsonrpc_response(id, result):
        return {"jsonrpc": "2.0", "id": id, "result": result}

    def _jsonrpc_error(id, code, message, data=None):
        err = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return {"jsonrpc": "2.0", "id": id, "error": err}

    def _make_post_handler(server_key: str, backend_clients: dict, tool_idx: dict):
        server = servers[server_key]

        async def handler(request: Request):
            body = await request.json()

            if isinstance(body, list):
                responses = []
                for item in body:
                    r = await _dispatch(item, server, server_key, backend_clients, tool_idx)
                    if r:
                        responses.append(r)
                return JSONResponse(content=responses) if responses else JSONResponse(content=None, status_code=202)

            resp = await _dispatch(body, server, server_key, backend_clients, tool_idx)
            if resp is None:
                return JSONResponse(content=None, status_code=202)
            return JSONResponse(content=resp)

        async def _dispatch(body, server, server_key, cls, tidx):
            method = body.get("method", "")
            params = body.get("params", {})
            id = body.get("id")

            if id is None:
                return None

            if method == "initialize":
                return _jsonrpc_response(id, {
                    "protocolVersion": MCP_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": server_key, "version": "0.1.0", "description": server.get("description", "")},
                })
            elif method == "tools/list":
                tools = [{"name": t["name"], "description": t["description"], "inputSchema": t["input_schema"]} for t in server["tools"].values()]
                return _jsonrpc_response(id, {"tools": tools})
            elif method == "tools/call":
                tool_name = params.get("name", "")
                arguments = params.get("arguments", {})
                if tool_name not in server["tools"]:
                    return _jsonrpc_error(id, -32601, f"Tool '{tool_name}' not found in {server_key}", list(server["tools"].keys()))
                try:
                    result = await _call_backend(cls, tidx, tool_name, arguments)
                except Exception as e:
                    return _jsonrpc_error(id, -32603, f"Tool execution failed: {e}")
                if isinstance(result, dict) and "content" in result.get("result", result):
                    inner = result.get("result", result)
                    return _jsonrpc_response(id, {"content": inner.get("content", [])})
                return _jsonrpc_response(id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})
            else:
                return _jsonrpc_error(id, -32601, f"Method not found: {method}")

        return handler

    def _make_get_handler(domain: str):
        async def handler(request: Request):
            async def stream():
                yield f"event: endpoint\ndata: /mcp/v2.0/{domain}\n\n"
            return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
        return handler

    # 为每个域注册路由
    for domain, server_key in domain_map.items():
        post_handler = _make_post_handler(server_key, clients, tool_index)
        get_handler = _make_get_handler(domain)

        router.add_api_route(f"/mcp/v2.0/{domain}", post_handler, methods=["POST"])
        router.add_api_route(f"/mcp/v2.0/{domain}", get_handler, methods=["GET"])

    return router
