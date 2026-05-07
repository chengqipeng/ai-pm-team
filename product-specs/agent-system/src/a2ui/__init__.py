"""A2UI v0.8 协议层 — 声明式 UI 描述协议

与 AG-UI 事件层的分工：
- AG-UI（src/agui/）：传输 Agent 运行时事件（RUN/TEXT_MESSAGE/TOOL_CALL/STEP/STATE/...）
- A2UI（src/a2ui/）：描述"让用户看到什么界面"的结构化 JSONL 消息

A2UI 消息有四种：
- SurfaceUpdate     — 定义/更新一个 UI 面板的组件列表（邻接表模型）
- DataModelUpdate   — 更新面板的数据模型（BoundValue 通过 path 引用）
- BeginRendering    — 通知前端开始渲染（含 surfaceId + root 组件 id）
- DeleteSurface     — 移除一个 UI 面板

融合方式：A2UI 消息通过 AG-UI ACTIVITY_SNAPSHOT 事件下发；
业务数据通过 AG-UI STATE_SNAPSHOT / STATE_DELTA 事件下发。

参考: https://a2ui.org/specification/v0.8-a2ui/
"""
from .models import (
    # BoundValue & DataEntry
    BoundValue,
    DataEntry,
    # 组件
    Component,
    # 四种消息
    SurfaceUpdate,
    DataModelUpdate,
    BeginRendering,
    DeleteSurface,
    # BoundValue 工厂函数
    literal,
    path_bind,
    # DataEntry 工厂函数
    entry_string,
    entry_int,
    entry_number,
    entry_boolean,
    entry_map,
    entry_list,
)
from .builder import A2UIBuilder
from .emitter import A2UIEmitter, a2ui_events
from .aggregator import SnapshotAggregator, DELTA_THRESHOLD, NOTIFICATION_SURFACE_ID

__all__ = [
    "BoundValue", "DataEntry", "Component",
    "SurfaceUpdate", "DataModelUpdate", "BeginRendering", "DeleteSurface",
    "literal", "path_bind",
    "entry_string", "entry_int", "entry_number", "entry_boolean", "entry_map", "entry_list",
    "A2UIBuilder",
    "A2UIEmitter", "a2ui_events",
    "SnapshotAggregator", "DELTA_THRESHOLD", "NOTIFICATION_SURFACE_ID",
]
