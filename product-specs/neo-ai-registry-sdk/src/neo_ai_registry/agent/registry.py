"""AgentRegistry — Agent 运行时注册器（SDK 核心集成类）

职责：
    - 注册 Builtin Tools（扫描目录）
    - 注册 Remote Tools（从 RegistryConfig）
    - 注册 Builtin Middlewares（扫描目录）
    - 注册 Remote Middlewares（从 RegistryConfig → to_agent_middleware 转换）
    - 提供 get_middlewares() → AgentMiddleware 列表
    - 提供 async_execute_tool() → Tool 统一分派

不做的事：
    - 不读文件（由 ConfigLoader 负责）
    - 不创建 Transport（由外部注入）
    - 不管 Eureka 注册（由项目启动逻辑负责）

Usage:
    from neo_ai_registry.config import ConfigLoader
    from neo_ai_registry.agent_registry import AgentRegistry
    from neo_ai_registry.feign.transport import NeoApiTransport

    config = ConfigLoader.from_yaml("config/registry.yaml")
    registry = AgentRegistry(transport=NeoApiTransport())
    registry.load(config, project_root="/path/to/project")

    # 获取 middlewares 传给 create_agent
    middlewares = registry.get_middlewares()

    # 执行 tool
    result = await registry.async_execute_tool("query_customer", input_data, agent_state)
"""
from __future__ import annotations

import logging
import os
from typing import Any

from neo_ai_registry.models import ToolDefinition, MiddlewareDefinition, ToolType
from neo_ai_registry.agent.discover import discover_tools, discover_middlewares
from neo_ai_registry.config import RegistryConfig
from neo_ai_registry.feign import ToolFeignClient

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Agent 运行时注册器 — 注册 + 分派 + 转换"""

    def __init__(self, transport: Any):
        """初始化 AgentRegistry

        Args:
            transport: Transport 实例（NeoApiTransport / HttpxTransport），由外部注入。
        """
        self._transport = transport

        # Builtin Tools（BaseTool 实例）
        self._builtin_tools: list = []
        # Remote Tools（ToolDefinition）
        self._remote_tool_defs: list[ToolDefinition] = []

        # Middleware
        self._builtin_middlewares: list = []
        self._remote_middleware_defs: list[MiddlewareDefinition] = []

        # FeignClient 连接池
        self._tool_clients: dict[str, ToolFeignClient] = {}

    def load(self, config: RegistryConfig, project_root: str = "") -> None:
        """加载注册数据（builtin 扫描 + remote 配置）

        Args:
            config: 由 ConfigLoader 解析的 RegistryConfig。
            project_root: 项目根目录（scan 路径相对于此目录）。为空时使用 CWD。
        """
        root = project_root or os.getcwd()

        # 1. 扫描 Builtin Tools（BaseTool 子类）
        tools_dir = os.path.join(root, config.scan.tools_dir)
        self._builtin_tools = discover_tools(tools_dir)

        # 2. 注册 Remote Tools（ToolDefinition）
        for tool_cfg in config.tools:
            self._remote_tool_defs.append(ToolDefinition(
                api_key=tool_cfg.api_key,
                name=tool_cfg.name,
                description=tool_cfg.description,
                domain=tool_cfg.domain,
                type=ToolType.REMOTE,
                service=tool_cfg.service,
                input_schema=tool_cfg.input_schema,
                timeout_ms=tool_cfg.timeout_ms,
                read_only_flg=tool_cfg.read_only_flg,
                category=tool_cfg.category,
                tags=tool_cfg.tags,
            ))

        # 3. 扫描 Builtin Middlewares（AgentMiddleware 子类）
        middlewares_dir = os.path.join(root, config.scan.middlewares_dir)
        self._builtin_middlewares = discover_middlewares(middlewares_dir)

        # 4. 注册 Remote Middlewares
        for mw_cfg in config.middlewares:
            self._remote_middleware_defs.append(MiddlewareDefinition(
                api_key=mw_cfg.api_key,
                name=mw_cfg.name,
                description=mw_cfg.description,
                service=mw_cfg.service,
                hooks=mw_cfg.hooks,
                sort_num=mw_cfg.sort_num,
                required_features=mw_cfg.required_features,
            ))

        logger.info(
            "[AgentRegistry] 加载完成: tools=%d (builtin=%d, remote=%d), "
            "middlewares=%d (builtin=%d, remote=%d)",
            len(self._builtin_tools) + len(self._remote_tool_defs),
            len(self._builtin_tools), len(self._remote_tool_defs),
            len(self._builtin_middlewares) + len(self._remote_middleware_defs),
            len(self._builtin_middlewares), len(self._remote_middleware_defs),
        )

    # ═══════════════════════════════════════════════════════════
    # Tool — 返回 BaseTool 列表
    # ═══════════════════════════════════════════════════════════

    def get_base_tools(self) -> list:
        """获取所有 BaseTool 列表（供 create_agent(tools=[...]) 使用）

        - Builtin tools: 直接返回（已经是 BaseTool）
        - Remote tools: 通过 ToolDefinition.to_base_tool() 转换

        Returns:
            BaseTool 实例列表。
        """
        remote_base_tools = ToolDefinition.to_base_tools(self._remote_tool_defs, self._transport)
        return self._builtin_tools + remote_base_tools

    # ═══════════════════════════════════════════════════════════
    # Middleware — 返回 AgentMiddleware 列表
    # ═══════════════════════════════════════════════════════════

    def get_middlewares(self) -> list:
        """获取完整的 AgentMiddleware 列表（builtin + remote 已转换）

        Returns:
            AgentMiddleware 实例列表。
        """
        remote_mws = MiddlewareDefinition.to_agent_middlewares(
            self._remote_middleware_defs, self._transport
        )
        return self._builtin_middlewares + remote_mws

    # ═══════════════════════════════════════════════════════════
    # 查询
    # ═══════════════════════════════════════════════════════════

    @property
    def tool_keys(self) -> list[str]:
        builtin_keys = [getattr(t, "name", "?") for t in self._builtin_tools]
        remote_keys = [d.api_key for d in self._remote_tool_defs]
        return builtin_keys + remote_keys

    def summary(self) -> dict[str, Any]:
        """注册数据汇总"""
        return {
            "builtin_tools": [getattr(t, "name", "?") for t in self._builtin_tools],
            "remote_tools": [d.api_key for d in self._remote_tool_defs],
            "builtin_middlewares": [getattr(m, "name", "?") for m in self._builtin_middlewares],
            "remote_middlewares": [d.api_key for d in self._remote_middleware_defs],
        }

    # ═══════════════════════════════════════════════════════════
    # 内部
    # ═══════════════════════════════════════════════════════════

    def _get_tool_client(self, service_name: str) -> ToolFeignClient:
        """获取或创建 ToolFeignClient（连接复用）"""
        if service_name not in self._tool_clients:
            self._tool_clients[service_name] = ToolFeignClient(
                app_name=service_name, transport=self._transport
            )
        return self._tool_clients[service_name]
