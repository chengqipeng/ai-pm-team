"""自动生成对话标题中间件"""

import logging
from typing import Any

from langchain_core.messages import HumanMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class TitleMiddleware(AgentMiddleware):
    def after_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        if state.get("title"):
            return None
        messages = state.get("messages", [])
        first_human = next((m for m in messages if isinstance(m, HumanMessage)), None)
        if not first_human:
            return None
        content = first_human.content
        title = (content[:50].strip() + "...") if isinstance(content, str) and len(content) > 50 else (
            content.strip() if isinstance(content, str) else "新对话")
        return {"title": title}
