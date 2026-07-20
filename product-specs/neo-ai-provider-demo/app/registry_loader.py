"""Registry 配置加载器 — 从 YAML 加载 Tool/Middleware 定义并匹配 handler

启动时从 config/tools.yaml 加载注册配置，自动匹配 handler 函数并注册到 Registry。
Handler 通过 api_key 在 handler_map 中查找（业务代码只需提供 handler 函数）。

Usage:
    from app.registry_loader import load_registry

    registry = load_registry()
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from neo_ai_registry import Registry, ToolDefinition, MiddlewareDefinition, ToolType, MiddlewareHook

logger = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "config", "tools.yaml",
)


def load_registry(config_path: str = "", domain: str = "sales") -> Registry:
    """从配置文件加载 Tool/Middleware 定义并注册到 Registry

    Args:
        config_path: 配置文件路径。为空使用默认 config/tools.yaml。
        domain: 业务域标识。

    Returns:
        已加载完成的 Registry 实例。
    """
    path = Path(config_path or _CONFIG_PATH)
    if not path.exists():
        raise FileNotFoundError(f"注册配置不存在: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    registry = Registry(domain=domain)

    # 加载 handler map
    tool_handler_map = _build_tool_handler_map()
    mw_handler_map = _build_middleware_handler_map()

    # 注册 Tool
    for item in raw.get("tools", []):
        api_key = item["api_key"]
        handler = tool_handler_map.get(api_key)
        if not handler:
            logger.warning("Tool '%s' 无对应 handler，跳过", api_key)
            continue

        tool_def = ToolDefinition(
            api_key=api_key,
            name=item.get("name", ""),
            description=item.get("description", ""),
            type=ToolType(item.get("type", "remote")),
            category=item.get("category", ""),
            tags=item.get("tags", []),
            timeout_ms=item.get("timeout_ms", 5000),
            read_only_flg=item.get("read_only_flg", True),
            input_schema=item.get("input_schema", {}),
        )
        registry.register_tool(tool_def, handler=handler)

    # 注册 Middleware
    for item in raw.get("middlewares", []):
        api_key = item["api_key"]
        handler = mw_handler_map.get(api_key)
        if not handler:
            logger.warning("Middleware '%s' 无对应 handler，跳过", api_key)
            continue

        mw_def = MiddlewareDefinition(
            api_key=api_key,
            name=item.get("name", ""),
            description=item.get("description", ""),
            hooks=[MiddlewareHook(h) for h in item.get("hooks", [])],
            module_path=item.get("module_path", ""),
            class_name=item.get("class_name", ""),
            sort_num=item.get("sort_num", 0),
            required_features=item.get("required_features", []),
        )
        registry.register_middleware(mw_def, handler=handler)

    logger.info("Registry 配置加载完成: %s", registry.summary())
    return registry


def _build_tool_handler_map() -> dict[str, Any]:
    """构建 api_key → handler 映射表

    所有 handler 函数在各自模块中定义，此处统一注册映射关系。
    新增 Tool 只需：1. 在配置文件加一行  2. 在对应 handler 文件写函数  3. 这里加一行映射
    """
    from app.tool_handlers import query_customer, update_opportunity, analyze_pipeline
    from app.mcp_tool_handlers import (
        query_records, get_record_details, create_record,
        search_knowledge, list_knowledge_bases,
        list_entities, get_entity_fields,
    )

    return {
        # Agent 直接调用
        "query_customer": query_customer,
        "update_opportunity": update_opportunity,
        "analyze_pipeline": analyze_pipeline,
        # MCP 回调
        "query_records": query_records,
        "get_record_details": get_record_details,
        "create_record": create_record,
        "search_knowledge": search_knowledge,
        "list_knowledge_bases": list_knowledge_bases,
        "list_entities": list_entities,
        "get_entity_fields": get_entity_fields,
    }


def _build_middleware_handler_map() -> dict[str, Any]:
    """构建 api_key → middleware handler 映射表"""
    from app.middleware_handlers import crm_query_state_handler, sales_context_inject_handler

    return {
        "crm_query_state": crm_query_state_handler,
        "sales_context_inject": sales_context_inject_handler,
    }
