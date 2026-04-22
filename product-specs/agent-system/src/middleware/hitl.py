"""HITLMiddleware — 人工审批，对应产品设计 §3.3.5 + §六中断体系"""
from __future__ import annotations

import re
from dataclasses import dataclass
from .base import PluginContext
from ..state import GraphState, AgentStatus


@dataclass
class HITLRule:
    """自定义审批规则"""
    tool_name: str
    condition: str = ""          # 简单表达式，如 "action == 'delete'"
    message: str = "操作需要确认"

    def matches(self, tool_name: str, input_data: dict) -> bool:
        if self.tool_name != tool_name:
            return False
        if not self.condition:
            return True
        # 简单条件求值
        try:
            return bool(eval(self.condition, {"__builtins__": {}}, input_data))
        except Exception:
            return False


class HITLMiddleware:
    name = "hitl"

    def __init__(self, rules: list[HITLRule] | None = None):
        self._rules = rules or []

    async def before_step(self, state: GraphState, context: PluginContext) -> GraphState:
        return state

    async def after_step(self, state: GraphState, context: PluginContext) -> GraphState:
        return state

    async def before_tool_call(self, tool_name, input_data, state, context):
        # 如果刚从 approve 恢复，放行一次
        if getattr(state, "_hitl_approved_once", False):
            state._hitl_approved_once = False
            return input_data

        tool = context.tool_registry.find_by_name(tool_name) if context.tool_registry else None

        # 规则 1: 内置 — is_destructive
        if tool and hasattr(tool, "is_destructive") and tool.is_destructive(input_data):
            desc = tool_name
            if hasattr(tool, "description"):
                try:
                    desc = await tool.description(input_data)
                except Exception:
                    pass
            return await self._pause(state, context, f"破坏性操作需要确认: {desc}")

        # 规则 2: 自定义规则
        for rule in self._rules:
            if rule.matches(tool_name, input_data):
                return await self._pause(state, context, rule.message)

        return input_data

    async def after_tool_call(self, tool_name, result, state, context):
        return result

    async def _pause(self, state, context, reason) -> None:
        """触发 CONFIRM 中断"""
        state.status = AgentStatus.PAUSED
        state.pause_reason = reason
        if context.callbacks and context.callbacks.on_approval_request:
            await context.callbacks.on_approval_request(reason, {})
        return None  # 阻止工具执行
