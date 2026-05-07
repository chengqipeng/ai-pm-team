"""AG-UI / A2UI REST + SSE 路由

由 server.py 通过 `app.include_router(a2ui_router)` 挂载。

路由清单：
  POST   /agent/a2ui/event                  客户端回传 userAction / error
  POST   /agent/a2ui/stream                 Mode A：原生 A2UI JSONL 流
  POST   /agent/chat/reconnect              断线重连首包 + tail 订阅
  GET    /.well-known/agent-card            A2A Agent Card（暴露 A2UI 扩展声明）

设计要点：
- 所有端点都无业务耦合；CatalogRegistry、AgentAdapter 通过依赖注入
- Mode A 返回 `application/x-ndjson`（NDJSON） 或 `text/event-stream`（SSE）
- /.well-known/agent-card 返回 JSON，配合 ai-native-app 的 a2uiClientCapabilities 协商
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.a2ui import (
    A2UIInboundHandler,
    CatalogRegistry,
    InboundDedupe,
    STANDARD_V08,
    VIKING_CRM_V1,
    UserAction,
    ClientError,
    a2ui_jsonl_stream,
    a2ui_sse_stream,
)
from src.a2ui.models import A2UIMessage

logger = logging.getLogger(__name__)


a2ui_router = APIRouter()


# ═══════════════════════════════════════════════════════════
# 模块级单例（进程生命周期内共享）
# ═══════════════════════════════════════════════════════════

_catalog_registry: CatalogRegistry | None = None
_inbound_handler: A2UIInboundHandler | None = None


def get_catalog_registry() -> CatalogRegistry:
    """懒加载 CatalogRegistry。

    可通过环境变量 `A2UI_CATALOG_DIR` 指定组件 JSON 目录；
    默认注册标准 v0.8 + Viking CRM 业务 catalog。
    """
    global _catalog_registry
    if _catalog_registry is None:
        reg = CatalogRegistry()
        reg.register_standard()
        crm_dir = os.environ.get("A2UI_CATALOG_DIR") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "resources", "a2ui", "components",
        )
        reg.load_from_dir(crm_dir, catalog_id=VIKING_CRM_V1)
        # 若本地 catalog 有组件则设为 default
        if reg.get(VIKING_CRM_V1) and reg.get(VIKING_CRM_V1).components:
            reg.set_default(VIKING_CRM_V1)
        _catalog_registry = reg
    return _catalog_registry


def get_inbound_handler() -> A2UIInboundHandler:
    global _inbound_handler
    if _inbound_handler is None:
        _inbound_handler = A2UIInboundHandler(
            dedupe=InboundDedupe(window_seconds=30.0, max_entries=1024),
        )
    return _inbound_handler


# ═══════════════════════════════════════════════════════════
# /.well-known/agent-card
# ═══════════════════════════════════════════════════════════

@a2ui_router.get("/.well-known/agent-card")
async def agent_card() -> JSONResponse:
    """A2A Agent Card — 暴露 A2UI v0.8 扩展声明。

    前端（CopilotKit / 纯 A2UI 客户端）拉取此接口了解支持的 catalog 列表。
    """
    reg = get_catalog_registry()
    return JSONResponse({
        "name": "DeepAgent CRM",
        "description": "CRM 2B Agent，支持 AG-UI 事件流 + A2UI v0.8 声明式 UI",
        "url": os.environ.get("AGENT_PUBLIC_URL", "http://localhost:8001"),
        "capabilities": {
            "streaming": True,
            "stateTransitionHistory": True,
            "extensions": [reg.advertise(accepts_inline=False)],
        },
    })


# ═══════════════════════════════════════════════════════════
# POST /agent/a2ui/event — 客户端入站事件
# ═══════════════════════════════════════════════════════════

class A2UIEventRequest(BaseModel):
    """客户端回传的 A2UI 事件。

    接受原始 A2UI v0.8 负载（`{"userAction": {...}}` 或 `{"error": {...}}`）。
    可选附带 `threadId` 以指示目标会话；若省略则由后续 handler 按
    `surfaceId` 查找。
    """
    thread_id: str | None = Field(default=None, alias="threadId")
    userAction: dict | None = None
    error: dict | None = None

    model_config = {"populate_by_name": True, "extra": "allow"}


@a2ui_router.post("/agent/a2ui/event", status_code=202)
async def a2ui_event(req: Request) -> JSONResponse:
    """接收客户端入站事件并调度到对应 Agent thread。

    处理流程：
    1. 解析 payload 为 UserAction / ClientError
    2. 短时去重（30s 窗口，`surfaceId+sourceComponentId+timestamp` 为指纹）
    3. UserAction → 合成 HumanMessage 注入 Agent（由 Adapter 处理）
    4. ClientError → 写 log + trace（可选上报）

    后端事件回流：处理产生的 AG-UI 事件仍在原 SSE 连接推送，不走本端点响应体。
    """
    try:
        payload = await req.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    thread_id = payload.pop("threadId", None) if isinstance(payload, dict) else None

    handler = get_inbound_handler()
    try:
        event = handler.handle(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if event is None:
        return JSONResponse({"status": "duplicate"}, status_code=202)

    if isinstance(event, UserAction):
        # 注入 Agent（实际调度由 adapter 侧完成；这里只做编排签约）
        _deliver_user_action(thread_id, event)
        return JSONResponse({
            "status": "accepted",
            "surfaceId": event.surface_id,
            "name": event.name,
        }, status_code=202)

    if isinstance(event, ClientError):
        logger.warning("[a2ui.error] surface=%s component=%s message=%s",
                       event.surface_id, event.component_id, event.message)
        return JSONResponse({"status": "logged"}, status_code=202)

    raise HTTPException(status_code=500, detail="Unknown handler outcome")


def _deliver_user_action(thread_id: str | None, ua: UserAction) -> None:
    """把 UserAction 注入 Agent thread。

    当前实现：把消息 append 到 thread 的 pending queue（由 Adapter 在下次 astream 时消费）。
    该桥接层为占位实现；实际接入方式取决于 agent_manager 的具体 API。
    """
    try:
        from src.agents.adapter import neo_agent_v2_adapter  # 延迟 import 避免循环
    except Exception:  # pragma: no cover
        logger.debug("adapter not available, UserAction only logged")
        neo_agent_v2_adapter = None

    msg = A2UIInboundHandler.to_human_message(ua)
    if neo_agent_v2_adapter is None:
        logger.info("[a2ui.userAction] thread=%s ua=%s msg=%s",
                    thread_id, ua.name, getattr(msg, "content", msg))
        return

    # 若 adapter 提供 inject_message API（设计 §7），调用之；否则 log 降级
    inject = getattr(neo_agent_v2_adapter, "inject_message", None)
    if callable(inject):
        try:
            inject(thread_id=thread_id, message=msg, source="a2ui")  # type: ignore[misc]
        except Exception:
            logger.exception("inject_message failed")
    else:
        logger.info("[a2ui.userAction] no inject_message; drop thread=%s name=%s",
                    thread_id, ua.name)


# ═══════════════════════════════════════════════════════════
# POST /agent/a2ui/stream — Mode A 原生 A2UI 流
# ═══════════════════════════════════════════════════════════

class A2UIStreamRequest(BaseModel):
    thread_id: str = Field(alias="threadId")
    message: str = ""
    a2uiClientCapabilities: dict | None = None
    run_id: str | None = Field(default=None, alias="runId")

    model_config = {"populate_by_name": True}


@a2ui_router.post("/agent/a2ui/stream")
async def a2ui_stream(req: A2UIStreamRequest, http: Request) -> StreamingResponse:
    """Mode A：独立的 A2UI JSONL/SSE 流。

    客户端通过 HTTP `Accept: application/x-ndjson` 或 `text/event-stream`
    协商输出格式。默认 NDJSON。
    """
    accept = http.headers.get("accept", "application/x-ndjson").lower()

    # Catalog 协商
    reg = get_catalog_registry()
    cap = req.a2uiClientCapabilities or {}
    negotiated = reg.negotiate(
        client_supported=cap.get("supportedCatalogIds") or [],
        client_inline=cap.get("inlineCatalogs") or [],
        accepts_inline=False,  # 生产默认关
    )
    logger.info("[a2ui.stream] thread=%s catalog=%s", req.thread_id, negotiated)

    async def messages_from_adapter() -> AsyncGenerator[A2UIMessage, None]:
        """占位 generator：

        生产实现需要调用 Adapter 的 execute_a2ui_only(thread_id, user_input)，
        抽取 ACTIVITY_SNAPSHOT.content.operations[] 并反序列化回 A2UI 消息。
        此处仅返回空流以便端点可用。
        """
        if False:  # pragma: no cover
            yield  # type: ignore[unreachable]
        return

    if "text/event-stream" in accept:
        generator = a2ui_sse_stream(messages_from_adapter())
        media_type = "text/event-stream"
    else:
        generator = a2ui_jsonl_stream(messages_from_adapter())
        media_type = "application/x-ndjson"

    return StreamingResponse(
        generator,
        media_type=media_type,
        headers={"X-A2UI-Catalog": negotiated},
    )


# ═══════════════════════════════════════════════════════════
# POST /agent/chat/reconnect — 断线重连
# ═══════════════════════════════════════════════════════════

class ChatReconnectRequest(BaseModel):
    thread_id: str = Field(alias="threadId")
    last_run_id: str | None = Field(default=None, alias="lastRunId")

    model_config = {"populate_by_name": True}


@a2ui_router.post("/agent/chat/reconnect")
async def chat_reconnect(req: ChatReconnectRequest) -> StreamingResponse:
    """断线重连首包 + tail 订阅（设计 §2.7 固定顺序）：

    1. RUN_STARTED(parent_run_id=last_run_id)
    2. MESSAGES_SNAPSHOT
    3. STATE_SNAPSHOT
    4. ACTIVITY_SNAPSHOT × N
    5. tail 恢复推送
    """
    import uuid
    from src.agui import AGUIConverter

    async def generator() -> AsyncGenerator[str, None]:
        run_id = uuid.uuid4().hex
        converter = AGUIConverter(
            run_id=run_id,
            thread_id=req.thread_id,
            parent_run_id=req.last_run_id,
        )

        # 首包快照（空骨架；生产实现需要从 checkpointer / aggregator 里拉真实状态）
        async for event in converter.emit_reconnect_snapshot(
            messages=[],           # TODO: 从 checkpointer 读取
            state_snapshot=None,   # TODO: 从 aggregator 读取
            activities=[],         # TODO: 从活跃 surfaces 读取
            parent_run_id=req.last_run_id,
        ):
            yield event.to_sse()

    return StreamingResponse(generator(), media_type="text/event-stream")
