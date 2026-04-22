"""安全护栏中间件 — 直接继承 LangChain AgentMiddleware"""

import logging
from langchain_core.messages import ToolMessage
from langchain.agents.middleware.types import AgentMiddleware
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)


class GuardrailMiddleware(AgentMiddleware):
    """工具白名单拦截"""

    def __init__(self, allowed_tools: list[str] | None = None):
        super().__init__()
        self._allowed = set(allowed_tools) if allowed_tools else None

    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        tool_name = request.tool_call.get("name", "")
        if self._allowed and tool_name not in self._allowed:
            logger.warning("Guardrail blocked: %s", tool_name)
            return ToolMessage(
                content=f"Error: Tool '{tool_name}' is not allowed by security policy.",
                tool_call_id=request.tool_call.get("id", ""),
                name=tool_name,
                status="error",
            )
        return handler(request)

    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        tool_name = request.tool_call.get("name", "")
        if self._allowed and tool_name not in self._allowed:
            logger.warning("Guardrail blocked: %s", tool_name)
            return ToolMessage(
                content=f"Error: Tool '{tool_name}' is not allowed by security policy.",
                tool_call_id=request.tool_call.get("id", ""),
                name=tool_name,
                status="error",
            )
        return await handler(request)
