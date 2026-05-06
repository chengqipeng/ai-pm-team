"""记忆更新器 — 使用 LLM 从对话中提取关键信息并更新记忆"""
from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class LLMInvoker(Protocol):
    """LLM 调用协议"""
    async def ainvoke(self, input: Any) -> Any: ...


class MemoryUpdater:
    """使用 LLM 从对话中提取关键信息并更新记忆"""

    _EXTRACTION_PROMPT = (
        "你是一个记忆提取助手。请从以下对话中提取关键信息（用户偏好、重要事实、"
        "待办事项等），并将其合并到现有记忆中。\n\n"
        "现有记忆:\n{existing_memory}\n\n"
        "对话内容:\n{conversation}\n\n"
        "请输出更新后的完整记忆文本（纯文本，不要 Markdown 标题）:"
    )

    def __init__(self, llm: LLMInvoker | None = None) -> None:
        self._llm = llm

    async def extract_and_update(self, messages: list[Any], existing_memory: str) -> str:
        """使用 LLM 从对话中提取关键信息并更新记忆"""
        if not messages:
            return existing_memory
        if self._llm is None:
            return existing_memory

        conversation = self._format_messages(messages)
        prompt = self._EXTRACTION_PROMPT.format(
            existing_memory=existing_memory or "(空)",
            conversation=conversation,
        )
        try:
            result = await self._llm.ainvoke(prompt)
            content = getattr(result, "content", None) or str(result)
            return content.strip()
        except Exception:
            logger.exception("LLM 记忆提取失败，保留现有记忆")
            return existing_memory

    @staticmethod
    def _format_messages(messages: list[Any]) -> str:
        lines: list[str] = []
        for msg in messages:
            role = getattr(msg, "type", None) or getattr(msg, "role", "unknown")
            content = getattr(msg, "content", None) or str(msg)
            if isinstance(content, str):
                lines.append(f"[{role}]: {content[:500]}")
        return "\n".join(lines)
