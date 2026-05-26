"""Agent 日志中间件 — 循环计数 + 工具调用耗时 + 工具调用次数限制"""

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

# 默认工具调用次数上限（单次对话）
DEFAULT_MAX_TOOL_CALLS = 80


def _truncate(text: str, max_len: int = 500) -> str:
    if len(text) <= max_len:
        return text
    half = max_len // 2
    return text[:half] + f" ...[truncated {len(text) - max_len}]... " + text[-half:]


class ToolCallLimitExceeded(Exception):
    """工具调用次数超限"""
    def __init__(self, thread_id: str, count: int, limit: int):
        self.thread_id = thread_id
        self.count = count
        self.limit = limit
        super().__init__(f"工具调用次数超限: {count}/{limit} (thread={thread_id})")


class AgentLoggingMiddleware(AgentMiddleware):
    """记录模型输出、工具调用和技能执行的日志 + 工具调用次数限制"""

    def __init__(
        self,
        system_prompt: str = "",
        agent_name: str = "",
        max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
    ) -> None:
        self._system_prompt = system_prompt
        self._agent_name = agent_name or "DeepAgent"
        self._loop_counters: dict[str, int] = defaultdict(int)
        self._tool_call_counters: dict[str, int] = defaultdict(int)
        self._agent_started: set[str] = set()
        self._max_tool_calls = max_tool_calls

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        configurable = get_config().get("configurable", {})
        thread_id = configurable.get("thread_id", "unknown")
        if thread_id in self._agent_started:
            return None
        self._agent_started.add(thread_id)
        # 每次新对话重置工具调用计数
        self._tool_call_counters[thread_id] = 0
        logger.warning("[thread=%s] Agent [%s] 启动 (工具调用上限: %d)",
                       thread_id, self._agent_name, self._max_tool_calls)
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
            is_parallel = len(names) > 1
            mode = "并行" if is_parallel else "串行"
            current_count = self._tool_call_counters.get(thread_id, 0)
            logger.warning("[agent=%s] [循环 #%d] 🧠 模型推理 → %s调用 %d 个工具: %s (累计工具调用: %d/%d)",
                           self._agent_name, loop_num, mode, len(names), names,
                           current_count, self._max_tool_calls)
        else:
            content = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)
            logger.warning("[agent=%s] [循环 #%d] [FINAL] 🧠 模型推理 → 生成最终回复: %s",
                           self._agent_name, loop_num, _truncate(content, 200))
        return None

    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        self._check_limit(request)
        return self._log_and_call(request, handler)

    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        self._check_limit(request)
        return await self._alog_and_call(request, handler)

    def _check_limit(self, request: ToolCallRequest) -> None:
        """检查工具调用次数是否超限，超限则返回错误消息而非抛异常"""
        configurable = get_config().get("configurable", {})
        thread_id = configurable.get("thread_id", "unknown")
        self._tool_call_counters[thread_id] += 1
        count = self._tool_call_counters[thread_id]

        if count > self._max_tool_calls:
            logger.error(
                "⚠️ 工具调用次数超限: %d/%d (thread=%s, tool=%s)，强制终止",
                count, self._max_tool_calls, thread_id,
                request.tool_call.get("name", "unknown"),
            )
            raise ToolCallLimitExceeded(thread_id, count, self._max_tool_calls)

    def _log_and_call(self, request, handler):
        name = request.tool_call.get("name", "unknown")
        args = request.tool_call.get("args", {})
        args_str = json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args)
        configurable = get_config().get("configurable", {})
        thread_id = configurable.get("thread_id", "unknown")
        count = self._tool_call_counters.get(thread_id, 0)
        logger.warning("工具调用 [%d/%d]: %s | 入参: %s",
                       count, self._max_tool_calls, name, _truncate(args_str, 800))
        start = time.perf_counter()
        result = handler(request)
        elapsed = time.perf_counter() - start
        result_content = ""
        if hasattr(result, "content"):
            result_content = result.content if isinstance(result.content, str) else str(result.content)
        elif isinstance(result, dict):
            result_content = json.dumps(result, ensure_ascii=False)
        logger.warning("工具完成 [%d/%d]: %s (%.2fs) | 出参: %s",
                       count, self._max_tool_calls, name, elapsed, _truncate(result_content, 800))
        return result

    async def _alog_and_call(self, request, handler):
        name = request.tool_call.get("name", "unknown")
        args = request.tool_call.get("args", {})
        args_str = json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args)
        configurable = get_config().get("configurable", {})
        thread_id = configurable.get("thread_id", "unknown")
        count = self._tool_call_counters.get(thread_id, 0)
        logger.warning("工具调用 [%d/%d]: %s | 入参: %s",
                       count, self._max_tool_calls, name, _truncate(args_str, 800))
        start = time.perf_counter()
        result = await handler(request)
        elapsed = time.perf_counter() - start
        result_content = ""
        if hasattr(result, "content"):
            result_content = result.content if isinstance(result.content, str) else str(result.content)
        elif isinstance(result, dict):
            result_content = json.dumps(result, ensure_ascii=False)
        logger.warning("工具完成 [%d/%d]: %s (%.2fs) | 出参: %s",
                       count, self._max_tool_calls, name, elapsed, _truncate(result_content, 800))
        return result
