"""ToolLoader — 按名注册 + 按名加载 + 目录自动发现

借鉴 neo_agent_v2 的 tools/loader.py 和 Hermes 的 discover_builtin_tools()。
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import os
from typing import Any

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


class ToolLoader:
    """工具加载器 — 按名注册 + 按名查找 + 目录自动发现"""

    def __init__(self) -> None:
        self._registry: dict[str, BaseTool] = {}

    def register_tool(self, name: str, tool: BaseTool) -> None:
        """注册工具到内部注册表"""
        self._registry[name] = tool

    def load_tools_by_names(self, tool_names: list[str]) -> list[BaseTool]:
        """按名称加载指定工具列表，找不到的跳过并警告"""
        tools: list[BaseTool] = []
        for name in tool_names:
            tool = self._registry.get(name)
            if tool is not None:
                tools.append(tool)
            else:
                logger.warning("工具 '%s' 未在注册表中找到，已跳过", name)
        return tools

    def load_tools(self) -> list[BaseTool]:
        """返回所有已注册的工具"""
        tools = list(self._registry.values())
        logger.info("已加载 %d 个工具: %s", len(tools), list(self._registry.keys()))
        return tools

    def discover_tools(self, tools_dir: str) -> list[BaseTool]:
        """从目录自动发现 BaseTool 子类并注册

        扫描 tools_dir 下所有 .py 文件，查找 BaseTool 子类并实例化。
        """
        if not tools_dir or not os.path.isdir(tools_dir):
            return []

        discovered: list[BaseTool] = []
        seen: set[str] = set()

        for filename in sorted(os.listdir(tools_dir)):
            if filename.startswith("_") or not filename.endswith(".py"):
                continue
            mod_stem = filename[:-3]
            if mod_stem in seen:
                continue
            seen.add(mod_stem)

            module_path = os.path.join(tools_dir, filename)
            module_name = f"tool_discover__{mod_stem}"

            try:
                spec = importlib.util.spec_from_file_location(module_name, module_path)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type)
                            and issubclass(attr, BaseTool)
                            and attr is not BaseTool
                            and not inspect.isabstract(attr)):
                        tool_instance = attr()
                        self.register_tool(tool_instance.name, tool_instance)
                        discovered.append(tool_instance)
                        logger.info("发现工具: %s (from %s)", tool_instance.name, filename)
            except Exception:
                logger.warning("工具加载失败: %s", module_path, exc_info=True)

        return discovered

    def __len__(self) -> int:
        return len(self._registry)

    def __contains__(self, name: str) -> bool:
        return name in self._registry
