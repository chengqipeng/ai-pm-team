"""记忆提示词构建 — 将短期记忆和长期检索结果注入系统提示词"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MemoryChunk:
    """记忆片段"""
    id: str = ""
    content: str = ""
    user_id: str = ""
    thread_id: str = ""
    embedding: list[float] = field(default_factory=list)
    created_at: datetime | None = None
    metadata: dict = field(default_factory=dict)


def build_memory_prompt(
    short_term: str = "",
    long_term_results: list[MemoryChunk] | None = None,
) -> str:
    """将短期记忆和长期语义检索结果组合为系统提示词片段"""
    sections: list[str] = []

    if short_term and short_term.strip():
        sections.append(f"<short_term_memory>\n{short_term.strip()}\n</short_term_memory>")

    if long_term_results:
        chunks_text = "\n---\n".join(
            chunk.content.strip() for chunk in long_term_results if chunk.content.strip()
        )
        if chunks_text:
            sections.append(f"<long_term_memory>\n{chunks_text}\n</long_term_memory>")

    if not sections:
        return ""

    return "以下是与当前对话相关的记忆上下文，请在回答时参考：\n\n" + "\n\n".join(sections)
