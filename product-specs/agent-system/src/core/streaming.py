"""SSE 流式响应 — 将 LangGraph 流式输出转换为 SSE 事件流"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from langgraph.graph.state import CompiledStateGraph

logger = logging.getLogger(__name__)

VALID_EVENT_TYPES = frozenset({"token", "tool_call", "tool_result", "subagent_start", "subagent_result", "done"})


@dataclass
class SSEEvent:
    event: str
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.event not in VALID_EVENT_TYPES:
            raise ValueError(f"无效事件类型: {self.event!r}")

    def to_sse_string(self) -> str:
        return f"event: {self.event}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"

    def to_dict(self) -> dict[str, Any]:
        return {"event": self.event, "data": self.data}


async def stream_agent_response(
    agent: CompiledStateGraph,
    input_data: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> AsyncGenerator[SSEEvent, None]:
    """将 LangGraph astream_events 转换为 SSE 事件流"""
    config = config or {}
    try:
        async for event in agent.astream_events(input_data, config=config, version="v2"):
            kind = event.get("event", "")
            # 过滤子 Agent 的 LLM stream
            if kind == "on_chat_model_stream" and len(event.get("parent_ids", [])) > 2:
                continue
            sse = _map_event(event)
            if sse:
                yield sse
    except Exception as exc:
        logger.exception("Agent streaming error")
        yield SSEEvent(event="done", data={"error": str(exc), "finished": True})
        return

    yield SSEEvent(event="done", data={"finished": True})


def _map_event(event: dict[str, Any]) -> SSEEvent | None:
    kind = event.get("event", "")
    data = event.get("data", {})

    if kind == "on_chat_model_stream":
        chunk = data.get("chunk")
        if chunk:
            content = getattr(chunk, "content", "")
            if isinstance(content, list):
                content = "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
            if content:
                return SSEEvent(event="token", data={"content": content})

    elif kind == "on_tool_start":
        return SSEEvent(event="tool_call", data={"tool_name": event.get("name", ""), "input": data.get("input", {})})

    elif kind == "on_tool_end":
        return None  # 不推送工具结果

    return None
