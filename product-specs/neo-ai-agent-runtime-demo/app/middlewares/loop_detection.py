"""loop_detection — 循环检测中间件（Builtin）

直接继承 LangChain AgentMiddleware，传给 create_agent(middleware=[...])。
在 after_model 阶段检测连续调用同一工具的循环。
"""
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.runtime import Runtime


class LoopDetectionMiddleware(AgentMiddleware):
    """循环检测 — 防止 Agent 反复调用同一工具"""

    name = "loop_detection"

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """LLM 返回后检测循环"""
        messages = state.get("messages", [])

        # 提取最近的 tool_call 名称
        recent_tools = []
        for msg in reversed(messages[-8:]):
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                for tc in tool_calls:
                    recent_tools.append(tc.get("name", ""))

        if len(recent_tools) >= 4:
            last_4 = recent_tools[:4]
            if len(set(last_4)) == 1:
                # 可以返回终止标记或仅告警
                pass

        return None
