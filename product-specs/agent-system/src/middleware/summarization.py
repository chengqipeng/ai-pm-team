"""
SummarizationMiddleware — 上下文压缩

对应 design.md §5.3.4:
当消息历史接近 token 上限时，对较早的消息进行摘要压缩。
使用 before_model 钩子在每次 LLM 调用前检查。
"""
from __future__ import annotations

import logging
from .base import PluginContext
from ..state import GraphState
from ..dtypes import Message, MessageRole

logger = logging.getLogger(__name__)


class SummarizationMiddleware:
    name = "summarization"

    def __init__(self, max_tokens: int = 100_000, trigger_ratio: float = 0.75):
        self._max_tokens = max_tokens
        self._trigger_ratio = trigger_ratio

    async def before_step(self, state, context):
        return state

    async def after_step(self, state, context):
        return state

    async def before_model(self, state: GraphState, context: PluginContext) -> GraphState:
        """每次 LLM 调用前检查消息长度，必要时压缩"""
        if len(state.messages) < 6:
            return state  # 对话太短，不压缩

        # 估算 token 数（粗略: 1 token ≈ 2 字符）
        total_chars = sum(
            len(str(m.content)) for m in state.messages if hasattr(m, "content")
        )
        estimated_tokens = total_chars // 2

        threshold = int(self._max_tokens * self._trigger_ratio)
        if estimated_tokens < threshold:
            return state

        logger.info(f"Summarization: {estimated_tokens} tokens > {threshold} threshold, compressing")

        # 保留最近 4 条消息，压缩更早的
        keep_recent = 4
        if len(state.messages) <= keep_recent:
            return state

        old_messages = state.messages[:-keep_recent]
        recent_messages = state.messages[-keep_recent:]

        # 生成摘要（简单截断，不调 LLM）
        summary_parts = []
        for msg in old_messages[-10:]:  # 最多保留 10 条的摘要
            role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            content = str(msg.content) if isinstance(msg.content, str) else "..."
            summary_parts.append(f"[{role}] {content[:200]}")

        summary_text = (
            "[CONTEXT SUMMARY] 以下是之前对话的摘要:\n"
            + "\n".join(summary_parts)
        )

        # 用摘要替换旧消息
        state.messages = [
            Message(role=MessageRole.SYSTEM, content=summary_text),
            *recent_messages,
        ]

        logger.info(f"Summarization: compressed {len(old_messages)} messages → 1 summary + {keep_recent} recent")
        return state

    async def after_model(self, state, response, context):
        return response

    async def before_tool_call(self, tool_name, input_data, state, context):
        return input_data

    async def after_tool_call(self, tool_name, result, state, context):
        return result
