"""输入转换中间件 — 预处理钩子（多模态转换等）"""

import logging
from abc import ABC, abstractmethod
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class InputTransformer(ABC):
    @abstractmethod
    def transform(self, messages: list, metadata: dict[str, Any]) -> list: ...


class MultimodalTransformer(InputTransformer):
    """多模态输入转换器（预留骨架）"""
    def transform(self, messages, metadata): return messages


class InputTransformMiddleware(AgentMiddleware):
    """输入转换中间件"""

    def __init__(self, transformers: list[InputTransformer] | None = None):
        super().__init__()
        self._transformers: list[InputTransformer] = transformers or []

    def register(self, transformer: InputTransformer) -> None:
        self._transformers.append(transformer)

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        if not self._transformers:
            return None
        messages = state.get("messages", [])
        configurable = get_config().get("configurable", {})
        metadata = configurable.get("input_metadata", {})
        transformed = messages
        for t in self._transformers:
            try:
                transformed = t.transform(transformed, metadata)
            except Exception as e:
                logger.error("InputTransformer %s failed: %s", type(t).__name__, e)
        return {"messages": transformed} if transformed is not messages else None
