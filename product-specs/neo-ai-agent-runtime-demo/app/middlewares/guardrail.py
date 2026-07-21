"""guardrail — 安全护栏中间件（Builtin）

直接继承 LangChain AgentMiddleware，传给 create_agent(middleware=[...])。
在 wrap_tool_call 阶段拦截破坏性操作。
"""
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command


class GuardrailMiddleware(AgentMiddleware):
    """安全护栏 — 拦截未授权的破坏性操作"""

    name = "guardrail"

    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        """包装工具调用 — 破坏性操作拦截"""
        tool_name = request.tool_call.get("name", "")
        args = request.tool_call.get("args", {})

        if tool_name == "modify_data" and args.get("action") == "delete":
            return ToolMessage(
                content=f"⚠️ 破坏性操作 {tool_name}.delete 需要用户确认，已拦截。",
                tool_call_id=request.tool_call.get("id", ""),
            )

        return await handler(request)
