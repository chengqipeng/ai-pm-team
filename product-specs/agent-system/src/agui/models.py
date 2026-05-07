"""AG-UI 事件模型 — 严格对齐官方 Python SDK

参考: https://docs.ag-ui.com/sdk/python/core/events

事件类型分组：
- Agent 生命周期: RUN_STARTED / RUN_FINISHED / RUN_ERROR
- Step:           STEP_STARTED / STEP_FINISHED  （只有 step_name，扩展字段走 CUSTOM("step_metadata")）
- 文本:           TEXT_MESSAGE_START/CONTENT/END/CHUNK
- 工具调用:       TOOL_CALL_START/ARGS/END/RESULT/CHUNK
- 推理（新分层）: REASONING_START/END + REASONING_MESSAGE_START/CONTENT/END/CHUNK
                 REASONING_ENCRYPTED_VALUE
- 快照:           STATE_SNAPSHOT / STATE_DELTA / MESSAGES_SNAPSHOT
- 活动（A2UI）:   ACTIVITY_SNAPSHOT / ACTIVITY_DELTA
- 扩展:           RAW / CUSTOM

向后兼容：
- `REASONING_STARTED/CONTENT/FINISHED` 保留作为旧事件别名（一期迁移）
- `reasoning_started/content/finished` 工厂函数内部转发到新事件，带 DeprecationWarning
"""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AGUIEventType(str, Enum):
    """AG-UI 标准事件类型（含 A2UI 融合扩展）"""
    # ── Agent 生命周期 ──
    RUN_STARTED = "RUN_STARTED"
    RUN_FINISHED = "RUN_FINISHED"
    RUN_ERROR = "RUN_ERROR"
    # ── Step ──
    STEP_STARTED = "STEP_STARTED"
    STEP_FINISHED = "STEP_FINISHED"
    # ── 文本消息 ──
    TEXT_MESSAGE_START = "TEXT_MESSAGE_START"
    TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
    TEXT_MESSAGE_END = "TEXT_MESSAGE_END"
    TEXT_MESSAGE_CHUNK = "TEXT_MESSAGE_CHUNK"
    # ── 工具调用 ──
    TOOL_CALL_START = "TOOL_CALL_START"
    TOOL_CALL_ARGS = "TOOL_CALL_ARGS"
    TOOL_CALL_END = "TOOL_CALL_END"
    TOOL_CALL_RESULT = "TOOL_CALL_RESULT"
    TOOL_CALL_CHUNK = "TOOL_CALL_CHUNK"
    # ── 推理（新分层）──
    REASONING_START = "REASONING_START"
    REASONING_MESSAGE_START = "REASONING_MESSAGE_START"
    REASONING_MESSAGE_CONTENT = "REASONING_MESSAGE_CONTENT"
    REASONING_MESSAGE_END = "REASONING_MESSAGE_END"
    REASONING_MESSAGE_CHUNK = "REASONING_MESSAGE_CHUNK"
    REASONING_END = "REASONING_END"
    REASONING_ENCRYPTED_VALUE = "REASONING_ENCRYPTED_VALUE"
    # ── 推理（旧事件，一期兼容）──
    REASONING_STARTED = "REASONING_STARTED"   # deprecated → REASONING_START
    REASONING_CONTENT = "REASONING_CONTENT"   # deprecated → REASONING_MESSAGE_CONTENT
    REASONING_FINISHED = "REASONING_FINISHED"  # deprecated → REASONING_END
    # ── 消息快照 ──
    MESSAGES_SNAPSHOT = "MESSAGES_SNAPSHOT"
    # ── 业务状态（承载 A2UI 数据模型）──
    STATE_SNAPSHOT = "STATE_SNAPSHOT"
    STATE_DELTA = "STATE_DELTA"
    # ── UI 活动（承载 A2UI surfaceUpdate）──
    ACTIVITY_SNAPSHOT = "ACTIVITY_SNAPSHOT"
    ACTIVITY_DELTA = "ACTIVITY_DELTA"
    # ── 扩展 ──
    RAW = "RAW"
    CUSTOM = "CUSTOM"


@dataclass
class AGUIEvent:
    """AG-UI 事件基类"""
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: int | None = None
    raw_event: Any | None = None

    def _type_str(self) -> str:
        """规范化 type 为字符串（兼容 Enum 输入）。

        Python 3.11 下 `AGUIEventType.RUN_STARTED` 的 `__str__` 返回
        "AGUIEventType.RUN_STARTED"，不是值本身；必须显式取 value。
        """
        t = self.type
        val = getattr(t, "value", None)
        return val if isinstance(val, str) else str(t)

    def to_sse(self) -> str:
        return f"event: {self._type_str()}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self._type_str(), **self.data}
        if self.timestamp is not None:
            out["timestamp"] = self.timestamp
        if self.raw_event is not None:
            out["raw_event"] = self.raw_event
        return out


# ═══════════════════════════════════════════════════════════
# 生命周期事件
# ═══════════════════════════════════════════════════════════

def run_started(run_id: str, thread_id: str,
                parent_run_id: str | None = None,
                input: Any | None = None) -> AGUIEvent:
    """RunStartedEvent — 对齐官方 SDK 字段。"""
    data: dict[str, Any] = {"run_id": run_id, "thread_id": thread_id}
    if parent_run_id is not None:
        data["parent_run_id"] = parent_run_id
    if input is not None:
        data["input"] = input
    return AGUIEvent(type=AGUIEventType.RUN_STARTED, data=data)


def run_finished(run_id: str, thread_id: str,
                 result: Any | None = None) -> AGUIEvent:
    data: dict[str, Any] = {"run_id": run_id, "thread_id": thread_id}
    if result is not None:
        data["result"] = result
    return AGUIEvent(type=AGUIEventType.RUN_FINISHED, data=data)


def run_error(message: str, code: str | None = None,
              *, error_type: str | None = None,
              error_message: str | None = None) -> AGUIEvent:
    """RunErrorEvent — 对齐官方字段 `{message, code?}`。

    为兼容旧调用方 `run_error(error_type=..., error_message=...)`，保留旧参数名。
    """
    if error_message is not None:
        message = error_message
    if error_type is not None and code is None:
        code = error_type
    data: dict[str, Any] = {"message": message}
    if code is not None:
        data["code"] = code
    # 兼容旧字段（transitional）
    if error_type is not None:
        data["error_type"] = error_type
    if error_message is not None:
        data["error_message"] = error_message
    return AGUIEvent(type=AGUIEventType.RUN_ERROR, data=data)


# ═══════════════════════════════════════════════════════════
# Step 事件（官方仅 step_name；扩展字段走 CUSTOM("step_metadata")）
# ═══════════════════════════════════════════════════════════

def step_started(step_name: str, *,
                 skill_apikey: str | None = None,
                 step_index: int | None = None) -> AGUIEvent:
    """StepStartedEvent — 只发 step_name，扩展字段通过 step_metadata CUSTOM 事件补充。"""
    return AGUIEvent(type=AGUIEventType.STEP_STARTED, data={"step_name": step_name})


def step_finished(step_name: str, *,
                  skill_apikey: str | None = None,
                  step_index: int | None = None,
                  status: str | None = None) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.STEP_FINISHED, data={"step_name": step_name})


def step_metadata(step_name: str, *,
                  skill_apikey: str | None = None,
                  step_index: int | None = None,
                  status: str | None = None,
                  phase: str = "started") -> AGUIEvent:
    """伴随 STEP_STARTED/FINISHED 发出的扩展信息（D4）。"""
    value: dict[str, Any] = {"step_name": step_name, "phase": phase}
    if skill_apikey is not None:
        value["skill_apikey"] = skill_apikey
    if step_index is not None:
        value["step_index"] = step_index
    if status is not None:
        value["status"] = status
    return AGUIEvent(type=AGUIEventType.CUSTOM,
                     data={"name": "step_metadata", "value": value})


# ═══════════════════════════════════════════════════════════
# 文本消息事件
# ═══════════════════════════════════════════════════════════

def text_message_start(message_id: str, role: str = "assistant") -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.TEXT_MESSAGE_START,
                     data={"message_id": message_id, "role": role})


def text_message_content(message_id: str, delta: str) -> AGUIEvent:
    """TextMessageContentEvent — delta 必须非空。"""
    if not delta:
        raise ValueError("TEXT_MESSAGE_CONTENT delta must not be empty")
    return AGUIEvent(type=AGUIEventType.TEXT_MESSAGE_CONTENT,
                     data={"message_id": message_id, "delta": delta})


def text_message_end(message_id: str) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.TEXT_MESSAGE_END,
                     data={"message_id": message_id})


def text_message_chunk(message_id: str | None = None,
                       delta: str | None = None,
                       role: str = "assistant") -> AGUIEvent:
    """TextMessageChunkEvent — 便捷事件，首 chunk 必带 message_id。"""
    data: dict[str, Any] = {}
    if message_id is not None:
        data["message_id"] = message_id
    if delta is not None:
        data["delta"] = delta
    if role:
        data["role"] = role
    return AGUIEvent(type=AGUIEventType.TEXT_MESSAGE_CHUNK, data=data)


# ═══════════════════════════════════════════════════════════
# 工具调用事件
# ═══════════════════════════════════════════════════════════

def tool_call_start(tool_call_id: str,
                    tool_call_name: str | None = None,
                    parent_message_id: str | None = None,
                    *,
                    tool_name: str | None = None) -> AGUIEvent:
    """ToolCallStartEvent。`tool_name` 是旧参数名，保留兼容。"""
    name = tool_call_name or tool_name or ""
    data: dict[str, Any] = {"tool_call_id": tool_call_id, "tool_call_name": name}
    if parent_message_id is not None:
        data["parent_message_id"] = parent_message_id
    return AGUIEvent(type=AGUIEventType.TOOL_CALL_START, data=data)


def tool_call_args(tool_call_id: str, delta: str) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.TOOL_CALL_ARGS,
                     data={"tool_call_id": tool_call_id, "delta": delta})


def tool_call_end(tool_call_id: str) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.TOOL_CALL_END,
                     data={"tool_call_id": tool_call_id})


def tool_call_result(tool_call_id: str,
                     result: Any = None,
                     *,
                     message_id: str | None = None,
                     content: Any = None,
                     role: str = "tool") -> AGUIEvent:
    """ToolCallResultEvent。

    官方字段：`{message_id, tool_call_id, content, role?}`
    旧版使用 `result` 参数名 — 作为 `content` 的别名保留。
    当 `message_id` 未提供时，回退使用 tool_call_id（保证字段完整性）。
    """
    effective_content = content if content is not None else result
    data: dict[str, Any] = {
        "message_id": message_id or tool_call_id,
        "tool_call_id": tool_call_id,
        "content": effective_content,
        "role": role,
    }
    # 兼容老前端读取 `result`
    data["result"] = effective_content
    return AGUIEvent(type=AGUIEventType.TOOL_CALL_RESULT, data=data)


def tool_call_chunk(tool_call_id: str | None = None,
                    tool_call_name: str | None = None,
                    delta: str | None = None,
                    parent_message_id: str | None = None) -> AGUIEvent:
    """ToolCallChunkEvent — 首 chunk 必带 id+name。"""
    data: dict[str, Any] = {}
    if tool_call_id is not None:
        data["tool_call_id"] = tool_call_id
    if tool_call_name is not None:
        data["tool_call_name"] = tool_call_name
    if delta is not None:
        data["delta"] = delta
    if parent_message_id is not None:
        data["parent_message_id"] = parent_message_id
    return AGUIEvent(type=AGUIEventType.TOOL_CALL_CHUNK, data=data)


# ═══════════════════════════════════════════════════════════
# 推理事件（新分层）
# ═══════════════════════════════════════════════════════════

def reasoning_start(message_id: str) -> AGUIEvent:
    """进入推理阶段（pass-through，不创建消息）"""
    return AGUIEvent(type=AGUIEventType.REASONING_START, data={"message_id": message_id})


def reasoning_end(message_id: str) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.REASONING_END, data={"message_id": message_id})


def reasoning_message_start(message_id: str) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.REASONING_MESSAGE_START,
                     data={"message_id": message_id, "role": "reasoning"})


def reasoning_message_content(message_id: str, delta: str) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.REASONING_MESSAGE_CONTENT,
                     data={"message_id": message_id, "delta": delta})


def reasoning_message_end(message_id: str) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.REASONING_MESSAGE_END,
                     data={"message_id": message_id})


def reasoning_message_chunk(message_id: str | None = None,
                            delta: str | None = None) -> AGUIEvent:
    data: dict[str, Any] = {}
    if message_id is not None:
        data["message_id"] = message_id
    if delta is not None:
        data["delta"] = delta
    return AGUIEvent(type=AGUIEventType.REASONING_MESSAGE_CHUNK, data=data)


def reasoning_encrypted_value(subtype: str, entity_id: str, encrypted_value: str) -> AGUIEvent:
    if subtype not in ("tool-call", "message"):
        raise ValueError(f"subtype must be 'tool-call' or 'message', got {subtype!r}")
    return AGUIEvent(type=AGUIEventType.REASONING_ENCRYPTED_VALUE, data={
        "subtype": subtype,
        "entity_id": entity_id,
        "encrypted_value": encrypted_value,
    })


# ── 旧推理工厂（Deprecated）──

def reasoning_started() -> AGUIEvent:
    """旧 API，转发到 REASONING_STARTED（旧事件名）。"""
    warnings.warn(
        "reasoning_started() is deprecated; emit reasoning_start(message_id)"
        " + reasoning_message_start(message_id) instead.",
        DeprecationWarning, stacklevel=2,
    )
    return AGUIEvent(type=AGUIEventType.REASONING_STARTED)


def reasoning_content(delta: str) -> AGUIEvent:
    warnings.warn(
        "reasoning_content() is deprecated; use reasoning_message_content(message_id, delta).",
        DeprecationWarning, stacklevel=2,
    )
    return AGUIEvent(type=AGUIEventType.REASONING_CONTENT, data={"delta": delta})


def reasoning_finished() -> AGUIEvent:
    warnings.warn(
        "reasoning_finished() is deprecated; emit reasoning_message_end()"
        " + reasoning_end(message_id) instead.",
        DeprecationWarning, stacklevel=2,
    )
    return AGUIEvent(type=AGUIEventType.REASONING_FINISHED)


# ═══════════════════════════════════════════════════════════
# 快照事件
# ═══════════════════════════════════════════════════════════

def messages_snapshot(messages: list) -> AGUIEvent:
    return AGUIEvent(type=AGUIEventType.MESSAGES_SNAPSHOT, data={"messages": messages})


def state_snapshot(snapshot: dict) -> AGUIEvent:
    """业务状态全量快照（Shared State 唯一源）。"""
    return AGUIEvent(type=AGUIEventType.STATE_SNAPSHOT, data={"snapshot": snapshot})


def state_delta(patch: list[dict]) -> AGUIEvent:
    """业务状态增量（RFC 6902 JSON Patch）。"""
    return AGUIEvent(type=AGUIEventType.STATE_DELTA, data={"delta": patch})


def activity_snapshot(message_id: str, activity_type: str, content: dict,
                      replace: bool = True) -> AGUIEvent:
    """UI 活动快照 — 典型承载 A2UI 的 surfaceUpdate 等消息。

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
    return AGUIEvent(
        type=AGUIEventType.ACTIVITY_DELTA,
        data={
            "message_id": message_id,
            "activity_type": activity_type,
            "patch": patch,
        },
    )


# ═══════════════════════════════════════════════════════════
# 扩展事件
# ═══════════════════════════════════════════════════════════

def raw(event: Any, source: str | None = None) -> AGUIEvent:
    """RawEvent — 透传外部系统原始事件。"""
    data: dict[str, Any] = {"event": event}
    if source is not None:
        data["source"] = source
    return AGUIEvent(type=AGUIEventType.RAW, data=data)


def custom_event(name: str, value: dict) -> AGUIEvent:
    """CustomEvent — 应用自定义事件。

    命名空间约定（对齐 ai-native-app CustomEventDispatcher）：
    - a2ui.*           → A2UI 操作（A2UIBridge 消费）
    - ui.*             → 通用 UI 事件（EventBus 消费）
    - component_*      → 渐进式组件状态（component_loading/delta/complete/error/data）
    - step_metadata    → STEP 事件的扩展字段
    """
    return AGUIEvent(type=AGUIEventType.CUSTOM, data={"name": name, "value": value})


# custom_event 的别名
custom = custom_event
