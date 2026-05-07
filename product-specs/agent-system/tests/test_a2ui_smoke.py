"""A2UI Phase 1+2 Smoke 测试

覆盖：
- models 序列化（BoundValue / DataEntry / 四种消息）
- Builder 流畅 API 产出三件套 JSONL
- Emitter 包成 AG-UI ACTIVITY_SNAPSHOT 与 CUSTOM 事件
- Aggregator 首次/后续 add 的事件序列 + delta 决策
- Converter 新增的 on_custom_event 分支
"""
from __future__ import annotations

import asyncio
import json

import pytest

from src.a2ui import (
    A2UIBuilder,
    A2UIEmitter,
    BeginRendering,
    BoundValue,
    Component,
    DataModelUpdate,
    DeleteSurface,
    SnapshotAggregator,
    SurfaceUpdate,
    a2ui_events,
    entry_string,
    literal,
    path_bind,
)
from src.agui import models as agui
from src.agui.converter import AGUIConverter


# ═══════════════════════════════════════════════════════════
# Phase 1: models
# ═══════════════════════════════════════════════════════════

def test_bound_value_literal_and_path():
    assert literal("hi").to_dict() == {"literalString": "hi"}
    assert literal(42).to_dict() == {"literalNumber": 42.0}
    assert literal(True).to_dict() == {"literalBoolean": True}
    assert literal([1, 2]).to_dict() == {"literalArray": [1, 2]}

    bv = path_bind("/user/name", default="Guest")
    d = bv.to_dict()
    assert d == {"path": "/user/name", "literalString": "Guest"}


def test_bound_value_must_have_at_least_one():
    with pytest.raises(ValueError):
        BoundValue().to_dict()


def test_component_serialization():
    c = Component(id="title", type="Text", props={"text": {"literalString": "hi"}})
    assert c.to_dict() == {
        "id": "title",
        "component": {"Text": {"text": {"literalString": "hi"}}},
    }


def test_surface_update_jsonl():
    su = SurfaceUpdate(surface_id="main", components=[
        Component(id="t", type="Text", props={"text": {"literalString": "x"}}),
    ])
    line = su.to_jsonl()
    # 可解析 + 符合 A2UI v0.8 顶层结构
    obj = json.loads(line)
    assert "surfaceUpdate" in obj
    assert obj["surfaceUpdate"]["surfaceId"] == "main"
    assert obj["surfaceUpdate"]["components"][0]["id"] == "t"


def test_begin_rendering_with_catalog():
    br = BeginRendering(surface_id="main", root="root", catalog_id="crm-v1")
    assert br.to_dict() == {
        "beginRendering": {"surfaceId": "main", "root": "root", "catalogId": "crm-v1"},
    }


def test_delete_surface():
    ds = DeleteSurface(surface_id="sidebar")
    assert ds.to_dict() == {"deleteSurface": {"surfaceId": "sidebar"}}


# ═══════════════════════════════════════════════════════════
# Phase 1: Builder
# ═══════════════════════════════════════════════════════════

def test_builder_simple_card():
    ui = A2UIBuilder(surface_id="profile", catalog_id="std")
    ui.column("root", children=[
        ui.text("name", literal="Bob", usage_hint="h1"),
        ui.text("bio", path="/user/bio"),
        ui.button("save", label="Save", action="save_profile",
                  context={"userId": path_bind("/user/id")}),
    ])
    ui.data({"user": {"id": 123, "bio": "Hello"}})
    su, du, br = ui.build()

    # SurfaceUpdate
    ids = [c.id for c in su.components]
    assert "root" in ids and "name" in ids and "save" in ids
    assert "save__label" in ids  # button 自动生成的 label 子组件

    # Column root 使用 explicitList
    root = next(c for c in su.components if c.id == "root")
    assert root.props["children"]["explicitList"] == ["name", "bio", "save"]

    # DataModelUpdate 含 user map
    assert du is not None
    assert du.surface_id == "profile"
    keys = [e.key for e in du.contents]
    assert "user" in keys

    # BeginRendering 指向 root
    assert br.root == "root"
    assert br.catalog_id == "std"


def test_builder_dynamic_list_template():
    ui = A2UIBuilder(surface_id="pipeline")
    ui.column("root", children=[ui.list_template("stages_list",
        data_binding="/pipeline/stages", template_id="stage_row")])
    # 独立注册一个模板组件（不在 root.children 内，但在 components 中）
    ui.add(Component(id="stage_row", type="Row", props={
        "children": {"explicitList": []},
    }))
    su, _, _ = ui.build()
    # list_template 的 props 中含 template
    lst = next(c for c in su.components if c.id == "stages_list")
    assert "template" in lst.props["children"]


def test_builder_requires_components():
    with pytest.raises(ValueError):
        A2UIBuilder(surface_id="empty").build()


def test_builder_duplicate_id_rejected():
    ui = A2UIBuilder(surface_id="x")
    ui.text("a", literal="1")
    with pytest.raises(ValueError):
        ui.text("a", literal="2")


# ═══════════════════════════════════════════════════════════
# Phase 1: Emitter
# ═══════════════════════════════════════════════════════════

def test_emitter_activity_mode():
    ui = A2UIBuilder(surface_id="s1")
    ui.text("t", literal="hi")
    messages = ui.messages()

    events = a2ui_events(messages, run_id="run-abc123", mode="activity")
    assert len(events) == 1
    ev = events[0]
    assert ev.type == agui.AGUIEventType.ACTIVITY_SNAPSHOT
    assert ev.data["activity_type"] == "a2ui-surface"
    assert ev.data["replace"] is True
    ops = ev.data["content"]["operations"]
    assert any("surfaceUpdate" in o for o in ops)
    assert any("beginRendering" in o for o in ops)


def test_emitter_custom_mode():
    ui = A2UIBuilder(surface_id="s1")
    ui.text("t", literal="hi")
    events = a2ui_events(ui.messages(), run_id="r1", mode="custom")
    names = [e.data["name"] for e in events]
    assert "a2ui.surfaceUpdate" in names
    assert "a2ui.beginRendering" in names
    # 每条 A2UI 消息 → 一条 CUSTOM 事件
    for ev in events:
        assert ev.type == agui.AGUIEventType.CUSTOM


def test_emitter_both_mode():
    ui = A2UIBuilder(surface_id="s1")
    ui.text("t", literal="hi")
    events = a2ui_events(ui.messages(), run_id="r1", mode="both")
    # both = 1 个 activity + N 个 custom
    types = [e.type for e in events]
    assert agui.AGUIEventType.ACTIVITY_SNAPSHOT in types
    assert agui.AGUIEventType.CUSTOM in types


# ═══════════════════════════════════════════════════════════
# Phase 2: Aggregator
# ═══════════════════════════════════════════════════════════

def test_aggregator_first_add_emits_notification_and_snapshot():
    agg = SnapshotAggregator(run_id="run-1", thread_id="t-1")
    events = agg.add("customers", [{"name": "工行"}])
    types = [e.type for e in events]
    # 首次添加：通知（ACTIVITY_SNAPSHOT）+ 状态（SNAPSHOT）
    assert agui.AGUIEventType.ACTIVITY_SNAPSHOT in types
    assert agui.AGUIEventType.STATE_SNAPSHOT in types

    snap = [e for e in events if e.type == agui.AGUIEventType.STATE_SNAPSHOT][0].data["snapshot"]
    # 业务数据分层到 data.<render_type>
    assert snap["data"]["customers"] == [{"name": "工行"}]
    assert snap["panelSurfaceMap"] == {"customers": "panel-slot-1"}
    assert snap["panelLayoutOrder"] == ["customers"]
    assert snap["phase"] == "executing"


def test_aggregator_subsequent_add_emits_delta_when_small():
    agg = SnapshotAggregator(run_id="run-2")
    agg.add("customers", [{"name": "工行"}])
    # 小修改：追加一个字段，理应走 STATE_DELTA
    events = agg.add("customers", [{"name": "工行"}, {"name": "农行"}])
    types = [e.type for e in events]
    # 无 ACTIVITY（非首次）；状态事件是 DELTA 或 SNAPSHOT 之一
    assert agui.AGUIEventType.ACTIVITY_SNAPSHOT not in types
    assert (agui.AGUIEventType.STATE_DELTA in types
            or agui.AGUIEventType.STATE_SNAPSHOT in types)


def test_aggregator_emit_ui_uses_panel_slot():
    agg = SnapshotAggregator(run_id="run-3")
    agg.add("pipeline", {"stages": []})  # 分配 panel-slot-1

    ui = A2UIBuilder(surface_id=agg.surface_id_for("pipeline") or "oops")
    ui.text("t", literal="Pipeline")
    events = agg.emit_ui("pipeline", ui.messages())
    assert len(events) == 1
    assert events[0].type == agui.AGUIEventType.ACTIVITY_SNAPSHOT


def test_aggregator_ensure_surface_allocates_for_unseen():
    agg = SnapshotAggregator(run_id="run-4")
    sid = agg.ensure_surface("new_panel")
    assert sid == "panel-slot-1"
    # 再次 ensure 返回同一 slot
    assert agg.ensure_surface("new_panel") == "panel-slot-1"


def test_aggregator_reset_clears_everything():
    agg = SnapshotAggregator(run_id="run-5")
    agg.add("a", 1)
    agg.add("b", 2)
    agg.reset()
    snap = agg.get_snapshot()
    assert snap["panelSurfaceMap"] == {}
    assert snap["panelLayoutOrder"] == []


# ═══════════════════════════════════════════════════════════
# Phase 2: AGUIConverter on_custom_event
# ═══════════════════════════════════════════════════════════

async def _collect(gen):
    out = []
    async for x in gen:
        out.append(x)
    return out


def test_converter_handles_agent_text_and_agent_data():
    conv = AGUIConverter(run_id="r-1", thread_id="t-1")

    async def stream():
        yield {"event": "on_custom_event", "name": "agent_text", "data": {"content": "hello "}}
        yield {"event": "on_custom_event", "name": "agent_text", "data": {"content": "world"}}
        yield {"event": "on_custom_event", "name": "agent_data", "data": {
            "data_key": "customers",
            "payload": {"data": [{"name": "工行"}]},
        }}

    events = asyncio.run(_collect(conv.convert(stream())))
    types = [e.type for e in events]
    # 文本三段式存在
    assert agui.AGUIEventType.TEXT_MESSAGE_START in types
    assert agui.AGUIEventType.TEXT_MESSAGE_CONTENT in types
    assert agui.AGUIEventType.TEXT_MESSAGE_END in types
    # 结构化数据通过 CUSTOM 下发
    customs = [e for e in events if e.type == agui.AGUIEventType.CUSTOM]
    assert any(c.data["name"] == "component_data" for c in customs)


def test_converter_handles_a2ui_namespace_custom():
    conv = AGUIConverter(run_id="r-2", thread_id="t-2")

    async def stream():
        yield {"event": "on_custom_event", "name": "a2ui.surfaceUpdate",
               "data": {"surfaceUpdate": {"surfaceId": "main", "components": []}}}

    events = asyncio.run(_collect(conv.convert(stream())))
    customs = [e for e in events if e.type == agui.AGUIEventType.CUSTOM]
    assert any(c.data["name"] == "a2ui.surfaceUpdate" for c in customs)


def test_converter_handles_state_patch():
    conv = AGUIConverter(run_id="r-3", thread_id="t-3")

    async def stream():
        yield {"event": "on_custom_event", "name": "state.patch", "data": {
            "patch": [{"op": "replace", "path": "/customers/0/status", "value": "done"}],
        }}

    events = asyncio.run(_collect(conv.convert(stream())))
    deltas = [e for e in events if e.type == agui.AGUIEventType.STATE_DELTA]
    assert len(deltas) == 1
    assert deltas[0].data["delta"][0]["path"] == "/customers/0/status"


# ═══════════════════════════════════════════════════════════
# Phase 3: DataEntry.valueList + 客户端入站消息
# ═══════════════════════════════════════════════════════════

def test_data_entry_value_list_is_canonical_name():
    from src.a2ui import entry_list
    e = entry_list("customers", [{"id": 1}, {"id": 2}])
    d = e.to_dict()
    # 规范字段名
    assert d["valueList"] == [{"id": 1}, {"id": 2}]
    # 同时产出兼容别名
    assert d["valueArray"] == [{"id": 1}, {"id": 2}]


def test_data_entry_accepts_value_array_alias():
    from src.a2ui import DataEntry
    e = DataEntry(key="x", value_array=[1, 2, 3])
    assert e.value_list == [1, 2, 3]
    d = e.to_dict()
    assert d["valueList"] == [1, 2, 3]


def test_parse_client_event_user_action():
    from src.a2ui import UserAction, parse_client_event
    payload = {
        "userAction": {
            "name": "open_opportunity",
            "surfaceId": "panel-slot-1",
            "sourceComponentId": "detail_btn",
            "timestamp": "2026-05-07T10:00:00Z",
            "context": {"recordId": "C1"},
        }
    }
    ev = parse_client_event(payload)
    assert isinstance(ev, UserAction)
    assert ev.name == "open_opportunity"
    assert ev.context == {"recordId": "C1"}


def test_parse_client_event_error():
    from src.a2ui import ClientError, parse_client_event
    ev = parse_client_event({"error": {"message": "bind not found", "componentId": "title"}})
    assert isinstance(ev, ClientError)
    assert ev.message == "bind not found"
    assert ev.component_id == "title"


def test_parse_client_event_unknown_raises():
    from src.a2ui import parse_client_event
    with pytest.raises(ValueError):
        parse_client_event({"whatever": {}})


def test_inbound_handler_dedupes():
    from src.a2ui import A2UIInboundHandler
    h = A2UIInboundHandler()
    payload = {"userAction": {
        "name": "click", "surfaceId": "s1", "sourceComponentId": "b1",
        "timestamp": "2026-05-07T10:00:00Z", "context": {},
    }}
    ev1 = h.handle(payload)
    ev2 = h.handle(payload)
    assert ev1 is not None
    assert ev2 is None  # 幂等命中


# ═══════════════════════════════════════════════════════════
# Phase 3: Catalog 协商 + ComponentMatcherV2
# ═══════════════════════════════════════════════════════════

def test_catalog_registry_negotiate_standard_default():
    from src.a2ui import CatalogRegistry, STANDARD_V08
    reg = CatalogRegistry()
    reg.register_standard()
    chosen = reg.negotiate(client_supported=[STANDARD_V08])
    assert chosen == STANDARD_V08


def test_catalog_registry_negotiate_custom_intersection():
    from src.a2ui import CatalogDefinition, CatalogRegistry, STANDARD_V08, VIKING_CRM_V1
    reg = CatalogRegistry()
    reg.register_standard()
    reg.register(CatalogDefinition(catalog_id=VIKING_CRM_V1))
    reg.set_default(VIKING_CRM_V1)
    chosen = reg.negotiate(client_supported=[STANDARD_V08, VIKING_CRM_V1])
    # default 优先
    assert chosen == VIKING_CRM_V1


def test_catalog_registry_negotiate_fallback_to_standard():
    from src.a2ui import CatalogRegistry, STANDARD_V08
    reg = CatalogRegistry()
    reg.register_standard()
    chosen = reg.negotiate(client_supported=["urn:unknown"])
    assert chosen == STANDARD_V08


def test_catalog_registry_advertise_shape():
    from src.a2ui import CatalogRegistry
    reg = CatalogRegistry()
    reg.register_standard()
    ad = reg.advertise()
    assert ad["uri"].startswith("https://a2ui.org/a2a-extension/a2ui/")
    assert "supportedCatalogIds" in ad["params"]
    assert isinstance(ad["params"]["acceptsInlineCatalogs"], bool)


def test_component_matcher_v2_bind_and_prefer():
    from src.a2ui import (
        CatalogDefinition, CatalogRegistry, ComponentMatcherV2, ComponentMeta,
        VIKING_CRM_V1,
    )
    reg = CatalogRegistry()
    cat = CatalogDefinition(catalog_id=VIKING_CRM_V1)
    cat.register(ComponentMeta(
        type="CrmRecordCard",
        skill_bindings={"bind": ["customer_detail"], "prefer": ["customer_list"]},
        supported_model_names=["component", "relevantData"],
    ))
    cat.register(ComponentMeta(
        type="PipelineTable",
        skill_bindings={"bind": ["pipeline_analysis"]},
    ))
    reg.register(cat)
    reg.set_default(VIKING_CRM_V1)

    matcher = ComponentMatcherV2(reg)
    matcher.warmup()

    assert matcher.resolve("customer_detail") == "CrmRecordCard"
    assert matcher.resolve("pipeline_analysis") == "PipelineTable"
    # prefer（多对一的首选）
    assert matcher.resolve("customer_list") == "CrmRecordCard"
    # model_name 匹配（唯一候选）
    assert matcher.resolve("unknown_skill", output_model_names=["relevantData"]) == "CrmRecordCard"


def test_component_matcher_v2_schema_matching():
    from src.a2ui import (
        CatalogDefinition, CatalogRegistry, ComponentMatcherV2, ComponentMeta,
        VIKING_CRM_V1,
    )
    # skill.output_schema: {properties: {name, amount, stage, customer}}
    # comp.input_schema:   {properties: {name, amount, stage}}
    reg = CatalogRegistry()
    cat = CatalogDefinition(catalog_id=VIKING_CRM_V1)
    cat.register(ComponentMeta(
        type="OpportunityCard",
        input_schema={"properties": {"name": {}, "amount": {}, "stage": {}}},
    ))
    reg.register(cat)
    reg.set_default(VIKING_CRM_V1)

    class FakeSkill:
        apikey = "opp_detail"
        output_schema = {"properties": {"name": {}, "amount": {}, "stage": {}, "customer": {}}}

    matcher = ComponentMatcherV2(reg)
    matcher.warmup(skills=[FakeSkill()])
    assert matcher.resolve("opp_detail") == "OpportunityCard"


# ═══════════════════════════════════════════════════════════
# Phase 3: Aggregator bind_a2ui_data + Shared State 分层
# ═══════════════════════════════════════════════════════════

def test_aggregator_bind_a2ui_data_returns_path():
    agg = SnapshotAggregator(run_id="run-bind")
    assert agg.bind_a2ui_data("customers_top") == "/data/customers_top"


def test_aggregator_snapshot_has_layered_data():
    agg = SnapshotAggregator(run_id="run-layer")
    agg.add("customers", [{"id": "C1"}])
    agg.add("pipeline", {"stages": []})
    snap = agg.get_snapshot()
    # 分层：data.* 下有业务数据；外层只有元数据
    assert set(snap.keys()) == {
        "phase", "data", "panelLayoutOrder", "panelAppearanceOrder",
        "notifications", "panelSurfaceMap",
    }
    assert set(snap["data"].keys()) == {"customers", "pipeline"}


# ═══════════════════════════════════════════════════════════
# Phase 3: Converter 推理新分层
# ═══════════════════════════════════════════════════════════

def test_converter_reasoning_new_layered_events():
    from dataclasses import dataclass

    @dataclass
    class Chunk:
        content: list
        tool_call_chunks: list = None

        def __post_init__(self):
            if self.tool_call_chunks is None:
                self.tool_call_chunks = []

    conv = AGUIConverter(run_id="r-think", thread_id="t-think",
                         emit_legacy_reasoning=False)  # 仅测试新事件

    async def stream():
        yield {"event": "on_chat_model_stream", "run_id": "root",
               "data": {"chunk": Chunk(content=[
                   {"type": "thinking", "thinking": "先找客户 C1 的合同 ..."},
               ])}}
        yield {"event": "on_chat_model_stream", "run_id": "root",
               "data": {"chunk": Chunk(content=[
                   {"type": "text", "text": "找到了："},
               ])}}

    events = asyncio.run(_collect(conv.convert(stream())))
    types = [e.type for e in events]
    # 新分层：REASONING_START → REASONING_MESSAGE_START → REASONING_MESSAGE_CONTENT
    #         → REASONING_MESSAGE_END → REASONING_END
    assert agui.AGUIEventType.REASONING_START in types
    assert agui.AGUIEventType.REASONING_MESSAGE_START in types
    assert agui.AGUIEventType.REASONING_MESSAGE_CONTENT in types
    assert agui.AGUIEventType.REASONING_MESSAGE_END in types
    assert agui.AGUIEventType.REASONING_END in types


def test_converter_tool_call_chunk_splits_args():
    from dataclasses import dataclass

    @dataclass
    class Chunk:
        content: str = ""
        tool_call_chunks: list = None

        def __post_init__(self):
            if self.tool_call_chunks is None:
                self.tool_call_chunks = []

    conv = AGUIConverter(run_id="r-tc", thread_id="t-tc")

    async def stream():
        # 首 chunk：带 name + 首段 args
        yield {"event": "on_chat_model_stream", "run_id": "root",
               "data": {"chunk": Chunk(tool_call_chunks=[
                   {"id": "tc1", "name": "list_customers", "args": "{\"quarter\":"},
               ])}}
        # 后续 chunk：只有 args delta
        yield {"event": "on_chat_model_stream", "run_id": "root",
               "data": {"chunk": Chunk(tool_call_chunks=[
                   {"id": "tc1", "name": None, "args": "\"Q3\"}"},
               ])}}

    events = asyncio.run(_collect(conv.convert(stream())))
    types = [e.type for e in events]
    assert agui.AGUIEventType.TOOL_CALL_START in types
    args_events = [e for e in events if e.type == agui.AGUIEventType.TOOL_CALL_ARGS]
    assert len(args_events) == 2


# ═══════════════════════════════════════════════════════════
# Phase 3: 断线重连首包顺序
# ═══════════════════════════════════════════════════════════

def test_converter_reconnect_snapshot_sequence():
    conv = AGUIConverter(run_id="r-new", thread_id="t-new")

    async def run():
        return [e async for e in conv.emit_reconnect_snapshot(
            messages=[{"role": "user", "content": "Q3 top10"}],
            state_snapshot={"phase": "idle", "data": {}},
            activities=[{
                "message_id": "a2ui-r-new",
                "activity_type": "a2ui-surface",
                "content": {"operations": []},
                "replace": True,
            }],
            parent_run_id="r-old",
        )]

    events = asyncio.run(run())
    types = [e.type for e in events]
    # 固定顺序
    assert types == [
        agui.AGUIEventType.RUN_STARTED,
        agui.AGUIEventType.MESSAGES_SNAPSHOT,
        agui.AGUIEventType.STATE_SNAPSHOT,
        agui.AGUIEventType.ACTIVITY_SNAPSHOT,
    ]
    assert events[0].data["parent_run_id"] == "r-old"


# ═══════════════════════════════════════════════════════════
# Phase 3: Renderer 吸收 skill_output + STEP_FINISHED 延迟透传
# ═══════════════════════════════════════════════════════════

def test_renderer_absorbs_skill_output_and_emits_state_delta():
    from src.agui import ComponentMatcher, ProgressiveRenderer

    matcher = ComponentMatcher({"my_skill": "MyComponent"})
    renderer = ProgressiveRenderer(matcher=matcher)

    async def upstream():
        # STEP_STARTED + step_metadata(started)
        yield agui.step_started("my_skill")
        yield agui.step_metadata("my_skill", skill_apikey="my_skill",
                                 step_index=0, phase="started")
        # skill_output 内部事件（应被 Renderer 吸收）
        yield agui.custom_event("skill_output",
                                {"skill_apikey": "my_skill",
                                 "data": {"result": 42}})
        # step_metadata(finished) + STEP_FINISHED
        yield agui.step_metadata("my_skill", skill_apikey="my_skill",
                                 step_index=0, status="completed",
                                 phase="finished")
        yield agui.step_finished("my_skill")

    events = asyncio.run(_collect(renderer.process(upstream())))
    types = [e.type for e in events]
    # skill_output 不透传
    for e in events:
        if e.type == agui.AGUIEventType.CUSTOM:
            assert e.data["name"] != "skill_output"
    # 出现过 component_loading → component_complete → STATE_DELTA → STEP_FINISHED
    names = [e.data.get("name") for e in events if e.type == agui.AGUIEventType.CUSTOM]
    assert "component_loading" in names
    assert "component_complete" in names
    # STEP_FINISHED 在 STATE_DELTA 之后
    idx_delta = next(i for i, t in enumerate(types) if t == agui.AGUIEventType.STATE_DELTA)
    idx_step_end = next(i for i, t in enumerate(types) if t == agui.AGUIEventType.STEP_FINISHED)
    assert idx_delta < idx_step_end
