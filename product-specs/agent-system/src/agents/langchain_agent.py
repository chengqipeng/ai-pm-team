"""
LangChain Agent 集成 — create_agent + 原生 AgentMiddleware

Tool 通过 StructuredTool 适配，Middleware 直接继承 AgentMiddleware。
"""
from __future__ import annotations

import json
import logging
from typing import Any
from dataclasses import dataclass, field

from langchain.agents import create_agent
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.tools import BaseTool, StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph

from src.tools.base import Tool, ToolRegistry
from src.skills.base import SkillRegistry, SkillExecutor, SkillsTool
from src.agents.subagent_config import SubagentRegistry

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Tool 适配: DeepAgent Tool → LangChain StructuredTool
# ═══════════════════════════════════════════════════════════

def _make_lc_tool(deep_tool: Tool) -> BaseTool:
    """将 DeepAgent Tool 转为 LangChain StructuredTool"""
    import asyncio

    async def _arun(tool_input: str = "") -> str:
        try:
            params = json.loads(tool_input) if tool_input else {}
        except (json.JSONDecodeError, TypeError):
            params = {"input": tool_input}
        result = await deep_tool.call(params, None)
        return result.content

    def _run(tool_input: str = "") -> str:
        return asyncio.run(_arun(tool_input))

    desc = deep_tool.prompt() or deep_tool.name
    schema = deep_tool.input_schema()
    props = schema.get("properties", {})
    if props:
        desc += "\n\n传入 JSON 参数，如: " + json.dumps(
            {k: f"<{v.get('description', k)}>" for k, v in list(props.items())[:3]},
            ensure_ascii=False,
        )

    return StructuredTool.from_function(
        func=_run, coroutine=_arun,
        name=deep_tool.name, description=desc,
    )


def adapt_tools(registry: ToolRegistry) -> list[BaseTool]:
    return [_make_lc_tool(t) for t in registry.all_tools]


# ═══════════════════════════════════════════════════════════
# Agent 配置 + 工厂
# ═══════════════════════════════════════════════════════════

@dataclass
class LangChainAgentConfig:
    model: str = "deepseek-chat"
    api_key: str = ""
    api_base: str = "https://api.deepseek.com"
    tool_registry: ToolRegistry | None = None
    skill_registry: SkillRegistry | None = None
    subagent_registry: SubagentRegistry | None = None
    agent_factory: Any = None          # AgentFactory 实例，供 fork + AgentTool 使用
    middlewares: list[AgentMiddleware] = field(default_factory=list)
    system_prompt: str = ""
    name: str = "DeepAgent"
    checkpointer: Any = None
    current_depth: int = 0             # 当前嵌套深度
    tool_names: list[str] = field(default_factory=list)   # 精确控制：非空时只注册声明的工具
    skill_names: list[str] = field(default_factory=list)  # 精确控制：非空时只注册声明的技能
    tools_dir: str = ""                # 工具自动发现目录


def create_deep_agent(config: LangChainAgentConfig) -> CompiledStateGraph:
    """用 LangChain create_agent 创建 Agent — 对齐 v2 AgentFactory._build_agent() 流程

    流程：
    1. ToolLoader 统一管理工具（支持精确控制 + 目录自动发现）
    2. 构建 SkillExecutor（注入 agent_factory + current_depth）
    3. 注册 SkillsTool（精确模式下检查声明）
    4. 注册 AgentTool（精确模式下检查声明）
    5. 校验 inline 技能的 allowed_tools
    6. create_agent()
    """
    from src.tools.loader import ToolLoader

    # 1. LLM
    model = ChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=config.api_base,
    )

    # 2. ToolLoader 统一管理（对齐 v2 步骤 1）
    tool_loader = ToolLoader()
    explicit_tools = bool(config.tool_names)
    explicit_skills = bool(config.skill_names)

    # 2a. 适配业务工具 → BaseTool，注册到 ToolLoader
    if config.tool_registry:
        for lc_tool in adapt_tools(config.tool_registry):
            if explicit_tools:
                if lc_tool.name in config.tool_names:
                    tool_loader.register_tool(lc_tool.name, lc_tool)
            else:
                tool_loader.register_tool(lc_tool.name, lc_tool)

    # 2b. 目录自动发现（对齐 v2 的 _discover_tools）
    if config.tools_dir:
        tool_loader.discover_tools(config.tools_dir)

    # 3. 构建 SkillExecutor + 注册 SkillsTool（对齐 v2 步骤 4-5）
    if config.skill_registry and len(config.skill_registry.list_all()) > 0:
        from src.tools.skills_tool import SkillsTool as PydanticSkillsTool
        from src.core.state import PluginContext

        ctx = PluginContext(llm=model, tool_registry=config.tool_registry)
        executor = SkillExecutor(
            config.skill_registry, context=ctx,
            subagent_registry=config.subagent_registry,
        )
        # 注入 AgentFactory + current_depth（对齐 v2 的 subagent_factory=self, current_depth=depth+1）
        if config.agent_factory is not None:
            executor._agent_factory = config.agent_factory
        executor._current_depth = config.current_depth + 1

        # 精确模式下检查是否声明了 skills_tool（对齐 v2 步骤 5）
        if not explicit_tools or "skills_tool" in config.tool_names:
            tool_loader.register_tool("skills_tool", PydanticSkillsTool(
                skill_executor=executor,
                parent_thread_id=config.name,
            ))

        # 校验 inline 技能的 allowed_tools（对齐 v2 步骤 3）
        if config.tool_registry:
            for skill in config.skill_registry.list_by_context("inline"):
                for tool_name in skill.allowed_tools:
                    if config.tool_registry.find_by_name(tool_name) is None:
                        logger.warning("技能 '%s' 引用了不存在的工具 '%s'",
                                       skill.name, tool_name)

    # 4. 注册 AgentTool（对齐 v2 步骤 6，精确模式下检查声明）
    if config.agent_factory is not None:
        if not explicit_tools or "agent_tool" in config.tool_names:
            from src.tools.agent_tool import AgentTool
            tool_loader.register_tool("agent_tool", AgentTool(
                agent_factory=config.agent_factory,
                parent_thread_id=config.name,
                current_depth=config.current_depth + 1,
            ))

    # 5. 统一加载所有工具（对齐 v2 的 tool_loader.load_tools()）
    all_tools = tool_loader.load_tools()

    # 6. System prompt + 技能描述
    system_prompt = config.system_prompt
    if config.skill_registry:
        section = config.skill_registry.build_skills_prompt_section()
        if section:
            system_prompt += "\n" + section

    # 7. 创建 Agent
    agent = create_agent(
        model=model,
        tools=all_tools if all_tools else None,
        system_prompt=system_prompt,
        middleware=tuple(config.middlewares),
        checkpointer=config.checkpointer,
        name=config.name,
    )

    logger.info("Agent created: name=%s, model=%s, tools=%d, middleware=%d, depth=%d",
                config.name, config.model, len(all_tools), len(config.middlewares),
                config.current_depth)
    return agent
