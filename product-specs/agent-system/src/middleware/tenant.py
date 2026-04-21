"""TenantMiddleware — 租户隔离，对应产品设计 §3.7.1"""
from __future__ import annotations

from .base import PluginContext
from ..graph.state import GraphState


class TenantMiddleware:
    name = "tenant"

    def __init__(self, tenant_id: str):
        self._tenant_id = tenant_id

    async def before_step(self, state: GraphState, context: PluginContext) -> GraphState:
        return state

    async def after_step(self, state: GraphState, context: PluginContext) -> GraphState:
        return state

    async def before_tool_call(self, tool_name, input_data, state, context):
        # 系统数据类工具：自动注入 tenant_id
        data_tools = ("query_schema", "query_data", "analyze_data", "query_permission", "modify_data")
        if tool_name in data_tools:
            input_data["_tenant_id"] = self._tenant_id

        # 记忆类工具：限定路径前缀
        if tool_name in ("search_memories", "save_memory"):
            input_data["_memory_prefix"] = f"{self._tenant_id}/"

        return input_data

    async def after_tool_call(self, tool_name, result, state, context):
        return result
