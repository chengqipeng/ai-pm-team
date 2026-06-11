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
        # 仅在顶层 Agent (depth=0) 注册 skills_tool，子 Agent 不需要再调用技能
        if self._skill_registry and len(self._skill_registry.list_all()) > 0 and depth == 0:
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

            # 校验技能的 allowed_tools（inline + fork 均校验）
            if self._tool_registry:
                missing_tools_errors: list[str] = []
                for skill in self._skill_registry.list_all():
                    for tn in skill.allowed_tools:
                        if tn in ("skills_tool", "ask_user", "ask_clarification"):
                            continue  # 豁免工具不需要在 registry 中
                        if self._tool_registry.find_by_name(tn) is None:
                            missing_tools_errors.append(
                                f"技能 '{skill.name}' 引用了不存在的工具 '{tn}'"
                            )
                if missing_tools_errors:
                    # 降级处理：禁用引用了缺失工具的技能，而非整体报错
                    # 这样其他正常技能仍可使用
                    error_detail = "; ".join(missing_tools_errors)
                    logger.warning(
                        "Skill allowed_tools 引用了不存在的工具（已跳过相关技能）— %s",
                        error_detail,
                    )
                    # 收集有问题的技能名称并从 registry 中禁用
                    broken_skills = set()
                    for skill in self._skill_registry.list_all():
                        for tn in skill.allowed_tools:
                            if tn in ("skills_tool", "ask_user", "ask_clarification"):
                                continue
                            if self._tool_registry.find_by_name(tn) is None:
                                broken_skills.add(skill.name)
                                break
                    for skill_name in broken_skills:
                        self._skill_registry.unregister(skill_name)
                        logger.info("已禁用技能 '%s'（缺失工具依赖）", skill_name)

        # 3. AgentTool（精确模式检查）
        if not explicit_tools or "agent_tool" in self._tool_names:
            tool_loader.register_tool("agent_tool", AgentTool(
                agent_factory=self,
                parent_thread_id=agent_name,
                current_depth=depth + 1,
            ))

        # 3.5 ask_user 工具（中断确认机制，需要 checkpointer 支持）
        if self._checkpointer is not None:
            if not explicit_tools or "ask_user" in self._tool_names:
                from src.tools.builtins.ask_user_tool import AskUserTool
                tool_loader.register_tool("ask_user", AskUserTool())

        # 4. 统一加载
        all_tools = tool_loader.load_tools()

        # 5. System prompt — 用最终工具列表重建（包含 skills_tool/agent_tool/ask_user 等动态注册的工具）
        # AgentFactory 在步骤 1~3 中动态注册了额外工具，需要将完整工具清单注入提示词
        from src.core.prompt_builder import build_system_prompt as _rebuild_prompt
        system_prompt = _rebuild_prompt(
            agent_name=agent_name,
            skills=self._skill_registry.list_all() if self._skill_registry else None,
            tools=all_tools,
        )

        # 6. 中间件：外部传入 > 按 features 自动组装
        if self._explicit_middlewares is not None:
            middlewares = self._explicit_middlewares
        else:
            from src.middleware.builder import build_middleware
            middlewares = build_middleware(
                features=self._features,
                system_prompt=system_prompt,
                agent_name=agent_name,
                memory_engine=self._memory_engine,
            )

        # 6.5 注入 recall_context 工具的 archive 引用
        # RecallContextTool 需要 ContextWindowMiddleware 的 archive 实例才能工作
        self._inject_archive_into_recall_tool(all_tools, middlewares)

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

    @staticmethod
    def _inject_archive_into_recall_tool(tools: list, middlewares: list) -> None:
        """将 ContextWindowMiddleware 的 archive 注入到 RecallContextTool

        遍历工具列表找到 recall_context，遍历中间件找到 ContextWindowMiddleware，
        将后者的 .archive 属性设置到前者。支持 TracingWrapper 包装的中间件。
        """
        # 找到 recall_context 工具
        recall_tool = None
        for tool in tools:
            if getattr(tool, "name", "") == "recall_context":
                recall_tool = tool
                break

        if recall_tool is None:
            return

        # 从中间件中找到 ContextWindowMiddleware 的 archive
        for mw in middlewares:
            # 支持 TracingWrapper 包装：先尝试 _inner 属性
            inner = getattr(mw, "_inner", mw)
            if hasattr(inner, "archive"):
                recall_tool.archive = inner.archive
                logger.info("[AgentFactory] recall_context 工具已注入 archive 引用")
                return

        logger.warning("[AgentFactory] 未找到 ContextWindowMiddleware，recall_context 工具无法获取 archive")
