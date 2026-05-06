"""AgentFactory — 唯一的 Agent 构建逻辑，LRU 缓存 + 深度限制

所有 Agent（包括 create_deep_agent 入口）都走这一份 _build_agent 流程。
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from src.core.exceptions import SkillExecutionError

logger = logging.getLogger(__name__)


class AgentFactory:
    """统一 Agent 工厂"""

    def __init__(
        self,
        default_model: BaseChatModel,
        tool_registry: Any = None,
        skill_registry: Any = None,
        subagent_registry: Any = None,
        default_system_prompt: str = "",
        default_middlewares: list | None = None,
        features: Any = None,
        memory_engine: Any = None,
        max_depth: int = 3,
        cache_size: int = 10,
        checkpointer: Any = None,
        tool_names: list[str] | None = None,
        tools_dir: str = "",
        base_dir: str = "",
        tracker: Any = None,
        optimizer: Any = None,
    ) -> None:
        self._model = default_model
        self._tool_registry = tool_registry
        self._skill_registry = skill_registry
        self._subagent_registry = subagent_registry
        self._system_prompt = default_system_prompt
        self._explicit_middlewares = default_middlewares  # None = 自动组装
        self._features = features
        self._memory_engine = memory_engine
        self._max_depth = max_depth
        self._cache: OrderedDict[str, CompiledStateGraph] = OrderedDict()
        self._cache_size = cache_size
        self._checkpointer = checkpointer
        self._tool_names = tool_names or []
        self._tools_dir = tools_dir
        self._base_dir = base_dir
        self._tracker = tracker
        self._optimizer = optimizer

    async def build(self, agent_name: str = "default", current_depth: int = 0) -> CompiledStateGraph:
        """构建或获取缓存的 Agent 实例"""
        if current_depth >= self._max_depth:
            raise SkillExecutionError(
                skill_name=agent_name,
                detail=f"超过最大 Agent 嵌套深度 ({self._max_depth})",
            )

        cache_key = f"{agent_name}:depth={current_depth}"
        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        agent = await self._build_agent(agent_name, current_depth)

        self._cache[cache_key] = agent
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

        return agent

    async def _build_agent(self, agent_name: str, depth: int) -> CompiledStateGraph:
        """唯一的 Agent 构建流程 — 对齐 v2 AgentFactory._build_agent"""
        from langchain.agents import create_agent
        from src.agents.langchain_agent import adapt_tools
        from src.skills.base import SkillExecutor
        from src.tools.skills_tool import SkillsTool as PydanticSkillsTool
        from src.tools.agent_tool import AgentTool
        from src.tools.loader import ToolLoader

        logger.info("构建 Agent: name=%s, depth=%d", agent_name, depth)

        explicit_tools = bool(self._tool_names)

        # 1. ToolLoader 统一管理
        tool_loader = ToolLoader()

        # 1a. 适配业务工具
        if self._tool_registry:
            for lc_tool in adapt_tools(self._tool_registry):
                if explicit_tools:
                    if lc_tool.name in self._tool_names:
                        tool_loader.register_tool(lc_tool.name, lc_tool)
                else:
                    tool_loader.register_tool(lc_tool.name, lc_tool)

        # 1b. 目录自动发现
        if self._tools_dir:
            tool_loader.discover_tools(self._tools_dir)

        # 2. SkillExecutor + SkillsTool
        if self._skill_registry and len(self._skill_registry.list_all()) > 0:
            from src.core.state import PluginContext
            ctx = PluginContext(llm=self._model, tool_registry=self._tool_registry)
            executor = SkillExecutor(
                self._skill_registry, context=ctx,
                subagent_registry=self._subagent_registry,
            )
            executor._agent_factory = self
            executor._current_depth = depth + 1

            # 注入 tracker + optimizer（自改进学习循环）
            if self._tracker is not None:
                executor._tracker = self._tracker
            if self._optimizer is not None:
                executor._optimizer = self._optimizer

            # 精确模式检查
            if not explicit_tools or "skills_tool" in self._tool_names:
                tool_loader.register_tool("skills_tool", PydanticSkillsTool(
                    skill_executor=executor,
                    parent_thread_id=agent_name,
                ))

            # 校验 inline 技能的 allowed_tools
            if self._tool_registry:
                for skill in self._skill_registry.list_by_context("inline"):
                    for tn in skill.allowed_tools:
                        if self._tool_registry.find_by_name(tn) is None:
                            logger.warning("技能 '%s' 引用了不存在的工具 '%s'", skill.name, tn)

        # 3. AgentTool（精确模式检查）
        if not explicit_tools or "agent_tool" in self._tool_names:
            tool_loader.register_tool("agent_tool", AgentTool(
                agent_factory=self,
                parent_thread_id=agent_name,
                current_depth=depth + 1,
            ))

        # 4. 统一加载
        all_tools = tool_loader.load_tools()

        # 5. System prompt
        system_prompt = self._system_prompt
        if self._skill_registry:
            section = self._skill_registry.build_skills_prompt_section()
            if section:
                system_prompt += "\n" + section

        # 6. 中间件：外部传入 > 按 features 自动组装
        if self._explicit_middlewares is not None:
            middlewares = self._explicit_middlewares
        else:
            from src.middleware.builder import build_middleware
            skill_names = [s.name for s in self._skill_registry.list_all()] if self._skill_registry else []
            middlewares = build_middleware(
                features=self._features,
                system_prompt=system_prompt,
                skill_names=skill_names,
                tool_names=[t.name for t in all_tools],
                agent_name=agent_name,
                memory_engine=self._memory_engine,
            )

        # 7. 创建 Agent
        agent = create_agent(
            model=self._model,
            tools=all_tools if all_tools else None,
            system_prompt=system_prompt,
            middleware=tuple(middlewares),
            checkpointer=self._checkpointer,
            name=agent_name,
        )

        logger.info("Agent 构建完成: name=%s, tools=%d, middleware=%d, depth=%d",
                     agent_name, len(all_tools), len(middlewares), depth)
        return agent

    def invalidate(self, agent_name: str | None = None) -> None:
        if agent_name is None:
            self._cache.clear()
        else:
            keys = [k for k in self._cache if k.startswith(f"{agent_name}:")]
            for k in keys:
                del self._cache[k]
