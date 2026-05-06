"""计划模式任务跟踪中间件"""

import logging
from typing import Any

from langchain_core.messages import SystemMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.config import get_config
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class TodoMiddleware(AgentMiddleware):
    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        configurable = get_config().get("configurable", {})
        if not configurable.get("is_plan_mode", False):
            return None
        todos = state.get("todos")
        if not todos:
            return None
        text = "当前任务计划：\n"
        for i, todo in enumerate(todos, 1):
            status = "✅" if todo.get("done") else "⬜"
            text += f"{status} {i}. {todo.get('task', '')}\n"
        return {"messages": [SystemMessage(content=text)]}
