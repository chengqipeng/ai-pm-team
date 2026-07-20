"""配置加载器 — 从 YAML 加载 MCP Server/Tool 定义

启动时从 config/servers.yaml 加载，注册到 ServerRegistry。
每个 Server 有独立的 backend 配置，指向不同的后端微服务。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from app.servers.registry import ServerRegistry, McpServer

logger = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "config", "servers.yaml",
)


def load_servers(registry: ServerRegistry, config_path: str = "") -> dict[str, dict[str, str]]:
    """从配置文件加载 MCP Server 和 Tool

    Args:
        registry: 目标 ServerRegistry 实例。
        config_path: 配置文件路径。

    Returns:
        server_backends: server_api_key → backend 配置的映射。
    """
    path = Path(config_path or _CONFIG_PATH)
    if not path.exists():
        raise FileNotFoundError(f"MCP 配置文件不存在: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    from app.backend import register_tool_server, call_provider_tool

    server_backends: dict[str, dict[str, str]] = {}

    for server_cfg in raw.get("servers", []):
        server_key = server_cfg["api_key"]

        # 提取 backend 配置
        backend_cfg = server_cfg.get("backend", {})
        if backend_cfg:
            server_backends[server_key] = backend_cfg

        # 创建 Server
        server = McpServer(
            api_key=server_key,
            name=server_cfg.get("name", ""),
            description=server_cfg.get("description", ""),
            domain=server_cfg.get("domain", ""),
        )

        # 注册 Tool
        for tool_cfg in server_cfg.get("tools", []):
            tool_name = tool_cfg["name"]

            # 注册 tool → server 映射（供 backend 路由）
            register_tool_server(tool_name, server_key)

            # 创建 handler（闭包捕获 tool_name）
            def make_handler(name: str):
                async def handler(arguments: dict) -> dict:
                    return await call_provider_tool(name, arguments)
                return handler

            server.add_tool(
                tool_name=tool_name,
                description=tool_cfg.get("description", ""),
                input_schema=tool_cfg.get("input_schema", {"type": "object", "properties": {}}),
                handler=make_handler(tool_name),
            )

        registry.register_server(server)

    logger.info(
        "MCP 配置加载完成: %d servers, %d tools, %d backends",
        len(registry.list_servers()),
        len(registry.list_tools()),
        len(server_backends),
    )
    return server_backends
