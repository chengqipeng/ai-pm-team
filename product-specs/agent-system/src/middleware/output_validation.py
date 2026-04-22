"""
OutputValidationMiddleware — 输出验证

对应 design.md §5.3.12:
在 Agent 准备输出最终答案时，检查结果是否满足质量要求。
使用 after_model 钩子在每次 LLM 返回后检查。
"""
from __future__ import annotations

import logging
from .base import PluginContext
from ..state import GraphState
from ..dtypes import Message, MessageRole

logger = logging.getLogger(__name__)


class OutputValidationMiddleware:
    name = "output_validation"

    def __init__(self, min_output_length: int = 20, max_retries: int = 1):
        self._min_length = min_output_length
        self._max_retries = max_retries
        self._retry_count: int = 0

    async def before_step(self, state, context):
        return state

    async def after_step(self, state, context):
        return state

    async def before_model(self, state, context):
        return state

    async def after_model(self, state: GraphState, response: dict, context: PluginContext) -> dict:
        """检查最终输出质量"""
        content = response.get("content", [])
        tool_calls = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]

        # 只检查最终输出（无 tool_calls 的纯文本响应）
        if tool_calls:
            return response

        text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        text = "\n".join(text_parts)

        if not text.strip():
            return response

        issues = []

        # 检查 1: 输出过短
        if len(text) < self._min_length:
            issues.append(f"输出过短（{len(text)}字符 < {self._min_length}）")

        if issues and self._retry_count < self._max_retries:
            self._retry_count += 1
            logger.info(f"OutputValidation: issues={issues}, retry {self._retry_count}/{self._max_retries}")
            # 注入修正指令
            state.messages.append(Message(
                role=MessageRole.SYSTEM,
                content=f"[OUTPUT VALIDATION] 输出质量不足: {'; '.join(issues)}。请补充更多细节。",
            ))
            # 清空当前响应，让 LLM 重新生成
            response["content"] = []
        elif not issues:
            self._retry_count = 0  # 重置

        return response

    async def before_tool_call(self, tool_name, input_data, state, context):
        return input_data

    async def after_tool_call(self, tool_name, result, state, context):
        return result
