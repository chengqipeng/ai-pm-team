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

        # Tool 注册表
        self._tools: dict[str, ToolDefinition] = {}

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

        # 1. 扫描 Builtin Tools
        tools_dir = os.path.join(root, config.scan.tools_dir)
        builtin_tools = discover_tools(tools_dir)
        self._tools.update(builtin_tools)

        # 2. 注册 Remote Tools
        for tool_cfg in config.tools:
            self._tools[tool_cfg.api_key] = ToolDefinition(
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
            )

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
            len(self._tools), len(builtin_tools), len(config.tools),
            len(self._builtin_middlewares) + len(self._remote_middleware_defs),
            len(self._builtin_middlewares), len(self._remote_middleware_defs),
        )

    # ═══════════════════════════════════════════════════════════
    # Middleware — 返回 AgentMiddleware 列表
    # ═══════════════════════════════════════════════════════════

    def get_middlewares(self) -> list:
        """获取完整的 AgentMiddleware 列表（builtin + remote 已转换）

        Remote middleware 通过 MiddlewareDefinition.to_agent_middleware() 转换，
        只覆写 hooks 中声明的方法。

        Returns:
            AgentMiddleware 实例列表（builtin 在前，remote 按 sort_num 排序在后）。
        """
        remote_mws = MiddlewareDefinition.to_agent_middlewares(
            self._remote_middleware_defs, self._transport
        )
        return self._builtin_middlewares + remote_mws

    # ═══════════════════════════════════════════════════════════
    # Tool 执行
    # ═══════════════════════════════════════════════════════════

    async def async_execute_tool(
        self,
        api_key: str,
        input_data: dict[str, Any],
        agent_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行 Tool — 异步入口

        builtin: 直接 await execute()
        remote: await FeignClient（通过 Transport → Eureka/HTTP）

        Args:
            api_key: Tool 唯一标识。
            input_data: Tool 入参。
            agent_state: AgentState dict（remote 模式自动转换 ToolState 并 write_back）。

        Returns:
            执行结果 dict。
        """
        tool = self._tools.get(api_key)
        if not tool:
            raise KeyError(f"Tool '{api_key}' 未注册，已配置: {list(self._tools.keys())}")

        if tool.is_builtin():
            context = dict(agent_state or {})
            return await tool.execute(input_data, context)
        else:
            return await self._async_remote_tool(tool, input_data, agent_state)

    def execute_tool(
        self,
        api_key: str,
        input_data: dict[str, Any],
        agent_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行 Tool — 同步入口（兼容非 async 场景）"""
        import asyncio

        tool = self._tools.get(api_key)
        if not tool:
            raise KeyError(f"Tool '{api_key}' 未注册，已配置: {list(self._tools.keys())}")

        if tool.is_builtin():
            context = dict(agent_state or {})
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, tool.execute(input_data, context)).result()
            return asyncio.run(tool.execute(input_data, context))
        else:
            from neo_ai_registry.state import ToolState
            tool_state = ToolState.from_agent_state(agent_state or {})
            client = self._get_tool_client(tool.service)
            response = client.execute_tool(tool.api_key, input_data, state=tool_state)
            if agent_state is not None:
                tool_state.write_back(agent_state)
            return response.get("result", response)

    async def _async_remote_tool(self, tool: ToolDefinition, input_data: dict, agent_state: dict | None) -> dict:
        """异步远程调用 Tool（FeignClient + ToolState 双向传递）"""
        from neo_ai_registry.state import ToolState

        tool_state = ToolState.from_agent_state(agent_state or {})
        client = self._get_tool_client(tool.service)
        response = await client.async_execute_tool(tool.api_key, input_data, state=tool_state)

        if agent_state is not None:
            patch = tool_state.write_back(agent_state)
            if patch:
                logger.info("[AgentRegistry] state write_back: %s", patch)

        return response.get("result", response)

    # ═══════════════════════════════════════════════════════════
    # 查询
    # ═══════════════════════════════════════════════════════════

    def get_tools(self) -> list[ToolDefinition]:
        """获取所有 Tool 定义列表"""
        return list(self._tools.values())

    def get_tool(self, api_key: str) -> ToolDefinition | None:
        """按 api_key 获取单个 Tool"""
        return self._tools.get(api_key)

    @property
    def tool_keys(self) -> list[str]:
        return list(self._tools.keys())

    def summary(self) -> dict[str, Any]:
        """注册数据汇总"""
        builtin_t = [k for k, v in self._tools.items() if v.is_builtin()]
        remote_t = [k for k, v in self._tools.items() if not v.is_builtin()]
        return {
            "builtin_tools": builtin_t,
            "remote_tools": remote_t,
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
