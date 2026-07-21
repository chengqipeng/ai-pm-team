"""AgentLoader — 项目级薄包装（委托 SDK AgentRegistry）

职责：
    - 决定 Transport 类型（NeoApiTransport）
    - 决定配置文件路径（config/registry.yaml）
    - 提供 get_base_tools() / get_middlewares() 供 create_agent 使用
"""
from __future__ import annotations

import os

from neo_ai_registry import ConfigLoader, AgentRegistry

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CONFIG = os.path.join(_PROJECT_ROOT, "config", "registry.yaml")


class AgentLoader:
    """项目级 Agent 加载器"""

    def __init__(self, config_path: str = ""):
        self._config_path = config_path or _DEFAULT_CONFIG
        self._registry: AgentRegistry | None = None

    def load(self) -> None:
        """加载注册数据"""
        from neo_ai_registry.feign.transport import NeoApiTransport

        config = ConfigLoader.from_yaml(self._config_path)
        transport = NeoApiTransport()
        self._registry = AgentRegistry(transport=transport)
        self._registry.load(config, project_root=_PROJECT_ROOT)

    def get_base_tools(self) -> list:
        """获取 BaseTool 列表（传给 create_agent(tools=[...])）"""
        return self._registry.get_base_tools()

    def get_middlewares(self) -> list:
        """获取 AgentMiddleware 列表（传给 create_agent(middleware=[...])）"""
        return self._registry.get_middlewares()

    def summary(self) -> dict:
        return self._registry.summary()

    @property
    def tool_keys(self) -> list[str]:
        return self._registry.tool_keys
