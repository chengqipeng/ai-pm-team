"""A2UIEmitter — 把 A2UI 消息包装成 AG-UI 事件

按融合架构（参考 apps-agent D1 决策）：
- ActivitySnapshotEvent：承载 A2UI 的 surfaceUpdate / deleteSurface（UI 操作指令）
- CustomEvent (name="a2ui.<message_type>")：承载单条 A2UI 消息，向后兼容不支持
  ActivitySnapshotEvent 的客户端

两种模式可共存；推荐用 ActivitySnapshot 作为主通道，CUSTOM 作为 fallback。
"""
from __future__ import annotations

from typing import Iterable

from src.agui import models as agui
from .models import (
    A2UIMessage,
    BeginRendering,
    DeleteSurface,
    DataModelUpdate,
    SurfaceUpdate,
)


def _message_name(msg: A2UIMessage) -> str:
    """A2UI 消息 → AG-UI CUSTOM event name"""
    mapping = {
        SurfaceUpdate:   "a2ui.surfaceUpdate",
        DataModelUpdate: "a2ui.dataModelUpdate",
        BeginRendering:  "a2ui.beginRendering",
        DeleteSurface:   "a2ui.deleteSurface",
    }
    cls = type(msg)
    if cls not in mapping:
        raise TypeError(f"未知的 A2UI 消息类型: {cls}")
    return mapping[cls]


class A2UIEmitter:
    """将 A2UI 消息转换为 AG-UI 事件流。

    用法:
        emitter = A2UIEmitter(run_id="r-123", message_id_prefix="a2ui")
        for event in emitter.emit_activity(messages):
            yield event
    """

    def __init__(self, run_id: str, message_id_prefix: str = "a2ui") -> None:
        self.run_id = run_id
        self._message_id = f"{message_id_prefix}-{run_id[:8]}"

    # ── 主通道：ACTIVITY_SNAPSHOT ──

    def emit_activity(
        self,
        messages: Iterable[A2UIMessage],
        activity_type: str = "a2ui-surface",
        replace: bool = True,
    ) -> list[agui.AGUIEvent]:
        """把一批 A2UI 消息打成一个 ACTIVITY_SNAPSHOT 事件

        content 结构遵循 AG-UI v1 规范：
            {"operations": [<A2UI message dict>, ...]}
        """
        ops = [m.to_dict() for m in messages]
        return [
            agui.activity_snapshot(
                message_id=self._message_id,
                activity_type=activity_type,
                content={"operations": ops},
                replace=replace,
            )
        ]

    def emit_activity_delta(
        self,
        patch: list[dict],
        activity_type: str = "a2ui-surface",
    ) -> list[agui.AGUIEvent]:
        """发送 ACTIVITY_DELTA（JSON Patch 增量）"""
        return [
            agui.activity_delta(
                message_id=self._message_id,
                activity_type=activity_type,
                patch=patch,
            )
        ]

    # ── 旁通道：CUSTOM（每条消息独立 CUSTOM 事件）──

    def emit_custom(self, messages: Iterable[A2UIMessage]) -> list[agui.AGUIEvent]:
        """把每条 A2UI 消息单独包成 CUSTOM 事件。

        适合对 ActivitySnapshot 不熟的旧客户端或调试。
        """
        events: list[agui.AGUIEvent] = []
        for msg in messages:
            events.append(agui.custom_event(
                name=_message_name(msg),
                value=msg.to_dict(),
            ))
        return events


def a2ui_events(
    messages: Iterable[A2UIMessage],
    run_id: str,
    *,
    mode: str = "activity",
    message_id_prefix: str = "a2ui",
    activity_type: str = "a2ui-surface",
) -> list[agui.AGUIEvent]:
    """便捷函数：一次性把 A2UI 消息转成 AG-UI 事件

    Args:
        messages: A2UI 消息列表
        run_id: AG-UI run_id（用于生成稳定的 message_id）
        mode: "activity" | "custom" | "both"（双发）
    """
    emitter = A2UIEmitter(run_id=run_id, message_id_prefix=message_id_prefix)
    events: list[agui.AGUIEvent] = []
    if mode in ("activity", "both"):
        events.extend(emitter.emit_activity(messages, activity_type=activity_type))
    if mode in ("custom", "both"):
        events.extend(emitter.emit_custom(messages))
    if not events:
        raise ValueError(f"未知 mode={mode}，应为 activity/custom/both")
    return events
