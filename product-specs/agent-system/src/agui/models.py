"""AG-UI 事件模型 — 标准 AG-UI 协议事件类型

参考: https://docs.ag-ui.com/concepts/events
"""
from __future__ import annotations

from enum import Enum
from typing import Any
from dataclasses import dataclass, field


class AGUIEventType(str, Enum):
    """AG-UI 标准事件类型"""
    RUN_STARTED = "RUN_STARTED"
    RUN_FINISHED = "RUN_FINISHED"
    RUN_ERROR = "RUN_ERROR"
    TEXT_MESSAGE_START = "TEXT_MESSAGE_START"
    TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
    TEXT_MESSAGE_END = "TEXT_MESSAGE_END"
    TOOL_CALL_START = "TOOL_CALL_START"
    TOOL_CALL_ARGS = "TOOL_CALL_ARGS"
    TOOL_CALL_END = "TOOL_CALL_END"
    TOOL_CALL_RESULT = "TOOL_CALL_RESULT"
    STEP_STARTED = "STEP_STARTED"
    STEP_FINISHED = "STEP_FINISHED"
    REASONING_STARTED = "REASONING_STARTED"
    REASONING_CONTENT = "REASONING_CONTENT"
    REASONING_FINISHED = "REASONING_FINISHED"
    MESSAGES_SNAPSHOT = "MESSAGES_SNAPSHOT"
    CUSTOM = "CUSTOM"


@dataclass
class AGUIEvent:
    """AG-UI 事件基类"""
    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> str:
        import json
        return f"event: {self.type}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, **self.data}


# ── 便捷构造函数 ──

def run_started(run_id: str, thread_id: str) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.RUN_STARTED, data={"run_id": run_id, "thread_id": thread_id})

def run_finished(run_id: str, thread_id: str) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.RUN_FINISHED, data={"run_id": run_id, "thread_id": thread_id})

def run_error(error_type: str, error_message: str) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.RUN_ERROR, data={"error_type": error_type, "error_message": error_message})

def text_message_start(message_id: str) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.TEXT_MESSAGE_START, data={"message_id": message_id})

def text_message_content(message_id: str, delta: str) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.TEXT_MESSAGE_CONTENT, data={"message_id": message_id, "delta": delta})

def text_message_end(message_id: str) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.TEXT_MESSAGE_END, data={"message_id": message_id})

def tool_call_start(tool_call_id: str, tool_name: str) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.TOOL_CALL_START, data={"tool_call_id": tool_call_id, "tool_name": tool_name})

def tool_call_end(tool_call_id: str) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.TOOL_CALL_END, data={"tool_call_id": tool_call_id})

def tool_call_result(tool_call_id: str, result: Any) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.TOOL_CALL_RESULT, data={"tool_call_id": tool_call_id, "result": result})

def step_started(step_id: str, skill_apikey: str, step_index: int) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.STEP_STARTED, data={"step_id": step_id, "skill_apikey": skill_apikey, "step_index": step_index})

def step_finished(step_id: str, skill_apikey: str, step_index: int, status: str = "completed") -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.STEP_FINISHED, data={"step_id": step_id, "skill_apikey": skill_apikey, "step_index": step_index, "status": status})

def reasoning_started() -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.REASONING_STARTED)

def reasoning_content(delta: str) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.REASONING_CONTENT, data={"delta": delta})

def reasoning_finished() -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.REASONING_FINISHED)

def messages_snapshot(messages: list) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.MESSAGES_SNAPSHOT, data={"messages": messages})

def custom_event(name: str, value: dict) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.CUSTOM, data={"name": name, "value": value})
