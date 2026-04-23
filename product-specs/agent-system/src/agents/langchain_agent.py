"""
LangChain Agent 集成 — 统一通过 AgentFactory 构建

create_deep_agent 是对外的便捷入口，内部委托 AgentFactory._build_agent，
确保只维护一份构建逻辑。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from dataclasses import dataclass, field

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.tools import BaseTool, StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph

from src.tools.base import Tool, ToolRegistry
from src.skills.base import SkillRegistry
from src.agents.subagent_config import SubagentRegistry

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Tool 适配: DeepAgent Tool → LangChain StructuredTool
# ═══════════════════════════════════════════════════════════

def _make_lc_tool(deep_tool: Tool) -> BaseTool:
    """将 DeepAgent Tool 转为 LangChain StructuredTool"""

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
# Agent 配置
# ═══════════════════════════════════════════════════════════

@dataclass
class LangChainAgentConfig:
    model: str = "doubao-1-5-pro-32k-250115"
    api_key: str = ""
    api_base: str = "https://ark.cn-beijing.volces.com/api/v3/"
    tool_registry: ToolRegistry | None = None
    skill_registry: SkillRegistry | None = None
    subagent_registry: SubagentRegistry | None = None
    middlewares: list[AgentMiddleware] = field(default_factory=list)
    system_prompt: str = ""
    name: str = "DeepAgent"
    checkpointer: Any = None
    current_depth: int = 0
    tool_names: list[str] = field(default_factory=list)
    skill_names: list[str] = field(default_factory=list)
    tools_dir: str = ""


# ═══════════════════════════════════════════════════════════
# Agent 创建 — 委托 AgentFactory（唯一构建逻辑）
# ═══════════════════════════════════════════════════════════

def create_deep_agent(config: LangChainAgentConfig) -> CompiledStateGraph:
    """创建 Agent — 内部委托 AgentFactory，确保只维护一份构建逻辑"""
    from src.agents.agent_factory import AgentFactory

    model = ChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=config.api_base,
    )

    factory = AgentFactory(
        default_model=model,
        tool_registry=config.tool_registry,
        skill_registry=config.skill_registry,
        default_system_prompt=config.system_prompt,
        default_middlewares=config.middlewares if config.middlewares else None,
        max_depth=3,
        checkpointer=config.checkpointer,
        subagent_registry=config.subagent_registry,
        tool_names=config.tool_names,
        tools_dir=config.tools_dir,
    )

    # 同步包装异步 build
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run,
                factory.build(config.name, config.current_depth)).result()
    return asyncio.run(factory.build(config.name, config.current_depth))
