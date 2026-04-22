"""记忆中间件 — before_agent 检索注入，after_agent 异步提取更新"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class MemoryDimension(str, Enum):
    USER_PROFILE = "user_profile"
    CUSTOMER_CONTEXT = "customer_context"
    TASK_HISTORY = "task_history"
    DOMAIN_KNOWLEDGE = "domain_knowledge"


@dataclass
class MemoryItem:
    dimension: MemoryDimension
    content: str
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryRetrievalResult:
    items: list[MemoryItem] = field(default_factory=list)
    query_used: str = ""


@dataclass
class MemoryExtractionResult:
    items: list[MemoryItem] = field(default_factory=list)
    source_thread_id: str = ""


class MemoryEngine(ABC):
    """记忆引擎抽象接口"""
    @abstractmethod
    async def rewrite_query(self, messages: list, current_query: str) -> str: ...
    @abstractmethod
    async def retrieve(self, query: str, dimensions: list[MemoryDimension] | None = None,
                       user_id: str | None = None, top_k: int = 5) -> MemoryRetrievalResult: ...
    @abstractmethod
    async def extract_and_update(self, messages: list, thread_id: str,
                                 user_id: str | None = None) -> MemoryExtractionResult: ...


class NoopMemoryEngine(MemoryEngine):
    """空实现占位"""
    async def rewrite_query(self, messages, current_query): return current_query
    async def retrieve(self, query, dimensions=None, user_id=None, top_k=5):
        return MemoryRetrievalResult(query_used=query)
    async def extract_and_update(self, messages, thread_id, user_id=None):
        return MemoryExtractionResult(source_thread_id=thread_id)


class MemoryMiddleware(AgentMiddleware):
    """记忆中间件"""

    def __init__(self, engine: MemoryEngine | None = None,
                 dimensions: list[MemoryDimension] | None = None, enabled: bool = True):
        super().__init__()
        self._engine = engine or NoopMemoryEngine()
        self._dimensions = dimensions or list(MemoryDimension)
        self._enabled = enabled

    @property
    def engine(self) -> MemoryEngine:
        return self._engine

    @engine.setter
    def engine(self, value: MemoryEngine) -> None:
        self._engine = value

    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        if not self._enabled:
            return None
        messages = state.get("messages", [])
        if not messages:
            return None

        current_query = self._get_current_query(messages)
        if not current_query:
            return None

        configurable = get_config().get("configurable", {})
        user_id = configurable.get("user_id")

        try:
            query = (await self._engine.rewrite_query(messages, current_query)
                     if self._has_context(messages) else current_query)
            result = await self._engine.retrieve(query, self._dimensions, user_id)
            text = self._format_memory(result)
            if text:
                return {"messages": [SystemMessage(content=text)]}
        except Exception as e:
            logger.error("Memory retrieval failed: %s", e)
        return None

    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        if not self._enabled:
            return None
        messages = state.get("messages", [])
        if len(messages) < 2:
            return None
        configurable = get_config().get("configurable", {})
        thread_id = configurable.get("thread_id", "unknown")
        user_id = configurable.get("user_id")
        asyncio.create_task(self._async_extract(messages, thread_id, user_id))
        return None

    def _has_context(self, messages): return sum(1 for m in messages if isinstance(m, HumanMessage)) > 1
    def _get_current_query(self, messages):
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                return msg.content if isinstance(msg.content, str) else str(msg.content)
        return ""

    def _format_memory(self, result: MemoryRetrievalResult) -> str | None:
        if not result.items:
            return None
        labels = {d.value: d.value for d in MemoryDimension}
        by_dim: dict[str, list] = {}
        for item in result.items:
            by_dim.setdefault(item.dimension.value, []).append(item)
        sections = [f"【{labels.get(d, d)}】\n" + "\n".join(f"  - {i.content}" for i in items)
                    for d, items in by_dim.items()]
        return "<memory_context>\n" + "\n\n".join(sections) + "\n</memory_context>"

    async def _async_extract(self, messages, thread_id, user_id):
        try:
            result = await self._engine.extract_and_update(messages, thread_id, user_id)
            if result.items:
                logger.info("Extracted %d memory items", len(result.items))
        except Exception as e:
            logger.error("Memory extraction failed: %s", e)
