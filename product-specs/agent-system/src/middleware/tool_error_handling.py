"""工具异常处理中间件 — 直接继承 LangChain AgentMiddleware"""

import logging
from langchain_core.messages import ToolMessage
from langchain.agents.middleware.types import AgentMiddleware
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)


class ToolErrorHandlingMiddleware(AgentMiddleware):
    """工具异常 → 错误消息，防止整个 Agent run 崩溃"""

    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        try:
            return handler(request)
        except Exception as exc:
            return self._error_message(request, exc)

    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        try:
            return await handler(request)
        except Exception as exc:
            return self._error_message(request, exc)

    @staticmethod
    def _error_message(request: ToolCallRequest, exc: Exception) -> ToolMessage:
        tool_name = request.tool_call.get("name", "unknown")
        detail = str(exc).strip() or exc.__class__.__name__
        if len(detail) > 500:
            detail = detail[:497] + "..."
        logger.exception("Tool '%s' failed: %s", tool_name, detail)
        return ToolMessage(
            content=f"Error: Tool '{tool_name}' failed with {exc.__class__.__name__}: {detail}. "
                    "Continue with available context, or choose an alternative tool.",
            tool_call_id=request.tool_call.get("id", ""),
            name=tool_name,
            status="error",
        )
