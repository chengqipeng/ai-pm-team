"""Official AG-UI wire compatibility boundary.

The runtime keeps the internal ``AGUIEvent`` model for legacy clients.  This
module validates each outbound event with the official SDK and delegates SSE
serialization to ``EventEncoder``.
"""
from __future__ import annotations

from typing import Any

from ag_ui.core import Event, RunAgentInput
from ag_ui.encoder import EventEncoder
from pydantic import TypeAdapter

from .models import AGUIEvent

OfficialRunAgentInput = RunAgentInput

_EVENT_ADAPTER = TypeAdapter(Event)
_EVENT_ENCODER = EventEncoder(accept="text/event-stream")

_KEY_ALIASES = {
    "raw_event": "rawEvent",
    "run_id": "runId",
    "thread_id": "threadId",
    "parent_run_id": "parentRunId",
    "step_name": "stepName",
    "message_id": "messageId",
    "tool_call_id": "toolCallId",
    "tool_call_name": "toolCallName",
    "parent_message_id": "parentMessageId",
    "entity_id": "entityId",
    "encrypted_value": "encryptedValue",
    "activity_type": "activityType",
}

_DEPRECATED_EVENT_TYPES = {
    "REASONING_STARTED",
    "REASONING_CONTENT",
    "REASONING_FINISHED",
}

_COMPAT_ONLY_FIELDS = {
    "RUN_ERROR": {"error_type", "error_message"},
    "TOOL_CALL_RESULT": {"result"},
}

def to_official_event(event: AGUIEvent) -> Any | None:
    """Convert and validate an internal event as an official SDK event."""
    event_type = event._type_str()
    if event_type in _DEPRECATED_EVENT_TYPES:
        return None

    dropped = _COMPAT_ONLY_FIELDS.get(event_type, set())
    payload: dict[str, Any] = {"type": event_type}
    for key, value in event.data.items():
        if key in dropped:
            continue
        payload[_KEY_ALIASES.get(key, key)] = value
    if event.timestamp is not None:
        payload["timestamp"] = event.timestamp
    if event.raw_event is not None:
        payload["rawEvent"] = event.raw_event
    return _EVENT_ADAPTER.validate_python(payload)


def encode_official_sse(
    event: AGUIEvent,
    event_id: str | int | None = None,
) -> str:
    """Encode a complete camelCase BaseEvent with the official encoder."""
    official_event = to_official_event(event)
    if official_event is None:
        return ""
    encoded = _EVENT_ENCODER.encode(official_event)
    if event_id is None:
        return encoded
    safe_id = str(event_id).replace("\r", "").replace("\n", "")
    return f"id: {safe_id}\n{encoded}"


__all__ = [
    "OfficialRunAgentInput",
    "encode_official_sse",
    "to_official_event",
]
