"""输出验证中间件 — 长度校验 + 输出敏感词审查"""

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class OutputValidationMiddleware(AgentMiddleware):
    """最终输出验证 — 输出敏感词审查 + 长度校验

    Args:
        min_output_length: 最小输出长度（低于此值触发扩展指令）
        max_retries: 长度不足时最大重试次数
        review_service: ContentReviewService 实例（None 则跳过输出审查）
    """

    def __init__(
        self,
        min_output_length: int = 100,
        max_retries: int = 1,
        review_service: Any = None,
    ):
        super().__init__()
        self._min_length = min_output_length
        self._max_retries = max_retries
        self._retry_counts: dict[str, int] = {}
        self._review_service = review_service

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

        # ── 输出敏感词审查 ──
        if self._review_service is not None:
            try:
                result = self._review_service.review_output(content)
                if not result.passed:
                    logger.warning("输出审查拦截: keywords=%s", result.blocked_keywords)
                    return {"messages": [AIMessage(content=result.blocked_reason)]}
            except Exception as e:
                logger.error("输出审查异常，降级放行: %s", e)

        # ── 长度校验 ──
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
