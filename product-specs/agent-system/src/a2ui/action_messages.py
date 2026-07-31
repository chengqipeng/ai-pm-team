"""页面操作在 Chat 中的 AG-UI Activity 表示。"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Any

from src.agui.models import AGUIEvent, activity_snapshot
from .models import UserAction

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_VISIBILITIES = {"hidden", "compact", "full", "agent"}


def _text(value: Any, limit: int = 160) -> str:
    cleaned = " ".join(str(value or "").replace("\x00", "").split())
    return cleaned[:limit]


def _fallback_action_id(action: UserAction) -> str:
    raw = "|".join((action.surface_id, action.source_component_id,
                    action.timestamp, action.name))
    return "act-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class NormalizedAction:
    action_id: str
    thread_id: str
    name: str
    surface_id: str
    component_id: str
    context: dict[str, Any]
    chat_visibility: str
    label: str
    user_text: str
    started_at: int

    def source_dict(self) -> dict[str, Any]:
        return {
            "placement": _text(self.context.get("placement") or "page", 32),
            "viewId": _text(self.context.get("viewId"), 128),
            "surfaceId": self.surface_id,
            "componentId": self.component_id,
        }

    def action_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "entityApiKey": _text(self.context.get("entityApiKey"), 128),
            "recordApiKey": _text(self.context.get("recordApiKey"), 128),
        }


def normalize_action(thread_id: str, action: UserAction, *,
                     visibility: str | None = None) -> NormalizedAction:
    thread_id = _text(thread_id, 128)
    if not thread_id or not _ID_RE.fullmatch(thread_id):
        raise ValueError("invalid threadId")
    if not action.name or not _ID_RE.fullmatch(action.name):
        raise ValueError("invalid userAction.name")

    context = dict(action.context or {})
    action_id = _text(
        action.action_id or context.get("actionId")
        or context.get("idempotencyKey") or _fallback_action_id(action), 128)
    if not _ID_RE.fullmatch(action_id):
        raise ValueError("invalid actionId")

    effective_visibility = visibility or context.get("chatVisibility") or "compact"
    if effective_visibility not in _VISIBILITIES:
        raise ValueError("invalid chatVisibility")
    label = _text(context.get("actionLabel") or context.get("label") or action.name)
    view_label = _text(context.get("viewLabel") or context.get("viewId"), 80)
    user_text = _text(context.get("userText"), 240)
    if not user_text:
        user_text = f"你在{view_label}中执行了{label}" if view_label else f"你执行了{label}"

    return NormalizedAction(
        action_id=action_id,
        thread_id=thread_id,
        name=action.name,
        surface_id=_text(action.surface_id, 128),
        component_id=_text(action.source_component_id, 128),
        context=context,
        chat_visibility=effective_visibility,
        label=label,
        user_text=user_text,
        started_at=int(time.time() * 1000),
    )


def ui_action_chat_messages(
    action: NormalizedAction,
    result: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """把成功的确定性保存动作转换成可恢复、可幂等的聊天消息对。"""
    operation = _text(result.get("operation"), 32)
    if operation not in {"created", "updated"}:
        raise ValueError("only created/updated actions can be persisted to chat")

    record = result.get("record") if isinstance(result.get("record"), dict) else {}
    entity = _text(record.get("entityApiKey") or action.context.get("entityApiKey"), 128)
    record_key = _text(record.get("recordApiKey"), 128)
    version = record.get("version")
    display_name = _text(
        record.get("name") or record.get("accountName")
        or record.get("customerName"), 120)

    user_text = action.user_text
    verb = "创建" if operation == "created" else "更新"
    target = f"客户“{display_name}”" if display_name else (entity or "业务记录")
    details = [f"记录标识 {record_key}" if record_key else ""]
    if version not in (None, ""):
        details.append(f"版本 v{_text(version, 24)}")
    detail_text = "，".join(item for item in details if item)
    assistant_text = f"{target}{verb}成功"
    if detail_text:
        assistant_text += f"（{detail_text}）"
    assistant_text += "，详情与当前会话上下文已同步。"

    metadata = {
        "contentType": "ui-action",
        "actionId": action.action_id,
        "actionName": action.name,
        "operation": operation,
        "entityApiKey": entity,
        "recordApiKey": record_key,
        "status": "succeeded",
        "originIntent": f"crm_ui_{action.name}",
        "userTriggeredViewIds": (
            [f"{entity}:detail:{record_key}"]
            if entity and record_key else []
        ),
    }
    return (
        {
            "id": f"ui-action-{action.action_id}-user",
            "role": "user",
            "content": user_text,
            "metadata": metadata,
        },
        {
            "id": f"ui-action-{action.action_id}-assistant",
            "role": "assistant",
            "content": assistant_text,
            "metadata": metadata,
        },
    )


def ui_action_activity(action: NormalizedAction, phase: str, *,
                       status_text: str, result: dict[str, Any] | None = None,
                       error: dict[str, Any] | None = None) -> AGUIEvent:
    if phase not in {"accepted", "running", "succeeded", "failed"}:
        raise ValueError(f"invalid ui-action phase: {phase}")
    content: dict[str, Any] = {
        "actionId": action.action_id,
        "threadId": action.thread_id,
        "phase": phase,
        "actor": {"type": "user"},
        "source": action.source_dict(),
        "action": action.action_dict(),
        "display": {
            "visibility": action.chat_visibility,
            "userText": action.user_text,
            "statusText": _text(status_text, 240),
        },
        "startedAt": action.started_at,
    }
    if result is not None:
        content["result"] = result
    if error is not None:
        content["error"] = error
    if phase in {"succeeded", "failed"}:
        content["finishedAt"] = int(time.time() * 1000)
    return activity_snapshot(
        message_id=f"ui-action-{action.action_id}",
        activity_type="ui-action",
        content=content,
        replace=True,
    )
