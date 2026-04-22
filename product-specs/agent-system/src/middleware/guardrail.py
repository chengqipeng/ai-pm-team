"""
GuardrailMiddleware — 安全护栏（工具白名单）

对应 design.md §5.3.8:
Allowlist 模式拦截不在白名单中的工具调用。
使用 wrap_tool_call 钩子。
"""
from __future__ import annotations

import logging
from .base import PluginContext
from ..state import GraphState
from ..dtypes import ToolResultBlock

logger = logging.getLogger(__name__)


class GuardrailMiddleware:
    """
    安全护栏 — 工具白名单拦截

    allowed_tools=None 或 [] 表示允许所有工具。
    指定后，只有白名单中的工具才能执行。
    """
    name = "guardrail"

    def __init__(self, allowed_tools: list[str] | None = None):
        self._allowed = set(allowed_tools) if allowed_tools else None

    async def before_step(self, state, context):
        return state

    async def after_step(self, state, context):
        return state

    async def before_model(self, state, context):
        return state

    async def after_model(self, state, response, context):
        return response

    async def before_tool_call(self, tool_name, input_data, state, context):
        return input_data

    async def wrap_tool_call(self, tool_name, input_data, state, context):
        """白名单检查 — 不在白名单中的工具调用被拦截"""
        if self._allowed is None:
            return None  # 允许所有

        if tool_name in self._allowed:
            return None  # 在白名单中，继续执行

        # 不在白名单 → 拦截
        logger.warning(f"Guardrail: blocked tool '{tool_name}' (not in allowed list)")
        return ToolResultBlock(
            tool_use_id="",
            content=f"工具 '{tool_name}' 不在允许列表中，操作被拒绝。允许的工具: {', '.join(sorted(self._allowed))}",
            is_error=True,
        )

    async def after_tool_call(self, tool_name, result, state, context):
        return result
