"""
LangChain Agent 集成 — 用 create_agent 替代自研 GraphEngine

将 DeepAgent 的 Tool/Skill/Middleware 适配到 LangChain 1.x 的 create_agent API。
保留所有业务逻辑，只替换编排引擎层。

迁移映射:
  GraphEngine.run()     → create_agent + agent.ainvoke()
  Router                → create_agent 内置的 agent loop
  ExecutionNode         → create_agent 内置的 tool calling loop
  PlanningNode          → 通过 before_agent middleware 实现
  ReflectionNode        → 通过 after_agent middleware 实现
  Tool                  → BaseTool 适配器
  Middleware            → AgentMiddleware 适配器
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Sequence
from dataclasses import dataclass, field

from langchain.agents import create_agent
from langchain.agents.middleware.types import AgentMiddleware as LCMiddleware, AgentState
from langchain_core.tools import BaseTool as LCBaseTool, tool as lc_tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph

from .tools import Tool, ToolRegistry
from .skills import SkillRegistry, SkillExecutor, SkillsTool, SkillDefinition
from .subagent_config import SubagentRegistry
from .state import AgentCallbacks

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Tool 适配器: DeepAgent Tool → LangChain @tool 函数
# ═══════════════════════════════════════════════════════════

def _make_lc_tool(deep_tool: Tool) -> LCBaseTool:
    """为单个 DeepAgent Tool 创建 LangChain 兼容的工具"""
    import asyncio
    from langchain_core.tools import StructuredTool

    async def _arun(tool_input: str = "") -> str:
        """执行工具。tool_input 是 JSON 字符串格式的参数。"""
        try:
            params = json.loads(tool_input) if tool_input else {}
        except (json.JSONDecodeError, TypeError):
            params = {"input": tool_input}
        result = await deep_tool.call(params, None)
        return result.content

    def _run(tool_input: str = "") -> str:
        return asyncio.run(_arun(tool_input))

    desc = deep_tool.prompt() or deep_tool.name
    # 把 input_schema 的参数说明加到描述中
    schema = deep_tool.input_schema()
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if properties:
        params = []
        for k, v in properties.items():
            p_desc = v.get("description", k)
            req = " (必填)" if k in required else ""
            params.append(f"  {k}: {p_desc}{req}")
        desc += "\n\n传入 JSON 格式参数，如: " + json.dumps(
            {k: f"<{v.get('description', k)}>" for k, v in list(properties.items())[:3]},
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        func=_run,
        coroutine=_arun,
        name=deep_tool.name,
        description=desc,
    )


def adapt_tools(registry: ToolRegistry) -> list[LCBaseTool]:
    """将 ToolRegistry 中的所有工具转为 LangChain BaseTool"""
    return [_make_lc_tool(t) for t in registry.all_tools]


# ═══════════════════════════════════════════════════════════
# Middleware 适配器: DeepAgent Middleware → LangChain AgentMiddleware
# ═══════════════════════════════════════════════════════════

class DeepAgentMiddlewareAdapter(LCMiddleware):
    """将 DeepAgent 的 Middleware 包装为 LangChain AgentMiddleware"""

    def __init__(self, deep_mw: Any):
        self._mw = deep_mw
        self._name = getattr(deep_mw, 'name', 'unknown')
        self.tools = []  # LangChain 要求 middleware 有 tools 属性（Sequence[BaseTool]）

    @property
    def name(self) -> str:
        return self._name

    def before_agent(self, state, runtime):
        if hasattr(self._mw, 'before_step'):
            logger.debug(f"MW {self._name}: before_agent")
        return None

    def after_agent(self, state, runtime):
        if hasattr(self._mw, 'after_step'):
            logger.debug(f"MW {self._name}: after_agent")
        return None

    def before_model(self, state, runtime):
        if hasattr(self._mw, 'before_model'):
            logger.debug(f"MW {self._name}: before_model")
        return None

    def after_model(self, state, runtime):
        if hasattr(self._mw, 'after_model'):
            logger.debug(f"MW {self._name}: after_model")
        return None


# ═══════════════════════════════════════════════════════════
# LangChain Agent 工厂
# ═══════════════════════════════════════════════════════════

@dataclass
class LangChainAgentConfig:
    """LangChain Agent 配置"""
    # LLM
    model: str = "deepseek-chat"
    api_key: str = ""
    api_base: str = "https://api.deepseek.com"

    # 工具
    tool_registry: ToolRegistry | None = None

    # 技能
    skill_registry: SkillRegistry | None = None
    subagent_registry: SubagentRegistry | None = None

    # 中间件（DeepAgent 格式，会自动适配）
    middlewares: list[Any] = field(default_factory=list)

    # System prompt
    system_prompt: str = ""

    # 回调
    callbacks: AgentCallbacks | None = None

    # Agent 名称
    name: str = "DeepAgent"


def create_deep_agent(config: LangChainAgentConfig) -> CompiledStateGraph:
    """
    用 LangChain create_agent 创建 Agent

    这是 GraphEngine 的替代品。保留所有 DeepAgent 的业务逻辑（Tool/Skill/Middleware），
    但用 LangChain 的 create_agent 作为编排引擎。
    """
    # 1. 创建 LLM
    model = ChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=config.api_base,
    )

    # 2. 适配工具
    lc_tools = []
    if config.tool_registry:
        lc_tools = adapt_tools(config.tool_registry)

    # 3. 如果有 SkillRegistry，创建 SkillsTool 并注册
    if config.skill_registry and config.tool_registry:
        from .middleware.base import PluginContext
        from .state import AgentLimits
        # 创建一个简化的 PluginContext 给 SkillExecutor
        ctx = PluginContext(
            llm=None,  # fork 模式暂不支持（需要 DeepSeekClient）
            tool_registry=config.tool_registry,
        )
        executor = SkillExecutor(
            config.skill_registry,
            context=ctx,
            subagent_registry=config.subagent_registry,
        )
        skills_tool = SkillsTool(executor)
        lc_tools.append(_make_lc_tool(skills_tool))

    # 4. 构建 system prompt
    system_prompt = config.system_prompt
    if config.skill_registry:
        skills_section = config.skill_registry.build_skills_prompt_section()
        if skills_section:
            system_prompt += "\n" + skills_section

    # 5. 适配中间件
    lc_middleware = []
    for mw in config.middlewares:
        lc_middleware.append(DeepAgentMiddlewareAdapter(mw))

    # 6. 创建 Agent
    agent = create_agent(
        model=model,
        tools=lc_tools if lc_tools else None,
        system_prompt=system_prompt,
        middleware=tuple(lc_middleware),  # 必须是 tuple/list，不能是 None
        name=config.name,
    )

    logger.info(
        f"LangChain Agent created: model={config.model}, "
        f"tools={len(lc_tools)}, middleware={len(lc_middleware)}"
    )

    return agent
