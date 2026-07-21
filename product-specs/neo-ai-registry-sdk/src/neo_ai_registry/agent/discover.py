"""自动发现 — 扫描目录加载 Builtin Tool 和 Middleware

Usage:
    from neo_ai_registry.agent.discover import discover_tools, discover_middlewares

    tools = discover_tools("app/tools")              # {api_key: ToolDefinition}
    middlewares = discover_middlewares("app/middlewares")  # [AgentMiddleware]
"""
from __future__ import annotations

import importlib.util
import inspect
import logging
import os
from typing import Any

from neo_ai_registry.models import ToolDefinition

logger = logging.getLogger(__name__)


def discover_tools(scan_dir: str) -> dict[str, ToolDefinition]:
    """扫描目录，发现继承 ToolDefinition 并实现 execute() 的类"""
    if not scan_dir or not os.path.isdir(scan_dir):
        return {}

    tools: dict[str, ToolDefinition] = {}

    for filename in sorted(os.listdir(scan_dir)):
        if filename.startswith("_") or not filename.endswith(".py"):
            continue

        module_path = os.path.join(scan_dir, filename)
        module_name = f"builtin_tool__{filename[:-3]}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type)
                        and issubclass(attr, ToolDefinition)
                        and attr is not ToolDefinition
                        and not inspect.isabstract(attr)):
                    if not getattr(attr, "api_key", None):
                        fields = getattr(attr, "model_fields", {})
                        api_key_field = fields.get("api_key")
                        if not api_key_field or not api_key_field.default:
                            continue
                    instance = attr()
                    if instance.api_key and instance.has_execute():
                        tools[instance.api_key] = instance
                        logger.info("发现内置 Tool: %s (from %s)", instance.api_key, filename)
        except Exception:
            logger.warning("内置 Tool 加载失败: %s", module_path, exc_info=True)

    return tools


def discover_middlewares(scan_dir: str) -> list:
    """扫描目录，发现继承 AgentMiddleware 的类（Builtin Middleware）"""
    if not scan_dir or not os.path.isdir(scan_dir):
        return []

    middlewares: list = []

    for filename in sorted(os.listdir(scan_dir)):
        if filename.startswith("_") or not filename.endswith(".py"):
            continue

        module_path = os.path.join(scan_dir, filename)
        module_name = f"builtin_mw__{filename[:-3]}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if not isinstance(attr, type):
                    continue
                if (hasattr(attr, 'name')
                        and getattr(attr, 'name', None)
                        and attr.__module__ == module_name
                        and not inspect.isabstract(attr)):
                    try:
                        from langchain.agents.middleware.types import AgentMiddleware
                        if issubclass(attr, AgentMiddleware) and attr is not AgentMiddleware:
                            instance = attr()
                            middlewares.append(instance)
                            logger.info("发现内置 Middleware: %s (from %s)", attr.name, filename)
                    except ImportError:
                        pass
        except Exception:
            logger.warning("内置 Middleware 加载失败: %s", module_path, exc_info=True)

    return middlewares
