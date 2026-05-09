"""A2UIProjector 单元测试

覆盖：
- ACTIVITY_SNAPSHOT 展开为 surfaceUpdate / dataModelUpdate / beginRendering / deleteSurface
- 双格式兼容：键名（官方）和 type 标识（CopilotKit 早期）
- 非 A2UI 事件（RUN_STARTED / TEXT_MESSAGE / STATE_SNAPSHOT 默认丢弃）
- include_state_as_data_model=True 时 STATE_SNAPSHOT 转 dataModelUpdate
- activity_type_filter 过滤非 "a2ui-surface" 的 activity
- 反序列化：valueList / valueArray 别名都能解析
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")

from src.a2ui import (
    A2UIProjector,
    BeginRendering,
    BoundValue,
    Component,
    DataModelUpdate,
    DeleteSurface,
    SurfaceUpdate,
    parse_a2ui_message,
)
from src.agui import models as agui


# ═══════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════

async def _collect(gen):
    out = []
    async for x in gen:
        out.append(x)
    return out


async def _as_stream(events):
    for e in events:
        yield e


# ═══════════════════════════════════════════════════════════
# 反序列化器
# ═══════════════════════════════════════════════════════════

def test_parse_surface_update_canonical():
    op = {"surfaceUpdate": {
        "surfaceId": "s1",
        "components": [
            {"id": "title", "component": {"Text": {"text": {"literalString": "Hi"}}}},
        ],
    }}
    msg = parse_a2ui_message(op)
    assert isinstance(msg, SurfaceUpdate)
    assert msg.surface_id == "s1"
    assert len(msg.components) == 1
    assert msg.components[0].type == "Text"
    assert msg.components[0].id == "title"


def test_parse_surface_update_type_format():
    op = {
        "type": "surfaceUpdate",
        "surfaceId": "s1",
        "components": [
            {"id": "x", "component": {"Row": {"children": {"explicitList": []}}}},
        ],
    }
    msg = parse_a2ui_message(op)
    assert isinstance(msg, SurfaceUpdate)
    assert msg.surface_id == "s1"


def test_parse_data_model_update_value_types():
    op = {"dataModelUpdate": {
        "surfaceId": "s1",
        "path": "user",
        "contents": [
            {"key": "name", "valueString": "Bob"},
            {"key": "age", "valueInt": 30},
            {"key": "score", "valueNumber": 3.14},
            {"key": "ok", "valueBoolean": True},
            {"key": "tags", "valueList": ["a", "b"]},
            {"key": "addr", "valueMap": [{"key": "city", "valueString": "Beijing"}]},
        ],
    }}
    msg = parse_a2ui_message(op)
    assert isinstance(msg, DataModelUpdate)
    assert msg.surface_id == "s1"
    assert msg.path == "user"
    keys = {e.key for e in msg.contents}
    assert keys == {"name", "age", "score", "ok", "tags", "addr"}
    # valueMap 嵌套
    addr = next(e for e in msg.contents if e.key == "addr")
    assert addr.value_map is not None
    assert addr.value_map[0].key == "city"


def test_parse_data_model_update_value_array_alias():
    op = {"dataModelUpdate": {
        "surfaceId": "s1",
        "contents": [{"key": "tags", "valueArray": [1, 2, 3]}],
    }}
    msg = parse_a2ui_message(op)
    assert isinstance(msg, DataModelUpdate)
    # valueArray 通过反序列化落到 value_list
    assert msg.contents[0].value_list == [1, 2, 3]


def test_parse_begin_rendering():
    op = {"beginRendering": {"surfaceId": "s1", "root": "root", "catalogId": "crm-v1"}}
    msg = parse_a2ui_message(op)
    assert isinstance(msg, BeginRendering)
    assert msg.surface_id == "s1"
    assert msg.root == "root"
    assert msg.catalog_id == "crm-v1"


def test_parse_delete_surface():
    op = {"deleteSurface": {"surfaceId": "ghost"}}
    msg = parse_a2ui_message(op)
    assert isinstance(msg, DeleteSurface)
    assert msg.surface_id == "ghost"


def test_parse_invalid_returns_none():
    assert parse_a2ui_message({"unknown": {}}) is None
    assert parse_a2ui_message({"surfaceUpdate": "not_a_dict"}) is None
    assert parse_a2ui_message({}) is None


# ═══════════════════════════════════════════════════════════
# A2UIProjector
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_projector_expands_activity_snapshot_operations():
    events = [
        agui.run_started("r1", "t1"),
        agui.activity_snapshot(
            message_id="a2ui-1",
            activity_type="a2ui-surface",
            content={"operations": [
                {"surfaceUpdate": {"surfaceId": "s1", "components": [
                    {"id": "title", "component": {"Text": {"text": {"literalString": "x"}}}},
                ]}},
                {"beginRendering": {"surfaceId": "s1", "root": "title"}},
            ]},
        ),
        agui.run_finished("r1", "t1"),
    ]
    projector = A2UIProjector()
    out = await _collect(projector.project(_as_stream(events)))
    # 非 activity 事件被丢弃；activity 里的 2 个 operations 被展开
    assert len(out) == 2
    assert isinstance(out[0], SurfaceUpdate)
    assert isinstance(out[1], BeginRendering)


@pytest.mark.asyncio
async def test_projector_filters_non_a2ui_activity_types():
    events = [
        agui.activity_snapshot(
            message_id="plan-1",
            activity_type="PLAN",   # 非 a2ui-surface
            content={"operations": [
                {"surfaceUpdate": {"surfaceId": "s1", "components": []}},
            ]},
        ),
    ]
    out = await _collect(A2UIProjector().project(_as_stream(events)))
    assert out == []


@pytest.mark.asyncio
async def test_projector_drops_text_and_reasoning_and_tool_events():
    events = [
        agui.text_message_start("m1"),
        agui.text_message_content("m1", "hi"),
        agui.text_message_end("m1"),
        agui.reasoning_start("r1"),
        agui.reasoning_message_start("r1m"),
        agui.reasoning_message_content("r1m", "think"),
        agui.reasoning_message_end("r1m"),
        agui.reasoning_end("r1"),
        agui.tool_call_start("tc1", tool_call_name="search"),
        agui.tool_call_args("tc1", "{}"),
        agui.tool_call_end("tc1"),
        agui.state_snapshot({"phase": "executing", "data": {}}),
        agui.state_delta([{"op": "add", "path": "/x", "value": 1}]),
        agui.messages_snapshot([]),
    ]
    out = await _collect(A2UIProjector().project(_as_stream(events)))
    assert out == []


@pytest.mark.asyncio
async def test_projector_include_state_as_data_model():
    events = [
        agui.state_snapshot({
            "phase": "executing",
            "data": {
                "customers_top": [{"id": "C1", "name": "工行"}],
                "pipeline": {"stages": []},
            },
            "panelSurfaceMap": {"customers_top": "panel-slot-1"},
        }),
    ]
    proj = A2UIProjector(include_state_as_data_model=True)
    out = await _collect(proj.project(_as_stream(events)))
    assert len(out) == 1
    dmu = out[0]
    assert isinstance(dmu, DataModelUpdate)
    assert dmu.path == "data"
    keys = {e.key for e in dmu.contents}
    assert keys == {"customers_top", "pipeline"}


@pytest.mark.asyncio
async def test_projector_custom_events_dropped():
    events = [
        agui.custom_event("component_loading", {"apikey": "x", "state": "loading"}),
        agui.custom_event("step_metadata", {"step_name": "s"}),
        agui.custom_event("a2ui.surfaceUpdate", {"surfaceId": "s1", "components": []}),
    ]
    out = await _collect(A2UIProjector().project(_as_stream(events)))
    # a2ui.* CUSTOM 不走这里（属于应用层自定义），默认丢弃
    # A2UI 操作的标准通道是 ACTIVITY_SNAPSHOT
    assert out == []


@pytest.mark.asyncio
async def test_projector_dual_format_in_operations():
    """ACTIVITY_SNAPSHOT.content.operations 里可以同时存在键名和 type 两种格式"""
    events = [
        agui.activity_snapshot(
            message_id="a2ui-1",
            activity_type="a2ui-surface",
            content={"operations": [
                {"surfaceUpdate": {"surfaceId": "s1", "components": []}},
                {"type": "beginRendering", "surfaceId": "s1", "root": "root"},
            ]},
        ),
    ]
    out = await _collect(A2UIProjector().project(_as_stream(events)))
    assert len(out) == 2
    assert isinstance(out[0], SurfaceUpdate)
    assert isinstance(out[1], BeginRendering)
