"""修复悬空 tool call 中间件 — 直接继承 LangChain AgentMiddleware"""

import logging
from typing import Any
from langchain_core.messages import AIMessage, ToolMessage
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class DanglingToolCallMiddleware(AgentMiddleware):
    """修复上一轮悬挂的 tool_calls（补充 error ToolMessage）"""

    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        existing_ids = {
            msg.tool_call_id for msg in messages if isinstance(msg, ToolMessage)
        }

        patches = []
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    tc_id = tc.get("id", "")
                    if tc_id and tc_id not in existing_ids:
                        patches.append(ToolMessage(
                            content="Error: This tool call was not executed (previous session interrupted).",
                            tool_call_id=tc_id,
                            name=tc.get("name", "unknown"),
                            status="error",
                        ))
                        logger.warning("Patched dangling tool call: %s (id=%s)", tc.get("name"), tc_id)
                break  # 只检查最后一条 AIMessage

        return {"messages": patches} if patches else None
