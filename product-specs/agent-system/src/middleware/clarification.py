"""澄清中间件 — 拦截 ask_clarification 工具调用，格式化后中断执行

触发场景（由 system prompt 指导 Agent 调用）：
1. missing_info: 缺少关键参数（实体名、筛选条件、目标值）
2. ambiguous_requirement: 用户表述有歧义，可能指向多种操作
3. approach_choice: 多个匹配结果或多种可行方案需用户选择
4. risk_confirmation: 操作涉及删除、批量修改等不可逆影响
"""

import logging
import time

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
        start = time.monotonic()
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

        dur = (time.monotonic() - start) * 1000
        logger.info("Intercepted clarification [%s]: %s (%.1fms)",
                     clarification_type, question[:80], dur)

        # 记录 tracing span
        self._record_span(clarification_type, question, options, dur)

        return ToolMessage(
            content="\n".join(parts),
            tool_call_id=request.tool_call.get("id", ""),
            name="ask_clarification",
            additional_kwargs={"interrupt": True},
        )

    @staticmethod
    def _record_span(ctype: str, question: str, options: list, duration_ms: float) -> None:
        try:
            from src.middleware.tracing import tracing_middleware
            tracing_middleware._add(
                span_type="clarification",
                name=f"clarification:{ctype}",
                duration_ms=duration_ms,
                metadata={
                    "clarification_type": ctype,
                    "question": question[:200],
                    "options": options[:10] if options else [],
                },
            )
        except Exception:
            pass
