"""A2UI v0.8 协议层 — 声明式 UI 描述协议

与 AG-UI 事件层的分工：
- AG-UI（src/agui/）：传输 Agent 运行时事件（RUN/TEXT_MESSAGE/TOOL_CALL/STEP/STATE/...）
- A2UI（src/a2ui/）：描述"让用户看到什么界面"的结构化 JSONL 消息

A2UI 消息有四种：
- SurfaceUpdate     — 定义/更新一个 UI 面板的组件列表（邻接表模型）
- DataModelUpdate   — 更新面板的数据模型（BoundValue 通过 path 引用）
- BeginRendering    — 通知前端开始渲染（含 surfaceId + root 组件 id）
- DeleteSurface     — 移除一个 UI 面板

客户端入站（§5）：
- UserAction        — 用户交互事件
- ClientError       — 渲染/绑定错误

融合方式：
- Mode B（默认）：A2UI 消息通过 AG-UI ACTIVITY_SNAPSHOT 事件下发
- Mode A：独立 JSONL / SSE 通道（`stream.py`）
- 业务数据通过 AG-UI STATE_SNAPSHOT / STATE_DELTA 事件下发（Shared State 唯一源）

参考: https://a2ui.org/specification/v0.8-a2ui/
"""
from .models import (
    # BoundValue & DataEntry
    BoundValue,
    DataEntry,
    # 组件
    Component,
    # 四种服务端消息
    SurfaceUpdate,
    DataModelUpdate,
    BeginRendering,
    DeleteSurface,
    A2UIMessage,
    # 客户端入站
    UserAction,
    ClientError,
    ClientEvent,
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
    dict_to_entries,
)
from .builder import A2UIBuilder
from .emitter import A2UIEmitter, a2ui_events
from .aggregator import SnapshotAggregator, DELTA_THRESHOLD, NOTIFICATION_SURFACE_ID
from .catalog import (
    CatalogDefinition,
    CatalogRegistry,
    ComponentMeta,
    ComponentMatcherV2,
    STANDARD_V08,
    VIKING_CRM_V1,
    SCHEMA_MATCH_THRESHOLD,
)
from .inbound import (
    A2UIInboundHandler,
    InboundDedupe,
    parse_client_event,
)
from .stream import a2ui_jsonl_stream, a2ui_sse_stream
from .render_helper import A2UIRenderHelper, SurfaceBuilder


__all__ = [
    # 模型
    "BoundValue", "DataEntry", "Component",
    "SurfaceUpdate", "DataModelUpdate", "BeginRendering", "DeleteSurface", "A2UIMessage",
    "UserAction", "ClientError", "ClientEvent",
    # 工厂
    "literal", "path_bind",
    "entry_string", "entry_int", "entry_number", "entry_boolean", "entry_map", "entry_list",
    "dict_to_entries",
    # 高层 API
    "A2UIBuilder",
    "A2UIEmitter", "a2ui_events",
    "SnapshotAggregator", "DELTA_THRESHOLD", "NOTIFICATION_SURFACE_ID",
    # Catalog
    "CatalogDefinition", "CatalogRegistry", "ComponentMeta", "ComponentMatcherV2",
    "STANDARD_V08", "VIKING_CRM_V1", "SCHEMA_MATCH_THRESHOLD",
    # Inbound
    "A2UIInboundHandler", "InboundDedupe", "parse_client_event",
    # Stream (Mode A)
    "a2ui_jsonl_stream", "a2ui_sse_stream",
    # Helper
    "A2UIRenderHelper", "SurfaceBuilder",
]
