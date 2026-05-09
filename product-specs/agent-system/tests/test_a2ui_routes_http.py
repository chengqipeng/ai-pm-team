"""A2UI REST + SSE 路由的 HTTP 层集成测试

直接用 FastAPI TestClient 打：
- GET  /.well-known/agent-card
- POST /agent/a2ui/event      （userAction / error / duplicate / invalid）
- POST /agent/a2ui/stream     （NDJSON / SSE 两种 Accept）
- POST /agent/chat/reconnect  （SSE）

不依赖真实 Agent Adapter — 通过 monkeypatch 替换 inject_message。
"""
from __future__ import annotations

import json
import sys

import pytest

# 关键：测试进程里不连真 DB / LLM，仅加载纯 A2UI 路由
sys.path.insert(0, ".")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.a2ui_routes import (
    a2ui_router,
    get_catalog_registry,
    get_inbound_handler,
)
from src.a2ui import STANDARD_V08


@pytest.fixture()
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(a2ui_router)
    return app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_catalog_and_dedupe():
    """每条测试重置单例状态，避免相互污染。"""
    import src.api.a2ui_routes as mod
    mod._catalog_registry = None
    mod._inbound_handler = None
    yield
    mod._catalog_registry = None
    mod._inbound_handler = None


# ═══════════════════════════════════════════════════════════
# /.well-known/agent-card
# ═══════════════════════════════════════════════════════════

def test_agent_card_returns_a2ui_extension(client: TestClient):
    resp = client.get("/.well-known/agent-card")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"]
    assert body["capabilities"]["streaming"] is True

    exts = body["capabilities"]["extensions"]
    a2ui_ext = next((e for e in exts if "a2ui" in e["uri"]), None)
    assert a2ui_ext is not None
    assert a2ui_ext["uri"].startswith("https://a2ui.org/a2a-extension/a2ui/")

    params = a2ui_ext["params"]
    assert STANDARD_V08 in params["supportedCatalogIds"]
    assert isinstance(params["acceptsInlineCatalogs"], bool)


# ═══════════════════════════════════════════════════════════
# /agent/a2ui/event — userAction
# ═══════════════════════════════════════════════════════════

def _user_action_payload(**overrides):
    base = {
        "threadId": "t-http-1",
        "userAction": {
            "name": "open_opportunity",
            "surfaceId": "panel-slot-1",
            "sourceComponentId": "detail_btn",
            "timestamp": "2026-05-07T10:00:00Z",
            "context": {"recordId": "C1"},
        },
    }
    if "threadId" in overrides:
        base["threadId"] = overrides.pop("threadId")
    if "userAction" in overrides:
        base["userAction"].update(overrides.pop("userAction"))
    return base


def test_a2ui_event_user_action_accepted(client: TestClient, monkeypatch):
    captured: dict = {}

    # 替换 adapter.inject_message，避免触碰真实 Agent
    def fake_inject(*, thread_id, message, source):
        captured["thread_id"] = thread_id
        captured["source"] = source
        captured["message"] = message

    # 由于 _deliver_user_action 内部 import adapter，我们 patch 其模块
    import src.api.a2ui_routes as mod

    class FakeAdapter:
        inject_message = staticmethod(fake_inject)

    # 替换延迟 import 的结果
    monkeypatch.setattr(mod, "_deliver_user_action", lambda tid, ua: fake_inject(
        thread_id=tid, message={"ua_name": ua.name, "ctx": ua.context}, source="a2ui",
    ))

    resp = client.post("/agent/a2ui/event", json=_user_action_payload())
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["name"] == "open_opportunity"

    assert captured["thread_id"] == "t-http-1"
    assert captured["source"] == "a2ui"
    assert captured["message"]["ua_name"] == "open_opportunity"


def test_a2ui_event_duplicate_returns_duplicate(client: TestClient, monkeypatch):
    import src.api.a2ui_routes as mod
    monkeypatch.setattr(mod, "_deliver_user_action", lambda tid, ua: None)

    payload = _user_action_payload()
    first = client.post("/agent/a2ui/event", json=payload)
    second = client.post("/agent/a2ui/event", json=payload)
    assert first.status_code == 202
    assert first.json()["status"] == "accepted"
    assert second.status_code == 202
    assert second.json()["status"] == "duplicate"


def test_a2ui_event_error_message(client: TestClient):
    resp = client.post("/agent/a2ui/event", json={
        "error": {
            "message": "binding not found",
            "componentId": "title",
            "surfaceId": "panel-slot-1",
        },
    })
    assert resp.status_code == 202
    assert resp.json()["status"] == "logged"


def test_a2ui_event_invalid_payload_returns_400(client: TestClient):
    resp = client.post("/agent/a2ui/event", json={"whatever": 1})
    assert resp.status_code == 400
    assert "Unknown A2UI client event" in resp.json()["detail"]


def test_a2ui_event_missing_required_field_returns_400(client: TestClient):
    resp = client.post("/agent/a2ui/event", json={
        "userAction": {"name": "click"}  # 缺 surfaceId 等
    })
    assert resp.status_code == 400
    assert "missing" in resp.json()["detail"].lower()


# ═══════════════════════════════════════════════════════════
# /agent/a2ui/stream — Mode A
# ═══════════════════════════════════════════════════════════

def test_a2ui_stream_ndjson_default(client: TestClient, monkeypatch):
    import src.agents.adapter as adapter_mod

    async def empty(*args, **kwargs):
        return
        yield  # type: ignore[unreachable]

    monkeypatch.setattr(adapter_mod.neo_agent_v2_adapter, "execute_a2ui",
                        empty, raising=False)
    resp = client.post("/agent/a2ui/stream", json={
        "threadId": "t-stream-1",
        "message": "hi",
        "a2uiClientCapabilities": {
            "supportedCatalogIds": [STANDARD_V08],
        },
    })
    assert resp.status_code == 200
    assert "application/x-ndjson" in resp.headers["content-type"]
    # 空流
    assert resp.text == ""
    assert resp.headers.get("X-A2UI-Catalog")


def test_a2ui_stream_sse_when_accept_header_set(client: TestClient, monkeypatch):
    import src.agents.adapter as adapter_mod

    async def empty(*args, **kwargs):
        return
        yield  # type: ignore[unreachable]

    monkeypatch.setattr(adapter_mod.neo_agent_v2_adapter, "execute_a2ui",
                        empty, raising=False)
    resp = client.post(
        "/agent/a2ui/stream",
        json={"threadId": "t-stream-2"},
        headers={"Accept": "text/event-stream"},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


def test_a2ui_stream_catalog_negotiation_header(client: TestClient, monkeypatch):
    import src.agents.adapter as adapter_mod

    async def empty(*args, **kwargs):
        return
        yield  # type: ignore[unreachable]

    monkeypatch.setattr(adapter_mod.neo_agent_v2_adapter, "execute_a2ui",
                        empty, raising=False)
    resp = client.post("/agent/a2ui/stream", json={
        "threadId": "t-stream-3",
        "a2uiClientCapabilities": {"supportedCatalogIds": ["urn:unknown"]},
    })
    assert resp.status_code == 200
    # 未命中任何 → 降级到 standard
    assert resp.headers["X-A2UI-Catalog"] == STANDARD_V08


def test_a2ui_stream_projects_real_a2ui_messages(client: TestClient, monkeypatch):
    """接入 Adapter 后：流里真正有 A2UI 消息。

    用 monkeypatch 把 adapter.execute_a2ui 替换为固定的假 generator，
    验证路由把消息正确序列化为 NDJSON。
    """
    import src.agents.adapter as adapter_mod
    from src.a2ui.models import BeginRendering, Component, SurfaceUpdate

    async def fake_execute_a2ui(thread_id, user_input, run_id=None, history=None,
                                *, include_state_as_data_model=False):
        yield SurfaceUpdate(surface_id="s1", components=[
            Component(id="root", type="Text", props={"text": {"literalString": "hi"}}),
        ])
        yield BeginRendering(surface_id="s1", root="root", catalog_id="crm-v1")

    monkeypatch.setattr(adapter_mod.neo_agent_v2_adapter, "execute_a2ui",
                        fake_execute_a2ui, raising=False)

    resp = client.post("/agent/a2ui/stream", json={
        "threadId": "t-stream-real",
        "message": "show me a card",
    })
    assert resp.status_code == 200
    lines = [line for line in resp.text.split("\n") if line.strip()]
    assert len(lines) == 2
    import json
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert "surfaceUpdate" in first
    assert "beginRendering" in second
    assert second["beginRendering"]["root"] == "root"


def test_a2ui_stream_sse_projects_events(client: TestClient, monkeypatch):
    import src.agents.adapter as adapter_mod
    from src.a2ui.models import BeginRendering, Component, SurfaceUpdate

    async def fake_execute_a2ui(thread_id, user_input, run_id=None, history=None,
                                *, include_state_as_data_model=False):
        yield SurfaceUpdate(surface_id="s1", components=[
            Component(id="root", type="Column",
                      props={"children": {"explicitList": []}}),
        ])
        yield BeginRendering(surface_id="s1", root="root")

    monkeypatch.setattr(adapter_mod.neo_agent_v2_adapter, "execute_a2ui",
                        fake_execute_a2ui, raising=False)

    resp = client.post(
        "/agent/a2ui/stream",
        json={"threadId": "t-stream-sse"},
        headers={"Accept": "text/event-stream"},
    )
    assert resp.status_code == 200
    body = resp.text
    # SSE 帧：每条消息 event: a2ui\ndata: ...\n\n
    assert body.count("event: a2ui") == 2
    assert "surfaceUpdate" in body
    assert "beginRendering" in body


# ═══════════════════════════════════════════════════════════
# /agent/chat/reconnect
# ═══════════════════════════════════════════════════════════

def test_chat_reconnect_emits_run_started(client: TestClient):
    resp = client.post("/agent/chat/reconnect", json={
        "threadId": "t-reconnect-1",
        "lastRunId": "r-old",
    })
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    body = resp.text
    # 固定首包顺序：RUN_STARTED 一定在
    assert "event: RUN_STARTED" in body
    # parent_run_id 回传
    assert "\"parent_run_id\": \"r-old\"" in body
    # 当前首包不含 MESSAGES_SNAPSHOT / STATE_SNAPSHOT（因为 checkpointer 未接入，
    # 只会 yield RUN_STARTED）。生产接入后 extend 该断言。


# ═══════════════════════════════════════════════════════════
# Trace 埋点（src.core.tracer）
# ═══════════════════════════════════════════════════════════

def test_a2ui_event_attaches_to_active_trace(client: TestClient, monkeypatch):
    from src.core.tracer import tracer
    # 先启动一个 trace
    trace = tracer.start_trace(thread_id="t-trace-1", user_input="test")

    # 替换 _deliver_user_action 为 no-op，避免触真 Adapter
    import src.api.a2ui_routes as mod
    monkeypatch.setattr(mod, "_deliver_user_action", lambda tid, ua: None)

    resp = client.post("/agent/a2ui/event", json={
        "threadId": "t-trace-1",
        "userAction": {
            "name": "click",
            "surfaceId": "s1",
            "sourceComponentId": "b1",
            "timestamp": "2026-05-07T11:00:00Z",
            "context": {},
        },
    })
    assert resp.status_code == 202

    # trace 里应出现一个 a2ui_inbound_event span
    t = tracer.get_trace(trace.trace_id)
    assert t is not None
    spans = [s for s in t.spans if s.name == "a2ui_inbound_event"]
    assert len(spans) == 1
    assert spans[0].metadata.get("outcome") == "accepted"
    assert spans[0].metadata.get("action") == "click"
    assert spans[0].status == "success"


def test_a2ui_event_invalid_records_error_span(client: TestClient):
    from src.core.tracer import tracer
    trace = tracer.start_trace(thread_id="t-trace-err", user_input="test")

    resp = client.post(
        "/agent/a2ui/event",
        json={"threadId": "t-trace-err", "whatever": 1},
    )
    assert resp.status_code == 400

    t = tracer.get_trace(trace.trace_id)
    spans = [s for s in t.spans if s.name == "a2ui_inbound_event"]
    assert len(spans) == 1
    assert spans[0].status == "error"
    assert spans[0].metadata.get("error")


# ═══════════════════════════════════════════════════════════
# /api/chat/agui — 统一 AG-UI 事件流对话端点
# ═══════════════════════════════════════════════════════════

def _parse_sse_events(body: str) -> list[tuple[str, dict]]:
    import json
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


def test_chat_agui_emits_run_lifecycle(client: TestClient, monkeypatch):
    """happy path：execute_agui 产出一串 AG-UI 事件，端点原样下发。"""
    import src.agents.adapter as adapter_mod
    from src.agui import (
        run_started, run_finished, text_message_start,
        text_message_content, text_message_end,
    )

    async def fake_execute_agui(thread_id, user_input, run_id=None, history=None):
        yield run_started(run_id or "r1", thread_id)
        yield text_message_start("m1")
        yield text_message_content("m1", "Hello ")
        yield text_message_content("m1", "world")
        yield text_message_end("m1")
        yield run_finished(run_id or "r1", thread_id)

    monkeypatch.setattr(adapter_mod.neo_agent_v2_adapter, "execute_agui",
                        fake_execute_agui, raising=False)

    resp = client.post("/api/chat/agui", json={
        "threadId": "t-agui-1",
        "message": "hi",
    })
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert resp.headers.get("X-A2UI-Catalog")

    events = _parse_sse_events(resp.text)
    names = [n for n, _ in events]
    assert names[0] == "RUN_STARTED"
    assert names[-1] == "RUN_FINISHED"
    assert "TEXT_MESSAGE_START" in names
    assert "TEXT_MESSAGE_CONTENT" in names
    assert "TEXT_MESSAGE_END" in names


def test_chat_agui_activity_snapshot_registers_thread_store(client: TestClient, monkeypatch):
    """当 execute_agui 产出带 render_type 的 ACTIVITY_SNAPSHOT，端点会登记到 ThreadStore。"""
    import src.agents.adapter as adapter_mod
    from src.a2ui.thread_store import reset_for_tests
    from src.a2ui import thread_store

    # 使用真实的 activity_snapshot 构造
    from src.agui import activity_snapshot, run_started, run_finished

    reset_for_tests()

    async def fake_execute_agui(thread_id, user_input, run_id=None, history=None):
        yield run_started(run_id or "r1", thread_id)
        yield activity_snapshot(
            message_id="a2ui-1",
            activity_type="a2ui-surface",
            content={
                "render_type": "orders",
                "operations": [
                    {"surfaceUpdate": {"surfaceId": "panel-slot-1", "components": []}},
                    {"beginRendering": {"surfaceId": "panel-slot-1", "root": "root"}},
                ],
            },
        )
        yield run_finished(run_id or "r1", thread_id)

    monkeypatch.setattr(adapter_mod.neo_agent_v2_adapter, "execute_agui",
                        fake_execute_agui, raising=False)

    resp = client.post("/api/chat/agui", json={
        "threadId": "t-agui-store",
        "message": "show orders",
    })
    assert resp.status_code == 200

    # 验证 ThreadStore 里已登记
    state = thread_store.get("t-agui-store")
    assert state is not None
    activities = state.active_activities()
    assert len(activities) == 1
    assert activities[0]["content"]["surface_id"]  # ensure_surface 已分配


def test_chat_agui_adapter_exception_emits_run_error(client: TestClient, monkeypatch):
    import src.agents.adapter as adapter_mod

    async def fake_execute_agui(*args, **kwargs):
        raise RuntimeError("boom")
        yield  # type: ignore[unreachable]

    monkeypatch.setattr(adapter_mod.neo_agent_v2_adapter, "execute_agui",
                        fake_execute_agui, raising=False)

    resp = client.post("/api/chat/agui", json={
        "threadId": "t-agui-err",
        "message": "hi",
    })
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    names = [n for n, _ in events]
    assert "RUN_ERROR" in names
    err_evt = next(d for n, d in events if n == "RUN_ERROR")
    assert err_evt["code"] == "RuntimeError"
