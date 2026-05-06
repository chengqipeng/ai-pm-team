"""Agent 日志中间件 — 循环计数 + 工具调用耗时 + 启动信息"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

logger = logging.getLogger(__name__)


def _truncate(text: str, max_len: int = 500) -> str:
    if len(text) <= max_len:
        return text
    half = max_len // 2
    return text[:half] + f" ...[truncated {len(text) - max_len}]... " + text[-half:]


class AgentLoggingMiddleware(AgentMiddleware):
    """记录模型输出、工具调用和技能执行的日志"""

    def __init__(
        self,
        system_prompt: str = "",
        agent_name: str = "",
    ) -> None:
        self._system_prompt = system_prompt
        self._agent_name = agent_name or "DeepAgent"
        self._loop_counters: dict[str, int] = defaultdict(int)
        self._agent_started: set[str] = set()

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        configurable = get_config().get("configurable", {})
        thread_id = configurable.get("thread_id", "unknown")
        if thread_id in self._agent_started:
            return None
        self._agent_started.add(thread_id)
        logger.warning("[thread=%s] Agent [%s] 启动", thread_id, self._agent_name)
        return None

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None
        last_msg = messages[-1]
        if not isinstance(last_msg, AIMessage):
            return None

        configurable = get_config().get("configurable", {})
        thread_id = configurable.get("thread_id", "unknown")
        self._loop_counters[thread_id] += 1
        loop_num = self._loop_counters[thread_id]

        tool_calls = getattr(last_msg, "tool_calls", None)
        if tool_calls:
            names = [tc.get("name", "?") for tc in tool_calls]
            logger.warning("[agent=%s] [循环 #%d] 调用工具: %s",
                           self._agent_name, loop_num, names)
        else:
            content = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)
            logger.warning("[agent=%s] [循环 #%d] [FINAL] %s",
                           self._agent_name, loop_num, _truncate(content, 200))
        return None

    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        return self._log_and_call(request, handler, is_async=False)

    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        return await self._alog_and_call(request, handler)

    def _log_and_call(self, request, handler):
        name = request.tool_call.get("name", "unknown")
        start = time.perf_counter()
        result = handler(request)
        elapsed = time.perf_counter() - start
        logger.warning("工具完成: %s (%.2fs)", name, elapsed)
        return result

    async def _alog_and_call(self, request, handler):
        name = request.tool_call.get("name", "unknown")
        start = time.perf_counter()
        result = await handler(request)
        elapsed = time.perf_counter() - start
        logger.warning("工具完成: %s (%.2fs)", name, elapsed)
        return result
