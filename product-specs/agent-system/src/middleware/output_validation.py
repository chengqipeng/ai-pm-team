"""输出验证中间件 — 检查最终输出质量，不满足时注入修正指令"""

import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class OutputValidationMiddleware(AgentMiddleware):
    """最终输出验证"""

    def __init__(self, min_output_length: int = 100, max_retries: int = 1):
        super().__init__()
        self._min_length = min_output_length
        self._max_retries = max_retries
        self._retry_counts: dict[str, int] = {}

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None
        last = messages[-1]
        if not isinstance(last, AIMessage) or getattr(last, "tool_calls", None):
            return None
        content = last.content
        if not isinstance(content, str) or not content.strip():
            return None

        configurable = get_config().get("configurable", {})
        thread_id = configurable.get("thread_id", "default")
        retries = self._retry_counts.get(thread_id, 0)
        if retries >= self._max_retries:
            self._retry_counts.pop(thread_id, None)
            return None

        if len(content.strip()) >= self._min_length:
            self._retry_counts.pop(thread_id, None)
            return None

        self._retry_counts[thread_id] = retries + 1
        logger.warning("Output too short (%d chars), requesting expansion", len(content.strip()))
        return {"messages": [HumanMessage(
            content="[输出验证] 回答过短，请补充关键信息后重新输出完整答案。"
        )]}
