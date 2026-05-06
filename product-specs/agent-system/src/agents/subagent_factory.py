"""SubagentFactory — 独立子 Agent 工厂

对齐 v2 subagents/factory.py：
- default 模式：克隆 Lead Agent 配置
- 指定 agent：从 SubagentRegistry 查找 SubagentConfig
- 中间件三级策略：显式指定 > inherit > 最小集
- LRU 缓存 + 深度限制
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from src.core.exceptions import SkillExecutionError
from src.agents.subagent_config import SubagentConfig, SubagentRegistry

logger = logging.getLogger(__name__)

_MINIMAL_MIDDLEWARE = ["logging", "tool_error_handling"]


class SubagentFactory:
    """独立子 Agent 工厂 — 根据 SubagentConfig 构建完整子 Agent"""

    def __init__(
        self,
        lead_model: BaseChatModel,
        lead_system_prompt: str = "",
        lead_skill_names: list[str] | None = None,
        subagent_registry: SubagentRegistry | None = None,
        lead_tool_loader: Any = None,
        max_depth: int = 3,
        cache_size: int = 10,
        checkpointer: Any = None,
    ) -> None:
        self._lead_model = lead_model
        self._lead_system_prompt = lead_system_prompt
        self._lead_skill_names = lead_skill_names or []
        self._registry = subagent_registry or SubagentRegistry()
        self._lead_tool_loader = lead_tool_loader
        self._max_depth = max_depth
        self._cache: OrderedDict[str, CompiledStateGraph] = OrderedDict()
        self._cache_size = cache_size
        self._checkpointer = checkpointer

    async def get_or_build(self, agent_name: str, current_depth: int = 0) -> CompiledStateGraph:
        """获取或构建子 Agent 实例"""
        if current_depth >= self._max_depth:
            raise SkillExecutionError(
                skill_name=agent_name,
                detail=f"超过最大子 Agent 嵌套深度 ({self._max_depth})",
            )

        cache_key = f"{agent_name}:depth={current_depth}"
        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        config = self._resolve_config(agent_name)
        agent = await self._build_agent(config, current_depth)

        self._cache[cache_key] = agent
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

        return agent

    # 兼容 AgentFactory.build 接口
    async def build(self, agent_name: str, current_depth: int = 0) -> CompiledStateGraph:
        return await self.get_or_build(agent_name, current_depth)

    def _resolve_config(self, agent_name: str) -> SubagentConfig:
        """解析子 Agent 配置：default 克隆 Lead，其他从 Registry 查找"""
        if agent_name == "default":
            return self._config_from_lead()

        config = self._registry.get_config(agent_name)
        if config is None:
            raise SkillExecutionError(
                skill_name=agent_name,
                detail=f"子 Agent '{agent_name}' 配置不存在",
            )
        return config

    def _config_from_lead(self) -> SubagentConfig:
        """从 Lead Agent 配置生成 default SubagentConfig"""
        return SubagentConfig(
            name="default",
            description="Default sub-agent (cloned from Lead Agent)",
            system_prompt="",
            model="",
            middleware_names=[],
            inherit_middleware=True,
            tool_names=[],
            skill_names=list(self._lead_skill_names),
            features={},
        )

    async def _build_agent(self, config: SubagentConfig, depth: int) -> CompiledStateGraph:
        """根据 SubagentConfig 构建完整子 Agent"""
        from langchain.agents import create_agent
        from src.agents.langchain_agent import adapt_tools
        from src.skills.base import SkillExecutor
        from src.tools.skills_tool import SkillsTool as PydanticSkillsTool
        from src.tools.agent_tool import AgentTool
        from src.tools.loader import ToolLoader
        from src.core.prompt_builder import build_system_prompt, build_fork_prompt

        logger.info("构建子 Agent: name=%s, depth=%d, inherit_mw=%s",
                     config.name, depth, config.inherit_middleware)

        model = self._lead_model

        # 1. ToolLoader
        tool_loader = ToolLoader()

        # 加载专属工具或继承 Lead Agent 工具
        if config.tool_names and self._lead_tool_loader is not None:
            for tool_name in config.tool_names:
                existing = self._lead_tool_loader._registry.get(tool_name)
                if existing is not None:
                    tool_loader.register_tool(tool_name, existing)
                else:
                    logger.warning("子 Agent '%s' 指定的工具 '%s' 未找到", config.name, tool_name)
        elif self._lead_tool_loader is not None:
            skip = {"skills_tool", "agent_tool"}
            for name, tool in self._lead_tool_loader._registry.items():
                if name not in skip:
                    tool_loader.register_tool(name, tool)

        # 2. SkillsTool（子 Agent 也能调技能）
        # 简化：子 Agent 不再递归注册 SkillsTool，避免复杂度

        # 3. AgentTool（子 Agent 也能 fork）
        tool_loader.register_tool("agent_tool", AgentTool(
            agent_factory=self,
            parent_thread_id=f"sub-{config.name}",
            current_depth=depth + 1,
        ))

        all_tools = tool_loader.load_tools()

        # 4. 中间件三级策略
        middleware = self._build_agent_middleware(config)

        # 5. 系统提示词
        if config.system_prompt:
            system_prompt = config.system_prompt
        else:
            system_prompt = self._lead_system_prompt

        # 6. 创建 Agent
        agent = create_agent(
            model=model,
            tools=all_tools if all_tools else None,
            system_prompt=system_prompt,
            middleware=tuple(middleware),
            checkpointer=self._checkpointer,
            name=f"sub-{config.name}",
        )

        logger.info("子 Agent 构建完成: name=%s, tools=%d, middleware=%d, depth=%d",
                     config.name, len(all_tools), len(middleware), depth)
        return agent

    def _build_agent_middleware(self, config: SubagentConfig) -> list:
        """中间件三级策略：显式指定 > inherit > 最小集"""
        from src.middleware.builder import build_middleware, _build_middleware_by_names

        # 1. 显式指定了中间件列表
        if config.middleware_names:
            return _build_middleware_by_names(config.middleware_names, config.middleware_config)

        # 2. inherit_middleware=True → 继承 Lead Agent 全量
        if config.inherit_middleware:
            return build_middleware(agent_name=f"sub-{config.name}")

        # 3. inherit_middleware=False → 最小中间件集
        return _build_middleware_by_names(_MINIMAL_MIDDLEWARE, {})

    def invalidate(self, agent_name: str | None = None) -> None:
        if agent_name is None:
            self._cache.clear()
        else:
            keys = [k for k in self._cache if k.startswith(f"{agent_name}:")]
            for k in keys:
                del self._cache[k]
