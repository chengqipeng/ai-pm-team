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
        _deliver_user_action(thread_id, event)
        if span is not None:
            span.metadata.update({
                "outcome": "accepted",
                "action": event.name,
                "surface_id": event.surface_id,
            })
            span.finish("success")
        return JSONResponse({
            "status": "accepted",
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
# POST /agent/chat/reconnect — 断线重连
# ═══════════════════════════════════════════════════════════

class ChatReconnectRequest(BaseModel):
    thread_id: str = Field(alias="threadId")
    last_run_id: str | None = Field(default=None, alias="lastRunId")

    model_config = {"populate_by_name": True}


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
    a2uiClientCapabilities: dict | None = None

    model_config = {"populate_by_name": True}


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

    async def generator() -> AsyncGenerator[str, None]:
        run_id = uuid.uuid4().hex
        parent_run_id = req.last_run_id

        # 从 ThreadStore 拉真实态
        state = thread_store.get(req.thread_id)
        messages = list(state.messages) if state else []
        state_snapshot = state.snapshot_state() if state else None
        activities = state.active_activities() if state else []
        if state and state.last_run_id and parent_run_id is None:
            parent_run_id = state.last_run_id

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

    return StreamingResponse(generator(), media_type="text/event-stream")


# ═══════════════════════════════════════════════════════════
# POST /api/chat/agui — 统一 AG-UI 事件流对话端点
# ═══════════════════════════════════════════════════════════

@a2ui_router.post("/api/chat/agui")
async def chat_agui(req: ChatAguiRequest, http: Request) -> StreamingResponse:
    """AG-UI 统一对话端点。

    替代老的 `/api/chat`，输出格式完全对齐 AG-UI Python SDK 事件类型。
    A2UI 消息通过 ACTIVITY_SNAPSHOT 事件下发（Mode B）。

    流程：
    1. Catalog 协商 → 选定 catalog_id
    2. Trace start（复用 src.core.tracer）
    3. 调用 Adapter.execute_agui 拿事件流
    4. 顺便把每条消息写入 ThreadStore（供断线重连）
    """
    import uuid as _uuid
    import time as _time
    from src.a2ui import thread_store

    _req_start = _time.time()
    logger.info(
        "[AG-UI] 收到请求: thread=%s, run=%s, message=%s",
        req.thread_id, req.run_id or "(auto)",
        repr(req.message[:100]) if req.message else "(empty)",
    )

    # 1. Catalog 协商
    reg = get_catalog_registry()
    cap = req.a2uiClientCapabilities or {}
    catalog_id = reg.negotiate(
        client_supported=cap.get("supportedCatalogIds") or [],
        client_inline=cap.get("inlineCatalogs") or [],
        accepts_inline=False,
    )

    # 2. Trace start
    trace = None
    if _TRACE_ENABLED:
        try:
            trace = tracer.start_trace(
                thread_id=req.thread_id,
                user_input=req.message,
                agent_name="CRM-Agent",
            )
        except Exception:
            logger.exception("tracer.start_trace failed")

    # 3. 记录本次消息入 ThreadStore
    if req.message:
        thread_store.append_message(req.thread_id, {
            "role": "user", "content": req.message,
        })

    run_id = req.run_id or _uuid.uuid4().hex
    thread_store.set_last_run(req.thread_id, run_id)

    async def generator() -> AsyncGenerator[str, None]:
        from src.agents.adapter import neo_agent_v2_adapter

        _event_count = 0
        _text_chars = 0
        _full_content = ""  # 累积模型回复文本，用于持久化到 ai_message.answer
        _tool_calls = []
        _tool_args_buffer = {}  # tool_call_id → accumulated args string

        try:
            async for event in neo_agent_v2_adapter.execute_agui(
                thread_id=req.thread_id,
                user_input=req.message or "",
                run_id=run_id,
                resume=req.resume,
            ):
                _event_count += 1
                # 详细事件日志
                t_val = getattr(event.type, "value", event.type)
                if t_val == "TEXT_MESSAGE_CONTENT":
                    delta = event.data.get("delta", "")
                    _text_chars += len(delta)
                    _full_content += delta
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
                    logger.error("[AG-UI] [thread=%s] RUN_ERROR: %s", req.thread_id, event.data)
                elif t_val == "CUSTOM":
                    name = event.data.get("name", "")
                    if name == "doc_stream":
                        pass  # 高频事件不打印
                    elif name == "doc_stream_end":
                        logger.info("[AG-UI] [thread=%s] doc_stream_end", req.thread_id)
                    elif name == "component_complete":
                        apikey = (event.data.get("value") or {}).get("apikey", "")
                        logger.info("[AG-UI] [thread=%s] component_complete: %s", req.thread_id, apikey)
                    elif name == "mw_span":
                        span_val = event.data.get("value") or {}
                        span_type = span_val.get("type", "")
                        span_name = span_val.get("step_name", span_val.get("name", ""))
                        if span_type in ("skill_execution", "llm_call", "content_review", "query_rewrite", "memory_retrieval"):
                            logger.info("[AG-UI] [thread=%s] %s: %s", req.thread_id, span_type, span_val.get("detail", span_name))

                # ACTIVITY_SNAPSHOT 带 a2ui-surface 时登记到 ThreadStore
                if (t_val == "ACTIVITY_SNAPSHOT"
                        and event.data.get("activity_type") == "a2ui-surface"):
                    ops = (event.data.get("content") or {}).get("operations") or []
                    render_type = (event.data.get("content") or {}).get("render_type")
                    if render_type and ops:
                        thread_store.record_activity(req.thread_id, render_type, ops)
                yield event.to_sse()

            # 流正常结束 — 持久化会话到 ai_conversation
            if trace is not None:
                try:
                    # 将 assistant 回复写入 ThreadStore（供断线重连 MESSAGES_SNAPSHOT）
                    if _full_content:
                        thread_store.append_message(req.thread_id, {
                            "role": "assistant", "content": _full_content,
                        })

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

                    tracer.finish_trace(trace.trace_id, "success", _full_content)
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
            yield run_error("INTERNAL_ERROR", code=type(exc).__name__).to_sse()
        finally:
            pass

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"X-A2UI-Catalog": catalog_id},
    )
