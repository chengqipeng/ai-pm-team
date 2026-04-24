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
    """将 DeepAgent Tool 转为 LangChain StructuredTool

    根据 input_schema 动态生成 Pydantic args_schema，
    确保 LangChain agent 以结构化 kwargs 调用工具，避免 KeyError。
    """
    from pydantic import BaseModel, Field, create_model
    from typing import Optional

    schema = deep_tool.input_schema()
    props = schema.get("properties", {})
    required = set(schema.get("required", []))

    # 动态构建 Pydantic model 作为 args_schema
    field_definitions = {}
    for field_name, field_info in props.items():
        field_type_str = field_info.get("type", "string")
        description = field_info.get("description", field_name)

        # 映射 JSON Schema type → Python type
        if field_type_str == "integer":
            py_type = int
        elif field_type_str == "number":
            py_type = float
        elif field_type_str == "boolean":
            py_type = bool
        elif field_type_str == "array":
            py_type = list
        elif field_type_str == "object":
            py_type = dict
        else:
            py_type = str

        if field_name in required:
            field_definitions[field_name] = (py_type, Field(description=description))
        else:
            default = field_info.get("default", None)
            field_definitions[field_name] = (Optional[py_type], Field(default=default, description=description))

    # 创建动态 Pydantic model
    model_name = f"{deep_tool.name.title().replace('_', '')}Input"
    ArgsModel = create_model(model_name, **field_definitions)

    async def _arun(**kwargs) -> str:
        """结构化参数调用 — kwargs 直接映射到 input_data"""
        # 兼容：如果只传了 tool_input 字符串，尝试 JSON 解析
        if len(kwargs) == 1 and "tool_input" in kwargs:
            try:
                params = json.loads(kwargs["tool_input"]) if kwargs["tool_input"] else {}
            except (json.JSONDecodeError, TypeError):
                params = {"input": kwargs["tool_input"]}
        else:
            # 过滤掉值为 None 的可选参数，避免覆盖下游默认值
            params = {k: v for k, v in kwargs.items() if v is not None}
        result = await deep_tool.call(params, None)
        return result.content

    def _run(**kwargs) -> str:
        return asyncio.run(_arun(**kwargs))

    desc = deep_tool.prompt() or deep_tool.name
    # 追加 enum 提示到描述中
    enum_hints = []
    for field_name, field_info in props.items():
        if "enum" in field_info:
            enum_hints.append(f"{field_name}: {'/'.join(field_info['enum'])}")
    if enum_hints:
        desc += "\n参数说明: " + ", ".join(enum_hints)

    return StructuredTool.from_function(
        func=_run, coroutine=_arun,
        name=deep_tool.name, description=desc,
        args_schema=ArgsModel,
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
