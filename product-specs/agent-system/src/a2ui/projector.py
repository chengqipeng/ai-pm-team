"""A2UI Projector — 从 AG-UI 事件流投影出纯 A2UI 消息流

Mode A 主传输通道的核心实现：

AG-UI 事件流  ──────────────────────────►  A2UI 消息流
  RUN_STARTED          (drop)
  MESSAGES_SNAPSHOT    (drop)
  TEXT_MESSAGE_*       (drop)
  TOOL_CALL_*          (drop)
  REASONING_*          (drop)
  CUSTOM(component_*)  (drop)                               (内部事件)
  STATE_SNAPSHOT/DELTA (drop by default; 可通过参数转成 dataModelUpdate)
  ACTIVITY_SNAPSHOT    → surfaceUpdate / dataModelUpdate /  beginRendering / deleteSurface
  ACTIVITY_DELTA       (drop; 规范里 A2UI v0.8 没有 delta 消息)

用法：

    projector = A2UIProjector()
    async for a2ui_msg in projector.project(agui_event_stream):
        yield a2ui_msg.to_jsonl()

设计取舍：
- **纯投影，不加工**：不根据 STATE_SNAPSHOT 重新生成 dataModelUpdate；数据路径已在
  surfaceUpdate 的 BoundValue 里引用了 Shared State，客户端自己维护一份即可。
- 若 Mode A 客户端 **没有** Shared State 概念（纯 A2UI v0.8 客户端应当要有），
  可开启 `include_state_as_data_model=True`，把 STATE_SNAPSHOT 转成针对 `notifications surface`
  的 dataModelUpdate（见下方实现注释）。
"""
from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, AsyncIterable

from src.agui.models import AGUIEvent, AGUIEventType

from .models import (
    A2UIMessage,
    BeginRendering,
    Component,
    DataEntry,
    DataModelUpdate,
    DeleteSurface,
    SurfaceUpdate,
    dict_to_entries,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 反序列化：A2UI message dict → dataclass
# ═══════════════════════════════════════════════════════════

def _parse_surface_update(body: dict) -> SurfaceUpdate:
    surface_id = body.get("surfaceId", "")
    components_raw = body.get("components", []) or []
    components: list[Component] = []
    for c in components_raw:
        if not isinstance(c, dict):
            continue
        comp_id = c.get("id") or ""
        inner = c.get("component") or {}
        if not inner or not isinstance(inner, dict):
            continue
        # component 字段必须是 {"<Type>": {<props>}}，恰好一个键
        if len(inner) != 1:
            logger.warning("Invalid component wrapper: %s", inner)
            continue
        type_name, props = next(iter(inner.items()))
        components.append(Component(
            id=comp_id,
            type=str(type_name),
            props=dict(props or {}),
        ))
    return SurfaceUpdate(surface_id=surface_id, components=components)


def _parse_data_entries(contents: list[dict]) -> list[DataEntry]:
    out: list[DataEntry] = []
    for entry in contents or []:
        if not isinstance(entry, dict) or "key" not in entry:
            continue
        key = entry["key"]
        if "valueString" in entry:
            out.append(DataEntry(key=key, value_string=entry["valueString"]))
        elif "valueInt" in entry:
            out.append(DataEntry(key=key, value_int=entry["valueInt"]))
        elif "valueNumber" in entry:
            out.append(DataEntry(key=key, value_number=entry["valueNumber"]))
        elif "valueBoolean" in entry:
            out.append(DataEntry(key=key, value_boolean=entry["valueBoolean"]))
        elif "valueMap" in entry:
            out.append(DataEntry(
                key=key,
                value_map=_parse_data_entries(entry["valueMap"] or []),
            ))
        elif "valueList" in entry:
            out.append(DataEntry(key=key, value_list=entry["valueList"] or []))
        elif "valueArray" in entry:  # 兼容别名
            out.append(DataEntry(key=key, value_list=entry["valueArray"] or []))
    return out


def _parse_data_model_update(body: dict) -> DataModelUpdate:
    return DataModelUpdate(
        surface_id=body.get("surfaceId", ""),
        contents=_parse_data_entries(body.get("contents", []) or []),
        path=body.get("path"),
    )


def _parse_begin_rendering(body: dict) -> BeginRendering:
    return BeginRendering(
        surface_id=body.get("surfaceId", ""),
        root=body.get("root", ""),
        catalog_id=body.get("catalogId"),
    )


def _parse_delete_surface(body: dict) -> DeleteSurface:
    return DeleteSurface(surface_id=body.get("surfaceId", ""))


def parse_a2ui_message(op: dict) -> A2UIMessage | None:
    """把一个 A2UI 操作 dict 还原为对应的 A2UIMessage dataclass。

    同时支持两种格式：
    - 键名标识（A2UI v0.8 官方）：`{"surfaceUpdate": {...}}`
    - 类型标识（早期 CopilotKit）：`{"type": "surfaceUpdate", ...}`
    """
    if not isinstance(op, dict):
        return None

    # 键名格式优先
    for key, parser in (
        ("surfaceUpdate", _parse_surface_update),
        ("dataModelUpdate", _parse_data_model_update),
        ("beginRendering", _parse_begin_rendering),
        ("deleteSurface", _parse_delete_surface),
    ):
        if key in op and isinstance(op[key], dict):
            return parser(op[key])

    # type 格式兜底
    t = op.get("type")
    if t == "surfaceUpdate":
        return _parse_surface_update(op)
    if t == "dataModelUpdate":
        return _parse_data_model_update(op)
    if t == "beginRendering":
        return _parse_begin_rendering(op)
    if t == "deleteSurface":
        return _parse_delete_surface(op)

    logger.warning("Unknown A2UI operation: keys=%s", list(op.keys())[:5])
    return None


# ═══════════════════════════════════════════════════════════
# A2UIProjector
# ═══════════════════════════════════════════════════════════

class A2UIProjector:
    """AG-UI 事件流 → A2UI 消息流的投影器。"""

    NOTIFICATIONS_SURFACE_ID = "panel-slot-top-1"

    def __init__(
        self,
        *,
        include_state_as_data_model: bool = False,
        activity_type_filter: str = "a2ui-surface",
    ) -> None:
        """
        Args:
            include_state_as_data_model: 若开启，Shared State (STATE_SNAPSHOT) 会被转成
                一条针对通知 surface 的 dataModelUpdate（path = "/data"）。适合没有
                Shared State 概念的纯 A2UI 客户端。默认关闭。
            activity_type_filter: 只消费此 activity_type 的 ACTIVITY_SNAPSHOT；其他
                （如 PLAN / SEARCH）会被忽略。
        """
        self._include_state_as_data_model = include_state_as_data_model
        self._activity_filter = activity_type_filter

    async def project(
        self,
        events: AsyncIterable[AGUIEvent],
    ) -> AsyncGenerator[A2UIMessage, None]:
        async for event in events:
            async for msg in self._project_one(event):
                yield msg

    async def _project_one(self, event: AGUIEvent) -> AsyncGenerator[A2UIMessage, None]:
        t = event.type
        # Enum or str
        t_val = getattr(t, "value", t)

        if t_val == AGUIEventType.ACTIVITY_SNAPSHOT.value:
            if event.data.get("activity_type") != self._activity_filter:
                return
            operations = (event.data.get("content") or {}).get("operations") or []
            for op in operations:
                msg = parse_a2ui_message(op)
                if msg is not None:
                    yield msg
            return

        if (self._include_state_as_data_model
                and t_val == AGUIEventType.STATE_SNAPSHOT.value):
            snapshot = event.data.get("snapshot") or {}
            data_section = snapshot.get("data") or {}
            if data_section:
                yield DataModelUpdate(
                    surface_id=self.NOTIFICATIONS_SURFACE_ID,
                    contents=dict_to_entries(data_section),
                    path="data",
                )
            return

        # 其他事件丢弃


__all__ = ["A2UIProjector", "parse_a2ui_message"]
