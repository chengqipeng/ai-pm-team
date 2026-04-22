"""
LoopDetectionMiddleware — 循环检测

对应 design.md §5.3.9:
检测 LLM 是否在重复调用相同的工具（相同参数），防止无限循环。
使用 after_model 钩子在每次 LLM 返回后检查。
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import OrderedDict

from .base import PluginContext
from ..state import GraphState
from ..dtypes import Message, MessageRole

logger = logging.getLogger(__name__)


class LoopDetectionMiddleware:
    name = "loop_detection"

    def __init__(self, warn_threshold: int = 3, hard_limit: int = 5, window_size: int = 20):
        self._warn_threshold = warn_threshold
        self._hard_limit = hard_limit
        self._window_size = window_size
        self._history: list[str] = []  # MD5 hash 滑动窗口

    async def before_step(self, state, context):
        return state

    async def after_step(self, state, context):
        return state

    async def before_model(self, state, context):
        return state

    async def after_model(self, state: GraphState, response: dict, context: PluginContext) -> dict:
        """每次 LLM 返回后检查是否有重复的 tool_calls"""
        content = response.get("content", [])
        tool_calls = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]

        if not tool_calls:
            return response

        # 计算 tool_calls 的 hash
        normalized = json.dumps(
            [{"name": tc.get("name"), "input": tc.get("input")} for tc in tool_calls],
            sort_keys=True, ensure_ascii=False,
        )
        h = hashlib.md5(normalized.encode()).hexdigest()[:12]

        # 统计窗口内重复次数
        self._history.append(h)
        if len(self._history) > self._window_size:
            self._history = self._history[-self._window_size:]

        count = self._history.count(h)

        if count >= self._hard_limit:
            # 硬限制: 剥离 tool_calls，强制模型输出文本
            logger.warning(f"LoopDetection: hard limit ({count}/{self._hard_limit}), stripping tool_calls")
            response["content"] = [b for b in content if b.get("type") != "tool_use"]
            if not response["content"]:
                response["content"] = [{"type": "text", "text": "检测到重复调用，请换一种方法。"}]
            # 注入警告消息
            state.messages.append(Message(
                role=MessageRole.SYSTEM,
                content=f"[LOOP DETECTED] 你已连续 {count} 次调用相同的工具和参数。请停止重复调用，换一种方法或直接回答。",
            ))
        elif count >= self._warn_threshold:
            # 警告: 注入提示但不阻止
            logger.info(f"LoopDetection: warning ({count}/{self._warn_threshold})")
            state.messages.append(Message(
                role=MessageRole.SYSTEM,
                content=f"[WARNING] 你已连续 {count} 次调用相同的工具。请考虑换一种方法。",
            ))

        return response

    async def before_tool_call(self, tool_name, input_data, state, context):
        return input_data

    async def after_tool_call(self, tool_name, result, state, context):
        return result
