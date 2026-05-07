"""AG-UI 事件模型 — 标准 AG-UI 协议事件类型

参考: https://docs.ag-ui.com/concepts/events
"""
from __future__ import annotations

from enum import Enum
from typing import Any
from dataclasses import dataclass, field


class AGUIEventType(str, Enum):
    """AG-UI 标准事件类型（含 A2UI 融合扩展）"""
    # ── Agent 生命周期 ──
    RUN_STARTED = "RUN_STARTED"
    RUN_FINISHED = "RUN_FINISHED"
    RUN_ERROR = "RUN_ERROR"
    # ── 文本消息 ──
    TEXT_MESSAGE_START = "TEXT_MESSAGE_START"
    TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
    TEXT_MESSAGE_END = "TEXT_MESSAGE_END"
    # ── 工具调用 ──
    TOOL_CALL_START = "TOOL_CALL_START"
    TOOL_CALL_ARGS = "TOOL_CALL_ARGS"
    TOOL_CALL_END = "TOOL_CALL_END"
    TOOL_CALL_RESULT = "TOOL_CALL_RESULT"
    # ── Skill Step ──
    STEP_STARTED = "STEP_STARTED"
    STEP_FINISHED = "STEP_FINISHED"
    # ── 推理 ──
    REASONING_STARTED = "REASONING_STARTED"
    REASONING_CONTENT = "REASONING_CONTENT"
    REASONING_FINISHED = "REASONING_FINISHED"
    # ── 消息快照 ──
    MESSAGES_SNAPSHOT = "MESSAGES_SNAPSHOT"
    # ── 业务状态（承载 A2UI 数据模型）──
    STATE_SNAPSHOT = "STATE_SNAPSHOT"
    STATE_DELTA = "STATE_DELTA"
    # ── UI 活动（承载 A2UI surfaceUpdate）──
    ACTIVITY_SNAPSHOT = "ACTIVITY_SNAPSHOT"
    ACTIVITY_DELTA = "ACTIVITY_DELTA"
    # ── 自定义（组件渲染唯一通道，参考 apps-agent D7）──
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


# ═══════════════════════════════════════════════════════════
# 新增事件构造器（A2UI 融合）
# ═══════════════════════════════════════════════════════════

def state_snapshot(snapshot: dict) -> AGUIEvent:
    """业务状态全量快照（纯数据，不含 UI 结构）"""
    return AGUIEvent(type=AGUIEventType.STATE_SNAPSHOT, data={"snapshot": snapshot})


def state_delta(patch: list[dict]) -> AGUIEvent:
    """业务状态增量（RFC 6902 JSON Patch）"""
    return AGUIEvent(type=AGUIEventType.STATE_DELTA, data={"delta": patch})


def activity_snapshot(message_id: str, activity_type: str, content: dict,
                      replace: bool = True) -> AGUIEvent:
    """UI 活动快照 — 典型承载 A2UI 的 surfaceUpdate 等消息

    content 推荐结构: {"operations": [<A2UI message dict>, ...]}
    """
    return AGUIEvent(
        type=AGUIEventType.ACTIVITY_SNAPSHOT,
        data={
            "message_id": message_id,
            "activity_type": activity_type,
            "content": content,
            "replace": replace,
        },
    )


def activity_delta(message_id: str, activity_type: str, patch: list[dict]) -> AGUIEvent:
    """UI 活动增量（对 content 结构打 JSON Patch）"""
    return AGUIEvent(
        type=AGUIEventType.ACTIVITY_DELTA,
        data={
            "message_id": message_id,
            "activity_type": activity_type,
            "patch": patch,
        },
    )
