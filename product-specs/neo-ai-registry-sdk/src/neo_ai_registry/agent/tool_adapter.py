"""Tool Adapter — 将 ToolDefinition 转换为 LangChain BaseTool

参考 neo-apps-ai-agent-service 中 Tool 的标准模式：
- 继承 BaseTool
- args_schema 使用 Pydantic model（支持 InjectedState）
- _arun 中通过 get_config().configurable 获取请求上下文
- 返回字符串（JSON 序列化）

Builtin Tool: _arun 直接调 execute()
Remote Tool: _arun 通过 FeignClient 远程调用

Usage:
    from neo_ai_registry.agent.tool_adapter import create_base_tool, create_base_tools

    base_tool = definition.to_base_tool(transport)
    tools = ToolDefinition.to_base_tools(definitions, transport)
    create_agent(model=model, tools=tools)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from neo_ai_registry.models import ToolDefinition
from neo_ai_registry.state import ToolState

logger = logging.getLogger(__name__)


def create_base_tool(definition: ToolDefinition, transport: Any) -> Any:
    """将 ToolDefinition 转换为 LangChain BaseTool 实例

    动态生成：
    - args_schema: 从 input_schema JSON Schema 生成 Pydantic model（含 InjectedState）
    - _arun: builtin 直接调 execute()，remote 走 FeignClient

    Args:
        definition: ToolDefinition 实例。
        transport: Transport 实例（remote 调用用）。

    Returns:
        BaseTool 实例。
    """
    from langchain_core.tools import BaseTool
    from langgraph.prebuilt import InjectedState
    from pydantic import BaseModel, Field, create_model
    from typing import Annotated

    api_key = definition.api_key
    input_schema = definition.input_schema or {}
    props = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))

    # 1. 从 input_schema 动态生成 args_schema
    field_definitions: dict[str, Any] = {}
    for field_name, field_info in props.items():
        field_type_str = field_info.get("type", "string")
        description = field_info.get("description", field_name)

        # JSON Schema type → Python type
        type_map = {
            "string": str, "integer": int, "number": float,
            "boolean": bool, "array": list, "object": dict,
        }
        py_type = type_map.get(field_type_str, str)

        if field_name in required:
            field_definitions[field_name] = (py_type, Field(description=description))
        else:
            default = field_info.get("default", None)
            field_definitions[field_name] = (Optional[py_type], Field(default=default, description=description))

    # 加入 InjectedState（LangGraph 自动注入图 state）
    field_definitions["state"] = (Annotated[dict, InjectedState], Field(default=None))

    model_name = f"{api_key.title().replace('_', '')}Input"
    ArgsModel = create_model(model_name, **field_definitions)

    # 2. 构建 _arun 方法
    is_builtin = definition.is_builtin()

    async def _arun(**kwargs) -> str:
        """动态生成的 _arun — builtin 本地执行 / remote FeignClient 调用"""
        from langgraph.config import get_config

        # 分离 state、config 和业务参数
        injected_state = kwargs.pop("state", None) or {}
        kwargs.pop("config", None)  # LangChain 传入的 config，已通过 get_config() 获取
        input_data = {k: v for k, v in kwargs.items() if v is not None}

        # 获取 configurable（过滤 LangGraph 内部字段 + 不可序列化对象）
        raw_configurable = get_config().get("configurable", {})
        configurable = {}
        for k, v in raw_configurable.items():
            if k.startswith("__"):
                continue
            try:
                import json as _json
                _json.dumps(v)
                configurable[k] = v
            except (TypeError, ValueError):
                pass

        if is_builtin:
            # Builtin: 直接调用 execute
            context = dict(injected_state)
            if configurable:
                context["_configurable"] = configurable
            result = await definition.execute(input_data, context)
        else:
            # Remote: FeignClient 调用
            from neo_ai_registry.feign.client import ToolFeignClient

            tool_state = ToolState.from_agent_state(injected_state)
            client = ToolFeignClient(app_name=definition.service, transport=transport)
            response = await client.async_execute_tool(api_key, input_data, state=tool_state, configurable=configurable)

            # write_back state_patch
            if isinstance(injected_state, dict):
                tool_state.write_back(injected_state)

            result = response.get("result", response)

        # BaseTool 要求返回字符串
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    def _run(**kwargs) -> str:
        """同步兜底"""
        import asyncio
        kwargs.pop("config", None)
        return asyncio.run(_arun(**kwargs))

    # 3. 构建 description（追加 enum 提示）
    desc = definition.description or definition.name or api_key
    enum_hints = []
    for field_name, field_info in props.items():
        if "enum" in field_info:
            enum_hints.append(f"{field_name}: {'/'.join(field_info['enum'])}")
    if enum_hints:
        desc += "\n参数说明: " + ", ".join(enum_hints)

    # 4. 创建 BaseTool
    from langchain_core.tools import StructuredTool

    tool = StructuredTool.from_function(
        func=_run,
        coroutine=_arun,
        name=api_key,
        description=desc,
        args_schema=ArgsModel,
    )

    return tool


def create_base_tools(definitions: list[ToolDefinition], transport: Any) -> list:
    """批量将 ToolDefinition 转换为 BaseTool

    Args:
        definitions: ToolDefinition 列表。
        transport: Transport 实例。

    Returns:
        BaseTool 实例列表。

    Raises:
        Exception: 任何转换失败直接抛出。
    """
    return [create_base_tool(d, transport) for d in definitions]
