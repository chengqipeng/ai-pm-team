"""AuditMiddleware — 审计日志，对应产品设计 §3.7.3"""
from __future__ import annotations

import time
import logging

from .base import PluginContext
from ..graph.state import GraphState

logger = logging.getLogger(__name__)


class AuditMiddleware:
    name = "audit"

    async def before_step(self, state: GraphState, context: PluginContext) -> GraphState:
        logger.info(
            f"[audit] node={state.current_node} llm_calls={state.total_llm_calls} "
            f"tool_calls={state.total_tool_calls} step={state.current_step_index}"
        )
        return state

    async def after_step(self, state: GraphState, context: PluginContext) -> GraphState:
        return state

    async def before_tool_call(self, tool_name, input_data, state, context):
        logger.info(f"[audit] tool_start: {tool_name}")
        return input_data

    async def after_tool_call(self, tool_name, result, state, context):
        is_err = getattr(result, "is_error", False)
        logger.info(f"[audit] tool_end: {tool_name} error={is_err}")
        return result
