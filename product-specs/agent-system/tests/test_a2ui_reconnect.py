"""A2UI 重连链路测试：ThreadStore + /agent/chat/reconnect

覆盖：
- ThreadStore.bind_aggregator + record_activity + snapshot_state
- RenderHelper 会自动登记到 default thread_store
- /agent/chat/reconnect 返回固定顺序首包（RUN_STARTED → MESSAGES → STATE → ACTIVITY×N）
- 空 thread 时首包只含 RUN_STARTED
"""
from __future__ import annotations

import json
import sys
import uuid

import pytest

sys.path.insert(0, ".")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.a2ui import (
    A2UIBuilder,
    A2UIRenderHelper,
    CatalogRegistry,
    Component,
    SnapshotAggregator,
    VIKING_CRM_V1,
    thread_store,
)
from src.a2ui.thread_store import reset_for_tests
from src.api.a2ui_routes import a2ui_router


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(a2ui_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_for_tests()
    yield
    reset_for_tests()


# ═══════════════════════════════════════════════════════════
# ThreadStore 基础
# ═══════════════════════════════════════════════════════════

def test_thread_store_ensure_and_bind():
    from src.a2ui import thread_store as store  # 重新 import 以拿到最新单例
    from src.a2ui import SnapshotAggregator

    st = store.ensure("t-1")
    assert st.thread_id == "t-1"
    assert st.aggregator is None

    agg = SnapshotAggregator(run_id="r-1", thread_id="t-1")
    store.bind_aggregator("t-1", agg)
    assert store.get("t-1").aggregator is agg


def test_thread_store_record_activity_and_snapshot():
    from src.a2ui import thread_store as store
    from src.a2ui import SnapshotAggregator

    agg = SnapshotAggregator(run_id="r-1", thread_id="t-1")
    store.bind_aggregator("t-1", agg)
    agg.add("customers", [{"id": "C1"}])

    store.record_activity("t-1", "customers", [
        {"surfaceUpdate": {"surfaceId": "panel-slot-1", "components": []}},
        {"beginRendering": {"surfaceId": "panel-slot-1", "root": "root"}},
    ])

    state = store.get("t-1")
    assert state.snapshot_state()["data"]["customers"] == [{"id": "C1"}]
    activities = state.active_activities()
    assert len(activities) == 1
    assert activities[0]["activity_type"] == "a2ui-surface"
    assert len(activities[0]["content"]["operations"]) == 2


# ═══════════════════════════════════════════════════════════
# RenderHelper 自动登记
# ═══════════════════════════════════════════════════════════

def test_render_helper_registers_into_default_thread_store():
    from src.a2ui import thread_store as store

    reg = CatalogRegistry()
    reg.register_standard()
    helper = A2UIRenderHelper(
        run_id=uuid.uuid4().hex,
        thread_id="t-helper-1",
        catalog_registry=reg,
    )

    def surface_fn(ui: A2UIBuilder, data_path: str) -> None:
        ui.column("root", children=[
            ui.text("title", literal="Hello"),
        ])

    helper.render("greeting", {"hello": "world"}, surface_fn=surface_fn)

    state = store.get("t-helper-1")
    assert state is not None
    assert state.aggregator is not None
    # 登记的 operations 来自这次 render
    activities = state.active_activities()
    assert len(activities) == 1
    op_keys = [list(op.keys())[0] for op in activities[0]["content"]["operations"]]
    assert "surfaceUpdate" in op_keys
    assert "beginRendering" in op_keys


# ═══════════════════════════════════════════════════════════
# /agent/chat/reconnect 端到端
# ═══════════════════════════════════════════════════════════

def _parse_sse_events(body: str) -> list[tuple[str, dict]]:
    """简单 SSE 解析：返回 [(event_name, data), ...]"""
    out = []
    frames = body.strip().split("\n\n")
    for frame in frames:
        name = None
        data = None
        for line in frame.splitlines():
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:"):].strip())
        if name is not None:
            out.append((name, data))
    return out


def test_reconnect_emits_full_sequence_from_thread_store(client: TestClient):
    # 1. 用 Helper 触发一次 render，填充 ThreadStore
    reg = CatalogRegistry()
    reg.register_standard()

    helper = A2UIRenderHelper(
        run_id="r-old",
        thread_id="t-reconnect-full",
        catalog_registry=reg,
    )

    def surface_fn(ui: A2UIBuilder, data_path: str) -> None:
        ui.column("root", children=[
            ui.text("title", literal="Q3"),
        ])

    helper.render("customers", [{"id": "C1"}], surface_fn=surface_fn)

    # 也登记一条历史消息（通常 adapter 会做）
    from src.a2ui import thread_store as store
    store.append_message("t-reconnect-full", {
        "role": "user", "content": "Top10",
    })

    # 2. 调 reconnect
    resp = client.post("/agent/chat/reconnect", json={
        "threadId": "t-reconnect-full",
    })
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    events = _parse_sse_events(resp.text)
    names = [n for n, _ in events]

    # 固定顺序
    assert names[0] == "RUN_STARTED"
    assert "MESSAGES_SNAPSHOT" in names
    assert "STATE_SNAPSHOT" in names
    assert "ACTIVITY_SNAPSHOT" in names
    assert names.index("MESSAGES_SNAPSHOT") < names.index("STATE_SNAPSHOT")
    assert names.index("STATE_SNAPSHOT") < names.index("ACTIVITY_SNAPSHOT")

    # parent_run_id 自动从 store 拿（上次 render 的 run_id）
    run_started = next(d for n, d in events if n == "RUN_STARTED")
    assert run_started["parent_run_id"] == "r-old"

    # STATE_SNAPSHOT 含业务数据
    state_evt = next(d for n, d in events if n == "STATE_SNAPSHOT")
    assert state_evt["snapshot"]["data"]["customers"] == [{"id": "C1"}]

    # ACTIVITY_SNAPSHOT 含 surfaceUpdate / beginRendering
    activity = next(d for n, d in events if n == "ACTIVITY_SNAPSHOT")
    op_keys = [list(op.keys())[0]
               for op in activity["content"]["operations"]]
    assert "surfaceUpdate" in op_keys
    assert "beginRendering" in op_keys


def test_reconnect_empty_thread_only_emits_run_started(client: TestClient):
    """对于一个未被使用过的 thread，reconnect 只会 yield RUN_STARTED。"""
    resp = client.post("/agent/chat/reconnect", json={
        "threadId": "t-never-used",
        "lastRunId": "r-old",
    })
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert [n for n, _ in events] == ["RUN_STARTED"]
    assert events[0][1]["parent_run_id"] == "r-old"


def test_reconnect_multiple_surfaces(client: TestClient):
    """多 render_type → 对应多条 ACTIVITY_SNAPSHOT。"""
    reg = CatalogRegistry()
    reg.register_standard()

    helper = A2UIRenderHelper(
        run_id=uuid.uuid4().hex,
        thread_id="t-multi",
        catalog_registry=reg,
    )

    def build(ui: A2UIBuilder, data_path: str) -> None:
        ui.column("root", children=[ui.text("t", literal="x")])

    helper.render("panel_a", {"v": 1}, surface_fn=build)
    helper.render("panel_b", {"v": 2}, surface_fn=build)

    resp = client.post("/agent/chat/reconnect", json={"threadId": "t-multi"})
    events = _parse_sse_events(resp.text)
    activity_count = sum(1 for n, _ in events if n == "ACTIVITY_SNAPSHOT")
    assert activity_count == 2
