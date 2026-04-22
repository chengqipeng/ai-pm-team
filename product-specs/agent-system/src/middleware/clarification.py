"""澄清中间件 — 拦截 ask_clarification 工具调用，格式化后中断执行"""

import logging

from langchain_core.messages import ToolMessage
from langchain.agents.middleware.types import AgentMiddleware
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)


class ClarificationMiddleware(AgentMiddleware):
    """拦截 ask_clarification 工具调用，格式化后中断执行"""

    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        if request.tool_call.get("name") != "ask_clarification":
            return handler(request)
        return self._format(request)

    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        if request.tool_call.get("name") != "ask_clarification":
            return await handler(request)
        return self._format(request)

    def _format(self, request: ToolCallRequest) -> ToolMessage:
        args = request.tool_call.get("args", {})
        question = args.get("question", "")
        clarification_type = args.get("clarification_type", "missing_info")
        context = args.get("context", "")
        options = args.get("options", [])

        icons = {"missing_info": "❓", "ambiguous_requirement": "🤔",
                 "approach_choice": "🔀", "risk_confirmation": "⚠️"}
        icon = icons.get(clarification_type, "❓")
        parts = [f"{icon} {context}\n{question}" if context else f"{icon} {question}"]
        if options:
            parts += [""] + [f"  {i}. {o}" for i, o in enumerate(options, 1)]

        logger.info("Intercepted clarification request")
        return ToolMessage(
            content="\n".join(parts),
            tool_call_id=request.tool_call.get("id", ""),
            name="ask_clarification",
            additional_kwargs={"interrupt": True},
        )
