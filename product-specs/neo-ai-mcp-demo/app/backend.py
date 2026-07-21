"""Backend 调用层 — 通过 FeignClient 调用 Provider 服务

服务名和地址从 config/servers.yaml 读取。
生产环境替换 HttpxTransport 为 NeoApiTransport 即可自动传递上下文+trace。
"""
from __future__ import annotations

import logging
from typing import Any

from neo_ai_registry.feign import ToolFeignClient, ServiceResolver
from neo_ai_registry.feign.transport import HttpxTransport

logger = logging.getLogger(__name__)

# server_api_key → FeignClient 映射
_clients: dict[str, ToolFeignClient] = {}

# tool_name → server_api_key 映射
_tool_server_map: dict[str, str] = {}


def init_backend(server_backends: dict[str, dict[str, str]]):
    """初始化所有 Server 的 Backend FeignClient

    Args:
        server_backends: server_api_key → {"service_name": "...", "url": "..."} 映射。
    """
    for server_key, cfg in server_backends.items():
        service_name = cfg.get("service_name", "")
        url = cfg.get("url", "")
        if not service_name or not url:
            logger.warning("Server '%s' backend 配置不完整，跳过", server_key)
            continue

        resolver = ServiceResolver(static_map={service_name: url})
        transport = HttpxTransport(resolver=resolver)
        _clients[server_key] = ToolFeignClient(app_name=service_name, transport=transport)
        logger.info("[Backend] %s → %s (%s)", server_key, service_name, url)


def register_tool_server(tool_name: str, server_api_key: str):
    """注册 tool_name → server_api_key 映射"""
    _tool_server_map[tool_name] = server_api_key


async def call_provider_tool(
    api_key: str,
    arguments: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """调用后端 Provider 服务（通过 NeoApiTransport 自动传递上下文+trace）

    Args:
        api_key: Tool 唯一标识。
        arguments: Tool 入参。
        context: 执行上下文（可选）。
    """
    server_key = _tool_server_map.get(api_key)
    if not server_key:
        raise KeyError(f"Tool '{api_key}' 未映射到任何 Server")

    client = _clients.get(server_key)
    if not client:
        raise RuntimeError(f"Server '{server_key}' 的 Backend 未初始化")

    logger.info("[MCP→Backend] %s → %s", api_key, server_key)
    return client.execute_tool(api_key, arguments, context)
