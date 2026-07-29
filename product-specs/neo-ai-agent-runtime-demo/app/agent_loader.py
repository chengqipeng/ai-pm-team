"""AgentLoader — 项目级薄包装（委托 SDK AgentRegistry）

职责：
    - 创建 Transport（NeoApiTransport）
    - 指定配置目录（config/）
    - 暴露 get_base_tools() / get_middlewares() 供 create_agent 使用

配置文件：
    config/ 目录下所有 registry*.yaml 文件会被自动扫描并合并。
    registry.yaml 作为基础配置先加载，registry-*.yaml 按文件名排序覆盖。
"""
from __future__ import annotations

import os
from typing import Any

from neo_ai_registry import AgentRegistry

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_DIR = os.path.join(_PROJECT_ROOT, "config")


class AgentLoader:
    """项目级 Agent 加载器"""

    def __init__(self, config_dir: str = ""):
        self._config_dir = config_dir or _CONFIG_DIR
        self._registry: AgentRegistry | None = None

    def load(self) -> None:
        """加载注册数据（扫描 config/ 下所有 registry*.yaml）"""
        from neo_ai_registry.feign.transport import NeoApiTransport

        self._registry = AgentRegistry(transport=NeoApiTransport())
        self._registry.load_from_dir(self._config_dir, project_root=_PROJECT_ROOT)

    def get_base_tools(self) -> list:
        """获取 BaseTool 列表（传给 create_agent(tools=[...])）"""
        return self._registry.get_base_tools()

    def get_middlewares(self) -> list:
        """获取 AgentMiddleware 列表（传给 create_agent(middleware=[...])）"""
        return self._registry.get_middlewares()

    def summary(self) -> dict[str, Any]:
        return self._registry.summary()

    @property
    def tool_keys(self) -> list[str]:
        return self._registry.tool_keys
