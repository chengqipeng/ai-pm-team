"""子 Agent 并发限制中间件 — 截断超出上限的 agent_tool 调用"""

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class SubagentLimitMiddleware(AgentMiddleware):
    """限制单轮中子 Agent 的并发数量"""

    def __init__(self, max_concurrent: int = 3):
        super().__init__()
        self._max = max_concurrent

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None
        last = messages[-1]
        if not isinstance(last, AIMessage):
            return None
        tool_calls = getattr(last, "tool_calls", None)
        if not tool_calls:
            return None

        agent_calls = [tc for tc in tool_calls if tc.get("name") == "agent_tool"]
        if len(agent_calls) <= self._max:
            return None

        logger.warning("Truncating %d agent_tool calls to %d", len(agent_calls), self._max)
        allowed_ids = {tc.get("id") for tc in agent_calls[:self._max]}
        filtered = [tc for tc in tool_calls
                    if tc.get("name") != "agent_tool" or tc.get("id") in allowed_ids]
        return {"messages": [last.model_copy(update={"tool_calls": filtered})]}
