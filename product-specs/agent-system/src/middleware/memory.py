"""
MemoryMiddleware — 长期记忆注入，对应产品设计 §3.5.2 四层召回
会话开始注入画像，每轮自动召回相关记忆。
由 memory-plugin 提供，PluginContext.memory 不为 None 时生效。
"""
from __future__ import annotations

import logging
from .base import PluginContext
from ..graph.state import GraphState

logger = logging.getLogger(__name__)


class MemoryMiddleware:
    name = "memory"

    def __init__(self, memory_plugin):
        self._memory = memory_plugin
        self._profile_injected = False

    async def before_step(self, state: GraphState, context: PluginContext) -> GraphState:
        # Layer 1: 画像注入（仅首次）
        if not self._profile_injected:
            try:
                profile_results = await self._memory.recall(
                    "user profile", categories=["profile"], max_results=1,
                )
                if profile_results:
                    entry = profile_results[0]
                    content = entry.get("content", entry) if isinstance(entry, dict) else str(entry)
                    state.memory_context = f"[用户画像] {content}"
                    logger.info(f"Memory: injected user profile ({len(content)} chars)")
            except Exception as e:
                logger.warning(f"Memory profile injection failed: {e}")
            self._profile_injected = True

        # Layer 2: 自动召回（每轮）
        last_msg = self._get_last_user_message(state)
        if last_msg and not self._is_trivial(last_msg):
            try:
                recalled = await self._memory.recall(last_msg, max_results=3)
                if recalled:
                    parts = []
                    for r in recalled:
                        content = r.get("content", r) if isinstance(r, dict) else str(r)
                        category = r.get("category", "?") if isinstance(r, dict) else "?"
                        parts.append(f"  - [{category}] {content}")
                    state.memory_context += "\n[相关记忆]\n" + "\n".join(parts)
                    logger.info(f"Memory: recalled {len(recalled)} entries")
            except Exception as e:
                logger.warning(f"Memory recall failed: {e}")

        return state

    async def after_step(self, state: GraphState, context: PluginContext) -> GraphState:
        return state

    async def before_tool_call(self, tool_name, input_data, state, context):
        return input_data

    async def after_tool_call(self, tool_name, result, state, context):
        return result

    @staticmethod
    def _get_last_user_message(state: GraphState) -> str:
        for msg in reversed(state.messages):
            role_val = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            if role_val == "user":
                if isinstance(msg.content, str):
                    return msg.content
        return ""

    @staticmethod
    def _is_trivial(msg: str) -> bool:
        """过滤问候/确认等不需要召回记忆的消息"""
        trivial = ["你好", "好的", "谢谢", "ok", "是的", "对", "嗯", "hi", "hello"]
        return msg.strip().lower() in trivial
