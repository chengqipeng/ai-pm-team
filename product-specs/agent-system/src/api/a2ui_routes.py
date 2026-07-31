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
import inspect
import json
import logging
import os
import re
from typing import Any, AsyncGenerator, Literal

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
    action_dispatcher,
    stream_hub,
    ActionDispatchError,
    UnknownActionError,
)
from src.a2ui.models import A2UIMessage
from src.agui.protocol import OfficialRunAgentInput, encode_official_sse
from src.agui.run_registry import run_registry

# Trace 埋点（可选：若 tracer 不可用则降级为 no-op）
try:
    from src.core.tracer import tracer, SpanType
    _TRACE_ENABLED = True
except Exception:  # pragma: no cover
    tracer = None  # type: ignore
    SpanType = None  # type: ignore
    _TRACE_ENABLED = False

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
    # UserAction 必须明确归属 thread；先保留原有字段错误优先级。
    if isinstance(payload, dict) and isinstance(payload.get("userAction"), dict):
        body = payload["userAction"]
        required = ("name", "surfaceId", "sourceComponentId", "timestamp")
        if all(key in body for key in required) and not thread_id:
            raise HTTPException(status_code=400, detail="threadId is required for userAction")

    # Trace：把入站事件挂到该 thread 的活跃 trace 上
    trace = None
    span = None
    if _TRACE_ENABLED and thread_id:
        trace = tracer.get_active_trace(thread_id)
        if trace is not None:
            span = tracer.start_span(
                trace.trace_id, SpanType.REQUEST, "a2ui_inbound_event",
                input_data={"payload_keys": list(payload.keys())[:5]},
            )

    handler = get_inbound_handler()
    try:
        event = handler.handle(payload)
    except ValueError as exc:
        if span is not None:
            span.metadata["error"] = str(exc)
            span.finish("error")
        raise HTTPException(status_code=400, detail=str(exc))

    if event is None:
        if span is not None:
            span.metadata["outcome"] = "duplicate"
            span.finish("success")
        return JSONResponse({"status": "duplicate"}, status_code=202)

    if isinstance(event, UserAction):
        try:
            outcome = _deliver_user_action(str(thread_id), event)
            if inspect.isawaitable(outcome):
                outcome = await outcome
            result = outcome if isinstance(outcome, dict) else {"status": "accepted"}
        except UnknownActionError as exc:
            if span is not None:
                span.metadata["error"] = str(exc)
                span.finish("error")
            raise HTTPException(status_code=422, detail=str(exc))
        except ActionDispatchError as exc:
            if span is not None:
                span.metadata["error"] = str(exc)
                span.finish("error")
            raise HTTPException(status_code=400, detail=str(exc))
        if span is not None:
            span.metadata.update({
                "outcome": result.get("status", "accepted"),
                "action": event.name,
                "surface_id": event.surface_id,
                "action_id": result.get("actionId"),
            })
            span.finish("success")
        return JSONResponse({
            **result,
            "surfaceId": event.surface_id,
            "name": event.name,
        }, status_code=202)

    if isinstance(event, ClientError):
        logger.warning("[a2ui.error] surface=%s component=%s message=%s",
                       event.surface_id, event.component_id, event.message)
        if span is not None:
            span.metadata.update({
                "outcome": "client_error",
                "component_id": event.component_id,
                "surface_id": event.surface_id,
                "error": event.message,
            })
            span.finish("error")
        return JSONResponse({"status": "logged"}, status_code=202)

    if span is not None:
        span.metadata["error"] = "unknown outcome"
        span.finish("error")
    raise HTTPException(status_code=500, detail="Unknown handler outcome")


async def _deliver_user_action(thread_id: str, ua: UserAction) -> dict[str, str]:
    """经白名单 ActionDispatcher 即时发布活动并启动处理。"""
    return await action_dispatcher.dispatch(thread_id, ua)


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

    # 选择消息源：真实 Adapter（有 execute_a2ui 即视为就绪）或空流兜底
    async def messages_from_adapter() -> AsyncGenerator[A2UIMessage, None]:
        try:
            from src.agents.adapter import neo_agent_v2_adapter
        except Exception:  # pragma: no cover
            logger.warning("Adapter unavailable; returning empty A2UI stream")
            return
        if not hasattr(neo_agent_v2_adapter, "execute_a2ui"):
            logger.warning("Adapter missing execute_a2ui; returning empty A2UI stream")
            return
        try:
            async for msg in neo_agent_v2_adapter.execute_a2ui(
                thread_id=req.thread_id,
                user_input=req.message or "",
                run_id=req.run_id,
            ):
                yield msg
        except Exception:
            # Adapter 初始化 / 运行期异常不应让整个 SSE 连接崩溃；
            # 打 log 后平静结束流，客户端按"Agent 暂不可用"处理
            logger.exception("execute_a2ui failed; closing A2UI stream gracefully")
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
# GET /api/chat/agui/tail — 页面操作及后台事件持续订阅
# ═══════════════════════════════════════════════════════════

@a2ui_router.get("/api/chat/agui/tail")
async def chat_agui_tail(request: Request, threadId: str,
                         lastEventId: int | None = None) -> StreamingResponse:
    """订阅 thread 广播流；支持 Last-Event-ID 有限重放与心跳。"""
    if not threadId.strip():
        raise HTTPException(status_code=400, detail="threadId is required")
    after_sequence = lastEventId
    header_event_id = request.headers.get("last-event-id")
    if header_event_id is not None:
        try:
            after_sequence = int(header_event_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid Last-Event-ID") from exc

    async def generator() -> AsyncGenerator[str, None]:
        subscription = await stream_hub.subscribe(
            threadId, after_sequence=after_sequence)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(
                        subscription.queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                yield item.event.to_sse(item.sequence)
        finally:
            await stream_hub.unsubscribe(subscription)

    return StreamingResponse(
        generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ═══════════════════════════════════════════════════════════
# POST /agent/chat/reconnect — 断线重连
# ═══════════════════════════════════════════════════════════

class ChatReconnectRequest(BaseModel):
    thread_id: str = Field(alias="threadId")
    last_run_id: str | None = Field(default=None, alias="lastRunId")

    model_config = {"populate_by_name": True}


class ChatBusinessContext(BaseModel):
    """客户端声明、服务端按租户验证后才可进入 Agent 的业务上下文。"""
    intent: Literal["customer_insight"]
    entity_api_key: Literal["account"] = Field(alias="entityApiKey")
    record_api_key: str = Field(
        alias="recordApiKey", min_length=1, max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$",
    )

    model_config = {"populate_by_name": True, "extra": "forbid"}


class ChatAguiRequest(BaseModel):
    """`/api/chat/agui` 请求体。

    与老 `/api/chat` 相比：
    - 输出统一 AG-UI 事件流（RUN_STARTED/TEXT_MESSAGE_*/TOOL_CALL_*/...）
    - A2UI 消息嵌入在 ACTIVITY_SNAPSHOT 里
    - Catalog 协商通过 `a2uiClientCapabilities`
    """
    thread_id: str = Field(alias="threadId")
    message: str = ""
    # history 字段已废弃：对话历史从后端 ai_message 表加载，不再依赖前端传递
    history: list[dict[str, str]] = Field(default_factory=list, deprecated=True)
    run_id: str | None = Field(default=None, alias="runId")
    # resume 字段：中断恢复时传递用户响应（interrupt_id + value）
    resume: dict | None = None
    business_context: ChatBusinessContext | None = Field(
        default=None, alias="businessContext")
    a2uiClientCapabilities: dict | None = None

    model_config = {"populate_by_name": True, "extra": "forbid"}


@a2ui_router.post("/agent/chat/reconnect")
async def chat_reconnect(req: ChatReconnectRequest) -> StreamingResponse:
    """断线重连首包 + tail 订阅（设计 §2.7 固定顺序）：

    1. RUN_STARTED(parent_run_id=last_run_id)
    2. MESSAGES_SNAPSHOT
    3. STATE_SNAPSHOT
    4. ACTIVITY_SNAPSHOT × N
    5. tail 恢复推送

    数据来源：
    - MESSAGES_SNAPSHOT: ThreadState.messages（仅近期可序列化版；深度历史请走 checkpointer）
    - STATE_SNAPSHOT:    ThreadState.aggregator.get_snapshot()
    - ACTIVITY_SNAPSHOT: ThreadState.surface_operations（最近一次 render 的 operations）
    """
    import uuid
    from src.agui import AGUIConverter
    from src.a2ui import thread_store

    # The folded snapshot and sequence are captured under StreamHub's publish
    # lock, eliminating the snapshot-to-tail race window.
    bundle, replay_after = stream_hub.snapshot_with_boundary(
        req.thread_id,
        lambda: thread_store.snapshot_bundle(req.thread_id),
    )

    async def generator() -> AsyncGenerator[str, None]:
        run_id = uuid.uuid4().hex
        parent_run_id = req.last_run_id

        messages = bundle["messages"] if bundle else []
        state_snapshot = bundle["state"] if bundle else None
        activities = bundle["activities"] if bundle else []
        if bundle and bundle["last_run_id"] and parent_run_id is None:
            parent_run_id = bundle["last_run_id"]

        converter = AGUIConverter(
            run_id=run_id,
            thread_id=req.thread_id,
            parent_run_id=parent_run_id,
        )

        async for event in converter.emit_reconnect_snapshot(
            messages=messages,
            state_snapshot=state_snapshot,
            activities=activities,
            parent_run_id=parent_run_id,
        ):
            yield event.to_sse()

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-AGUI-Replay-After": str(replay_after),
        },
    )


# ═══════════════════════════════════════════════════════════
# POST /api/chat/agui — 统一 AG-UI 事件流对话端点
# ═══════════════════════════════════════════════════════════

def _is_failed_insight_content(content: str) -> bool:
    """识别被 Skill 包装成文档流的明确客户洞察失败结果。"""
    text = " ".join(str(content or "").split())
    if not text:
        return False
    missing = bool(re.search(
        r"(?:客户\s*(?:ID|记录标识)|CRM\s*(?:记录|系统)|recordApiKey)"
        r".{0,160}(?:没有找到|未找到|不存在|not\s+found)",
        text, re.IGNORECASE,
    ))
    explicit_failure = bool(re.search(
        r"客户洞察.{0,40}(?:生成|执行|保存)?.{0,20}失败|"
        r"(?:生成|执行)客户洞察.{0,20}失败",
        text, re.IGNORECASE,
    ))
    redacted_missing = (
        "<PII:CN_BANK_CARD_" in text
        and bool(re.search(r"没有找到|未找到|不存在|not\s+found", text, re.IGNORECASE))
    )
    return missing or explicit_failure or redacted_missing


def _standard_message_text(req: OfficialRunAgentInput) -> str:
    """Extract the newest user text while keeping server-side history canonical."""
    for message in reversed(req.messages):
        if getattr(message, "role", "") != "user":
            continue
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content
        parts: list[str] = []
        for item in content or []:
            text = getattr(item, "text", None)
            if text:
                parts.append(str(text))
        return "\n".join(parts)
    return ""


def _standard_resume_value(req: OfficialRunAgentInput) -> Any | None:
    if not req.resume:
        return None
    payloads = [entry.payload for entry in req.resume]
    return payloads[0] if len(payloads) == 1 else payloads


@a2ui_router.post("/api/chat/agui")
async def chat_agui(req: ChatAguiRequest, http: Request) -> StreamingResponse:
    """Legacy CRM endpoint; its existing snake_case SSE contract is preserved."""
    return await _chat_agui_response(req, http)


@a2ui_router.post("/api/chat/agui/run")
async def chat_agui_run(
    req: OfficialRunAgentInput,
    http: Request,
) -> StreamingResponse:
    """Official RunAgentInput + BaseEvent/EventEncoder compatibility endpoint."""
    forwarded = req.forwarded_props if isinstance(req.forwarded_props, dict) else {}
    message = _standard_message_text(req)
    resume = _standard_resume_value(req)
    if not message.strip() and resume is None:
        raise HTTPException(
            status_code=422,
            detail="RunAgentInput requires a user text message or resume entries",
        )

    legacy_req = ChatAguiRequest.model_validate({
        "threadId": req.thread_id,
        "runId": req.run_id,
        "message": message,
        "resume": resume,
        "businessContext": forwarded.get("businessContext"),
        "a2uiClientCapabilities": forwarded.get("a2uiClientCapabilities"),
    })
    protocol_metadata = {
        "ag_ui_input": {
            "state": req.state,
            "tools": [tool.model_dump(by_alias=True) for tool in req.tools],
            "context": [item.model_dump(by_alias=True) for item in req.context],
            "forwardedProps": req.forwarded_props,
        }
    }
    return await _chat_agui_response(
        legacy_req,
        http,
        standard_wire=True,
        parent_run_id=req.parent_run_id,
        protocol_metadata=protocol_metadata,
    )


async def _chat_agui_response(
    req: ChatAguiRequest,
    http: Request,
    *,
    standard_wire: bool = False,
    parent_run_id: str | None = None,
    protocol_metadata: dict[str, Any] | None = None,
) -> StreamingResponse:
    """Execute one chat run and select either legacy or official wire encoding.

    The execution, CRM visibility, document persistence and trace behavior stay
    shared, so adding protocol compatibility cannot fork business semantics.
    """
    import uuid as _uuid
    import time as _time
    from src.a2ui import thread_store

    _req_start = _time.time()
    run_id = req.run_id or _uuid.uuid4().hex
    logger.info(
        "[AG-UI] 收到请求: thread=%s, run=%s, message=%s",
        req.thread_id, run_id,
        repr(req.message[:100]) if req.message else "(empty)",
    )

    # 业务标识不能由客户端直接声明为 PII 例外。先按当前租户验证记录存在，
    # 再构建仅在本次 Agent run 生效的可信字面量保护列表。
    input_metadata: dict[str, Any] = dict(protocol_metadata or {})
    validated_context: dict[str, Any] | None = None
    if req.business_context is not None:
        from src.core.context import get_context
        from src.store.business_record_dao import BusinessRecordDAO

        current = get_context()
        business = req.business_context
        record = await asyncio.to_thread(
            BusinessRecordDAO.get,
            int(current.tenant_id),
            business.entity_api_key,
            business.record_api_key,
        )
        if record is None:
            raise HTTPException(
                status_code=404, detail="CRM 中未找到该客户记录，无法生成客户洞察")
        validated_context = {
            "intent": business.intent,
            "entityApiKey": business.entity_api_key,
            "recordApiKey": business.record_api_key,
        }
        input_metadata.update({
            "protected_literals": [business.record_api_key],
            "business_context": validated_context,
        })

    # 1. Catalog 协商
    reg = get_catalog_registry()
    cap = req.a2uiClientCapabilities or {}
    catalog_id = reg.negotiate(
        client_supported=cap.get("supportedCatalogIds") or [],
        client_inline=cap.get("inlineCatalogs") or [],
        accepts_inline=False,
    )

    # Standard endpoint: one active run per thread and no duplicate runId
    # execution. Legacy behavior is intentionally unchanged during migration.
    lease_acquired = False
    if standard_wire:
        admission = run_registry.start(req.thread_id, run_id)
        if admission == "duplicate":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "DUPLICATE_RUN_ID",
                    "message": "runId was already accepted; reconnect to the thread tail",
                    "threadId": req.thread_id,
                    "runId": run_id,
                },
            )
        if admission == "conflict":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "THREAD_RUN_IN_PROGRESS",
                    "message": "another run is active for this thread",
                    "threadId": req.thread_id,
                    "runId": run_id,
                },
            )
        lease_acquired = True

    # 2. Trace start
    trace = None
    if _TRACE_ENABLED:
        try:
            trace = tracer.start_trace(
                thread_id=req.thread_id,
                user_input=req.message,
                agent_name="CRM-Agent",
            )
            # 写入 ai_trace 表（status=running），确保 read_trace_detail 能查到记录
            from src.store.trace_writer import TraceWriter
            from src.core.context import DEFAULT_TENANT_ID
            _tw_start = TraceWriter(tenant_id=DEFAULT_TENANT_ID)
            _tw_start.on_trace_start(trace)
        except Exception:
            logger.exception("tracer.start_trace failed")

    # 3. 记录本次消息入 ThreadStore（稳定 ID 保证 runId 重试不重复写入）
    if req.message:
        thread_store.upsert_message(req.thread_id, {
            "id": f"chat-{run_id}-user",
            "role": "user",
            "content": req.message,
            "createdAt": int(_time.time() * 1000),
        })

    thread_store.set_last_run(req.thread_id, run_id)
    from src.a2ui.thread_store import infer_user_requested_views
    requested_view_patterns, origin_intent = infer_user_requested_views(
        req.message or "", validated_context)
    user_view_scope_id = f"run:{run_id}"

    async def generator() -> AsyncGenerator[str, None]:
        nonlocal trace
        from src.agents.adapter import neo_agent_v2_adapter
        from src.core.context import RequestContext, get_context, set_context

        # StreamingResponse 会在独立异步任务中消费 generator；必须在该任务内
        # 注入 thread_id，深层 CRM Tool 才能把页面状态广播回正确的 AG-UI tail。
        current_ctx = get_context()
        set_context(RequestContext(
            tenant_id=current_ctx.tenant_id,
            user_id=current_ctx.user_id,
            thread_id=req.thread_id,
            agent_name=current_ctx.agent_name,
            extend_params=dict(current_ctx.extend_params),
        ))
        thread_store.begin_user_view_scope(
            req.thread_id,
            user_view_scope_id,
            requested_view_patterns,
            origin_intent,
        )

        _event_count = 0
        _text_chars = 0
        _full_content = ""  # 累积普通文本回复
        _document_content = ""  # 文档内容在明确成功终态前仅作为 provisional 数据
        _document_title = ""
        _document_completed = False
        _document_failed = False
        _run_failed = False
        _doc_stream_active = False  # 一旦 doc_stream 开始，抑制 TEXT_MESSAGE 事件转发
        _tool_calls = []
        _tool_args_buffer = {}  # tool_call_id → accumulated args string

        try:
            execute_kwargs: dict[str, Any] = {
                "thread_id": req.thread_id,
                "user_input": req.message or "",
                "run_id": run_id,
            }
            if standard_wire:
                execute_kwargs.update({
                    "parent_run_id": parent_run_id,
                    "emit_legacy_reasoning": False,
                })
            if req.resume is not None:
                execute_kwargs["resume"] = req.resume
            if input_metadata:
                execute_kwargs["input_metadata"] = input_metadata
            async for event in neo_agent_v2_adapter.execute_agui(**execute_kwargs):
                _event_count += 1
                # 详细事件日志
                t_val = getattr(event.type, "value", event.type)
                if t_val == "TEXT_MESSAGE_CONTENT":
                    # doc_stream 开始后抑制 TEXT_MESSAGE（避免重复输出）
                    if _doc_stream_active or _document_completed:
                        continue
                    delta = event.data.get("delta", "")
                    _text_chars += len(delta)
                    _full_content += delta
                elif t_val in ("TEXT_MESSAGE_START", "TEXT_MESSAGE_END"):
                    if _doc_stream_active or _document_completed:
                        continue
                elif t_val == "TOOL_CALL_START":
                    tool_name = event.data.get("tool_call_name") or event.data.get("name", "")
                    tool_call_id = event.data.get("tool_call_id", "")
                    _tool_calls.append(tool_name)
                    _tool_args_buffer[tool_call_id] = ""
                    logger.info("[AG-UI] [thread=%s] TOOL_CALL_START: %s (id=%s)", req.thread_id, tool_name, tool_call_id[:12])
                elif t_val == "TOOL_CALL_ARGS":
                    tool_call_id = event.data.get("tool_call_id", "")
                    delta = event.data.get("delta", "")
                    if tool_call_id in _tool_args_buffer:
                        _tool_args_buffer[tool_call_id] += delta
                elif t_val == "TOOL_CALL_END":
                    tool_call_id = event.data.get("tool_call_id", "")
                    args_str = _tool_args_buffer.pop(tool_call_id, "")
                    if args_str:
                        # 截断过长参数（保留前 500 字符）
                        args_preview = args_str[:500] + ("..." if len(args_str) > 500 else "")
                        logger.info("[AG-UI] [thread=%s] TOOL_CALL_END: id=%s, args=%s", req.thread_id, tool_call_id[:12], args_preview)
                elif t_val == "TOOL_CALL_RESULT":
                    tool_call_id = event.data.get("tool_call_id", "")
                    content = event.data.get("content", "")
                    # 截断过长结果（保留前 800 字符）
                    result_preview = content[:800] + ("..." if len(content) > 800 else "")
                    logger.info("[AG-UI] [thread=%s] TOOL_CALL_RESULT: id=%s, len=%d, content=%s", req.thread_id, tool_call_id[:12], len(content), result_preview)
                elif t_val == "RUN_FINISHED":
                    elapsed = _time.time() - _req_start
                    logger.info(
                        "[AG-UI] [thread=%s] RUN_FINISHED: events=%d, text_chars=%d, tool_calls=%s, elapsed=%.1fs",
                        req.thread_id, _event_count, _text_chars, _tool_calls, elapsed,
                    )
                elif t_val == "RUN_ERROR":
                    _run_failed = True
                    _document_failed = True
                    _document_completed = False
                    logger.error("[AG-UI] [thread=%s] RUN_ERROR: %s", req.thread_id, event.data)
                    # 记录错误到 trace 链路
                    if trace is not None:
                        try:
                            _error_msg = event.data.get("message", "INTERNAL_ERROR")
                            _error_code = event.data.get("code", "")
                            tracer.finish_trace(
                                trace.trace_id, "error",
                                f"RUN_ERROR: {_error_msg} ({_error_code})" if _error_code else f"RUN_ERROR: {_error_msg}",
                            )
                            from src.store.trace_writer import TraceWriter
                            from src.core.context import DEFAULT_TENANT_ID
                            _tw_err = TraceWriter(tenant_id=DEFAULT_TENANT_ID)
                            trace_final_err = tracer.get_trace(trace.trace_id)
                            if trace_final_err:
                                _tw_err.on_trace_finish(trace_final_err)
                            trace = None  # 标记已处理，避免后续重复 finish
                        except Exception as _te:
                            logger.warning("AG-UI trace error persist failed: %s", _te)
                elif t_val == "CUSTOM":
                    name = event.data.get("name", "")
                    raw_value = event.data.get("value")
                    value = raw_value if isinstance(raw_value, dict) else {}
                    if name == "doc_stream":
                        _doc_stream_active = True
                        delta = value.get("delta", "")
                        if isinstance(delta, str) and not _run_failed:
                            _document_content += delta
                    elif name == "doc_stream_end":
                        status = str(value.get("status") or "complete").lower()
                        _document_failed = (
                            status in {"failed", "error", "cancelled"}
                            or _is_failed_insight_content(_document_content)
                        )
                        _document_completed = bool(
                            _document_content and not _document_failed and not _run_failed)
                        logger.info(
                            "[AG-UI] [thread=%s] doc_stream_end status=%s committed=%s",
                            req.thread_id, status, _document_completed)
                    elif name == "component_complete":
                        apikey = value.get("apikey", "")
                        if apikey == "doc_card":
                            component_data = value.get("data") or {}
                            content = component_data.get("content", "")
                            status = str(
                                value.get("status") or component_data.get("status")
                                or "complete").lower()
                            if isinstance(content, str) and content:
                                _document_content = content
                                _document_title = str(component_data.get("title") or "")
                            _document_failed = (
                                status in {"failed", "error", "cancelled"}
                                or _is_failed_insight_content(_document_content)
                            )
                            _document_completed = bool(
                                _document_content and not _document_failed and not _run_failed)
                        logger.info(
                            "[AG-UI] [thread=%s] component_complete: %s committed=%s",
                            req.thread_id, apikey, _document_completed)
                    elif name == "mw_span":
                        span_val = event.data.get("value") or {}
                        span_type = span_val.get("type", "")
                        span_name = span_val.get("step_name", span_val.get("name", ""))
                        if span_type in ("skill_execution", "llm_call", "content_review", "query_rewrite", "memory_retrieval"):
                            logger.info("[AG-UI] [thread=%s] %s: %s", req.thread_id, span_type, span_val.get("detail", span_name))

                # 所有事件进入统一广播序列；ACTIVITY 由 StreamHub 原位写入 ThreadStore。
                published = await stream_hub.publish(req.thread_id, event)
                encoded = (
                    encode_official_sse(event, published.sequence)
                    if standard_wire else event.to_sse(published.sequence)
                )
                if encoded:
                    yield encoded

            # 流正常结束：文档只有收到明确成功终态才提交；失败内容仅作为普通错误消息。
            document_success = bool(
                _document_content and _document_completed
                and not _document_failed and not _run_failed)
            if _document_failed:
                final_content = _document_content or _full_content
                content_type = "error"
                final_status = "failed"
            elif document_success:
                final_content = _document_content
                content_type = "document"
                final_status = "succeeded"
            else:
                final_content = _full_content
                content_type = "text"
                final_status = "succeeded" if not _run_failed else "failed"

            if final_content:
                thread_store.upsert_message(req.thread_id, {
                    "id": f"chat-{run_id}-assistant",
                    "role": "assistant", "content": final_content,
                    "createdAt": int(_time.time() * 1000),
                    "metadata": {
                        "contentType": content_type,
                        "title": _document_title if document_success else "",
                        "status": final_status,
                    },
                })

            # 持久化会话到 ai_conversation；trace 不可用时仍保留 ThreadStore 快照。
            if trace is not None:
                try:
                    # 合并所有中间件 spans 到 Tracer（供 /api/conversations/:id/messages 查询）
                    from src.middleware.tracing import tracing_middleware as _tm
                    all_mw_spans = _tm.get_spans(req.thread_id)
                    if all_mw_spans:
                        for mw_span in all_mw_spans:
                            span = tracer.start_span(
                                trace.trace_id,
                                mw_span.get("type", "unknown"),
                                mw_span.get("name", ""),
                                input_data=mw_span.get("input_data", {}),
                                metadata=mw_span.get("metadata", {}),
                            )
                            span.start_time = mw_span.get("timestamp", span.start_time)
                            span.duration_ms = mw_span.get("duration_ms", 0)
                            span.status = mw_span.get("status", "success")
                            span.end_time = span.start_time + span.duration_ms / 1000
                            span.output_data = mw_span.get("output_data", {})
                            if mw_span.get("detail"):
                                span.metadata["detail"] = mw_span["detail"]
                            if mw_span.get("step_name"):
                                span.metadata["step_name"] = mw_span["step_name"]
                            if mw_span.get("step_name_en"):
                                span.metadata["step_name_en"] = mw_span["step_name_en"]
                            if mw_span.get("phase"):
                                span.metadata["phase"] = mw_span["phase"]
                            if mw_span.get("children"):
                                span.metadata["children"] = mw_span["children"]
                        _tm.clear(req.thread_id)

                    trace_status = "error" if (_document_failed or _run_failed) else "success"
                    tracer.finish_trace(trace.trace_id, trace_status, final_content)
                    from src.store.trace_writer import TraceWriter
                    from src.core.context import DEFAULT_TENANT_ID
                    _tw = TraceWriter(tenant_id=DEFAULT_TENANT_ID)
                    trace_final = tracer.get_trace(trace.trace_id)
                    if trace_final:
                        _tw.on_trace_finish(trace_final)
                except Exception as _te:
                    logger.warning("AG-UI conversation persist failed: %s", _te)

        except Exception as exc:
            logger.exception("execute_agui failed")
            from src.agui import run_error
            # 记录异常到 trace 链路
            if trace is not None:
                try:
                    tracer.finish_trace(
                        trace.trace_id, "error",
                        f"execute_agui exception: {type(exc).__name__}: {str(exc)[:200]}",
                    )
                    from src.store.trace_writer import TraceWriter
                    from src.core.context import DEFAULT_TENANT_ID
                    _tw_exc = TraceWriter(tenant_id=DEFAULT_TENANT_ID)
                    trace_final_exc = tracer.get_trace(trace.trace_id)
                    if trace_final_exc:
                        _tw_exc.on_trace_finish(trace_final_exc)
                except Exception as _te:
                    logger.warning("AG-UI trace exception persist failed: %s", _te)
            error_event = run_error("INTERNAL_ERROR", code=type(exc).__name__)
            published = await stream_hub.publish(req.thread_id, error_event)
            encoded = (
                encode_official_sse(error_event, published.sequence)
                if standard_wire else error_event.to_sse(published.sequence)
            )
            if encoded:
                yield encoded
        finally:
            thread_store.end_user_view_scope(req.thread_id, user_view_scope_id)
            if lease_acquired:
                run_registry.finish(req.thread_id, run_id)

    headers = {
        "X-A2UI-Catalog": catalog_id,
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    if standard_wire:
        headers["X-AGUI-Protocol"] = "0.1"
    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers=headers,
    )
