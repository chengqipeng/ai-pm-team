"""自动发现 — 递归扫描目录加载 Builtin Tool（BaseTool）和 Middleware（AgentMiddleware）

支持子目录递归扫描（如 app/tools/crm/query.py）。

Usage:
    from neo_ai_registry.agent.discover import discover_tools, discover_middlewares

    tools = discover_tools("app/tools")              # list[BaseTool]
    middlewares = discover_middlewares("app/middlewares")  # list[AgentMiddleware]
"""
from __future__ import annotations

import importlib.util
import inspect
import logging
import os

logger = logging.getLogger(__name__)


def discover_tools(scan_dir: str) -> list:
    """递归扫描目录，发现继承 BaseTool 的类并实例化

    Args:
        scan_dir: 扫描根目录的绝对路径。

    Returns:
        BaseTool 实例列表。
    """
    if not scan_dir or not os.path.isdir(scan_dir):
        return []

    tools: list = []

    for root, dirs, files in os.walk(scan_dir):
        dirs[:] = [d for d in dirs if not d.startswith("_")]

        for filename in sorted(files):
            if filename.startswith("_") or not filename.endswith(".py"):
                continue

            module_path = os.path.join(root, filename)
            rel_path = os.path.relpath(module_path, scan_dir).replace(os.sep, ".")
            module_name = f"builtin_tool__{rel_path[:-3]}"

            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if not isinstance(attr, type):
                    continue
                if inspect.isabstract(attr):
                    continue
                try:
                    from langchain_core.tools import BaseTool
                    if issubclass(attr, BaseTool) and attr is not BaseTool:
                        instance = attr()
                        name = getattr(instance, "name", None)
                        if name:
                            tools.append(instance)
                            logger.info("发现内置 Tool: %s (from %s)", name, os.path.relpath(module_path, scan_dir))
                except ImportError:
                    pass

    return tools


def discover_middlewares(scan_dir: str) -> list:
    """递归扫描目录，发现继承 AgentMiddleware 的类并实例化

    Args:
        scan_dir: 扫描根目录的绝对路径。

    Returns:
        AgentMiddleware 实例列表。
    """
    if not scan_dir or not os.path.isdir(scan_dir):
        return []

    middlewares: list = []

    for root, dirs, files in os.walk(scan_dir):
        dirs[:] = [d for d in dirs if not d.startswith("_")]

        for filename in sorted(files):
            if filename.startswith("_") or not filename.endswith(".py"):
                continue

            module_path = os.path.join(root, filename)
            rel_path = os.path.relpath(module_path, scan_dir).replace(os.sep, ".")
            module_name = f"builtin_mw__{rel_path[:-3]}"

            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if not isinstance(attr, type):
                    continue
                if inspect.isabstract(attr):
                    continue
                try:
                    from langchain.agents.middleware.types import AgentMiddleware
                    if issubclass(attr, AgentMiddleware) and attr is not AgentMiddleware:
                        instance = attr()
                        name = getattr(instance, "name", None)
                        if name:
                            middlewares.append(instance)
                            logger.info("发现内置 Middleware: %s (from %s)", name, os.path.relpath(module_path, scan_dir))
                except ImportError:
                    pass

    return middlewares
