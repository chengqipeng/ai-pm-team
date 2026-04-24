"""DeepAgent API 服务 — FastAPI + SSE + 完整 Tracing

启动: poetry run uvicorn server:app --host 0.0.0.0 --port 8001 --reload

API:
  POST /api/chat              — 流式对话（SSE）
  POST /api/chat/sync         — 同步对话
  GET  /api/traces             — Trace 列表
  GET  /api/traces/{trace_id}  — Trace 详情（含完整 span 链路）
  GET  /api/health             — 健康检查
  GET  /                       — 前端页面
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from src.core.tracer import tracer, Tracer, SpanType

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("deepagent.server")

app = FastAPI(title="DeepAgent API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Trace 持久化 ──
from src.store.trace_writer import TraceWriter
trace_writer = TraceWriter(tenant_id=1)

# ── Agent 懒加载 ──

_agent = None
_agent_mm = None  # 多模态 Agent
_agent_lock = asyncio.Lock()


async def _get_agent(multimodal: bool = False):
    global _agent, _agent_mm
    target = _agent_mm if multimodal else _agent
    if target is not None:
        return target
    async with _agent_lock:
        target = _agent_mm if multimodal else _agent
        if target is not None:
            return target

        from src.agents.langchain_agent import create_deep_agent, LangChainAgentConfig
        from src.tools.base import ToolRegistry
        from src.tools.crm_backend import CrmSimulatedBackend
        from src.tools.crm_tools import register_crm_tools
        from src.skills.base import SkillRegistry
        from src.skills.crm_skills import register_crm_skills
        from src.core.prompt_builder import build_system_prompt
        from src.middleware.builder import build_middleware
        from src.memory.fts_engine import FTSMemoryEngine
        from langchain_openai import ChatOpenAI

        backend = CrmSimulatedBackend()
        reg = ToolRegistry()
        register_crm_tools(reg, backend)
        skill_reg = SkillRegistry()
        register_crm_skills(skill_reg)

        aux_llm = ChatOpenAI(model="doubao-1-5-pro-32k-250115", api_key=os.environ["DOUBAO_API_KEY"],
                             base_url="https://ark.cn-beijing.volces.com/api/v3/", max_tokens=2048)
        memory_engine = FTSMemoryEngine(storage_dir="./data/memory", llm=aux_llm)

        system_prompt = build_system_prompt(agent_name="CRM-Agent", skills=skill_reg.list_all())
        middlewares = build_middleware(
            system_prompt=system_prompt,
            agent_name="CRM-Agent", memory_engine=memory_engine,
            file_upload_enabled=True,
        )

        model_name = MULTIMODAL_MODEL if multimodal else TEXT_MODEL

        config = LangChainAgentConfig(
            model=model_name, api_key=os.environ["DOUBAO_API_KEY"],
            api_base="https://ark.cn-beijing.volces.com/api/v3/", tool_registry=reg,
            skill_registry=skill_reg, system_prompt=system_prompt, middlewares=middlewares,
        )
        built = create_deep_agent(config)

        if multimodal:
            _agent_mm = built
            logger.warning("多模态 Agent 初始化完成 (model=%s)", model_name)
        else:
            _agent = built
            logger.warning("文本 Agent 初始化完成 (model=%s)", model_name)
        return built


# ── API 模型 ──

class ChatRequest(BaseModel):
    message: str
    thread_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    history: list[dict[str, str]] = Field(default_factory=list)


# ── 文件上传存储 ──

_uploaded_files: dict[str, list[dict]] = {}  # thread_id → [file_info, ...]

UPLOAD_DIR = "./data/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 多模态模型配置
MULTIMODAL_MODEL = "doubao-seed-2-0-lite-260215"
TEXT_MODEL = "doubao-1-5-pro-32k-250115"


# ── API 路由 ──

@app.get("/api/health")
async def health():
    return {"status": "ok", "agent_ready": _agent is not None,
            "multimodal_ready": _agent_mm is not None,
            "text_model": TEXT_MODEL, "multimodal_model": MULTIMODAL_MODEL}


@app.post("/api/upload")
async def upload_file(request: Request):
    """文件上传 — 支持图片和文档"""
    form = await request.form()
    thread_id = str(form.get("thread_id", uuid.uuid4().hex[:12]))
    file = form.get("file")

    if file is None:
        return JSONResponse({"error": "No file provided"}, status_code=400)

    # 读取文件内容
    content = await file.read()
    filename = getattr(file, "filename", None) or "unnamed"
    content_type = getattr(file, "content_type", "") or ""

    # 保存到磁盘
    import mimetypes
    thread_dir = os.path.join(UPLOAD_DIR, str(thread_id))
    os.makedirs(thread_dir, exist_ok=True)
    file_id = uuid.uuid4().hex[:8]
    save_path = os.path.join(thread_dir, f"{file_id}_{filename}")
    with open(save_path, "wb") as f:
        f.write(content)

    # 判断文件类型
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
    is_image = ext in image_exts or content_type.startswith("image/")

    # 构建文件信息
    file_info = {
        "fileName": filename,
        "fileType": "image" if is_image else "document",
        "content": "",  # 文档内容后续由中间件提取
        "url": f"/uploads/{thread_id}/{file_id}_{filename}",
        "mediaId": file_id,
        "size": len(content),
    }

    # 图片：生成 base64 data URL 供多模态模型使用
    if is_image:
        import base64
        b64 = base64.b64encode(content).decode("ascii")
        mime = content_type or mimetypes.guess_type(filename)[0] or "image/png"
        file_info["url"] = f"data:{mime};base64,{b64}"

    # 文档：尝试提取文本
    if not is_image:
        try:
            from src.uploads.manager import UploadManager
            mgr = UploadManager(base_dir=UPLOAD_DIR)
            text = ""
            if ext in (".txt", ".md", ".csv"):
                text = content.decode("utf-8", errors="replace")
            elif ext == ".pdf":
                text = mgr.convert_to_markdown(save_path)
            elif ext == ".docx":
                text = mgr.convert_to_markdown(save_path)
            file_info["content"] = text[:10000]
        except Exception as e:
            logger.warning("文件内容提取失败: %s — %s", filename, e)

    # 存储到 thread 的文件列表
    _uploaded_files.setdefault(str(thread_id), []).append(file_info)

    return {
        "file_id": file_id,
        "fileName": filename,
        "fileType": file_info["fileType"],
        "size": len(content),
        "thread_id": str(thread_id),
    }


@app.get("/uploads/{thread_id}/{filename}")
async def serve_upload(thread_id: str, filename: str):
    """静态文件服务 — 上传的文件"""
    from fastapi.responses import FileResponse
    path = os.path.join(UPLOAD_DIR, thread_id, filename)
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse({"error": "File not found"}, status_code=404)


@app.post("/api/chat")
async def chat_stream(req: ChatRequest):
    """流式对话 — SSE + 完整 Tracing + 多模态支持"""
    # 获取该 thread 的上传文件
    files = _uploaded_files.get(req.thread_id, [])
    has_images = any(f.get("fileType") == "image" for f in files)

    agent = await _get_agent(multimodal=has_images)
    thread_id = req.thread_id

    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

    messages = []
    for msg in req.history:
        if msg.get("role") == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg.get("role") == "assistant":
            messages.append(AIMessage(content=msg["content"]))
    messages.append(HumanMessage(content=req.message))

    # 获取该 thread 的上传文件
    files = _uploaded_files.get(thread_id, [])

    # 开始 Trace
    trace = tracer.start_trace(thread_id, req.message, model=TEXT_MODEL, agent_name="CRM-Agent")
    trace_id = trace.trace_id
    trace_writer.on_trace_start(trace)

    async def event_generator():
        config = {
            "configurable": {
                "thread_id": thread_id,
                "files": files,
                "parsed_files": files,  # FileProcessMiddleware 也从这里读
                "extend_params": {},
            },
            "recursion_limit": 100,
        }
        full_content = ""
        current_tool_span = None
        # 增量推送中间件 spans
        from src.middleware.tracing import tracing_middleware
        last_mw_idx = 0

        def flush_mw_spans():
            """检查并推送新的中间件 spans"""
            nonlocal last_mw_idx
            mw_spans = tracing_middleware.get_spans(thread_id)
            new_spans = mw_spans[last_mw_idx:]
            last_mw_idx = len(mw_spans)
            return new_spans

        try:
            async for event in agent.astream_events({"messages": messages}, config=config, version="v2"):
                kind = event.get("event", "")
                data = event.get("data", {})

                # 每次事件循环都检查是否有新的中间件 spans 需要推送
                for mw_span in flush_mw_spans():
                    yield f"data: {json.dumps({'type': 'mw_span', 'span': mw_span}, ensure_ascii=False)}\n\n"

                if kind == "on_chat_model_stream":
                    parent_ids = event.get("parent_ids", [])
                    if len(parent_ids) > 2:
                        continue
                    chunk = data.get("chunk")
                    if chunk:
                        content = getattr(chunk, "content", "")
                        if isinstance(content, list):
                            content = "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
                        if content:
                            full_content += content
                            yield f"data: {json.dumps({'type': 'token', 'content': content}, ensure_ascii=False)}\n\n"

                elif kind == "on_chat_model_start":
                    tracer.increment_iteration(trace_id)
                    iter_num = trace.iteration_count
                    span = tracer.start_span(trace_id, SpanType.LLM_CALL, f"第 {iter_num} 轮思考",
                                             metadata={"iteration": iter_num})
                    yield f"data: {json.dumps({'type': 'llm_start', 'iteration': iter_num}, ensure_ascii=False)}\n\n"

                elif kind == "on_chat_model_end":
                    # 结束最后一个 LLM span — 提取完整的 token/tool_calls/is_final 信息
                    for s in reversed(trace.spans):
                        if s.type == "llm_call" and s.status == "running":
                            output = data.get("output", {})
                            # 提取 token 用量（优先 usage_metadata，fallback 文本长度估算）
                            token_info = {}
                            if hasattr(output, "usage_metadata") and output.usage_metadata:
                                um = output.usage_metadata
                                token_info = {"input_tokens": um.get("input_tokens", 0),
                                              "output_tokens": um.get("output_tokens", 0)}
                            # Fallback: 从文本长度估算（1 token ≈ 2 中文字符 / 4 英文字符）
                            if not token_info.get("output_tokens"):
                                ai_text = ""
                                if hasattr(output, "content"):
                                    ai_text = output.content if isinstance(output.content, str) else str(output.content)
                                est_output = max(len(ai_text) // 2, 1) if ai_text else 0
                                # 估算 input tokens（从当前消息数 × 平均长度）
                                est_input = s.metadata.get("iteration", 1) * 2000  # 粗估每轮 2K input
                                token_info = {"input_tokens": est_input, "output_tokens": est_output, "estimated": True}

                            total = token_info.get("input_tokens", 0) + token_info.get("output_tokens", 0)
                            if total > 0:
                                tracer.add_tokens(trace_id, total)

                            # 提取 tool_calls 和 is_final
                            tool_calls = []
                            is_final = True
                            ai_content = ""
                            if hasattr(output, "content"):
                                ai_content = output.content if isinstance(output.content, str) else str(output.content)
                            if hasattr(output, "tool_calls") and output.tool_calls:
                                tool_calls = [tc.get("name", "") for tc in output.tool_calls if isinstance(tc, dict)]
                                is_final = False

                            # 写入 metadata（确保前端能读到）
                            s.metadata.update({
                                **token_info,
                                "tool_calls": tool_calls if tool_calls else [],
                                "is_final": is_final,
                                "output_preview": ai_content[:200] if is_final and ai_content else "",
                            })
                            s.finish("success", token_info)
                            yield f"data: {json.dumps({'type': 'llm_end', 'duration_ms': round(s.duration_ms), 'tokens': token_info}, ensure_ascii=False)}\n\n"
                            break

                elif kind == "on_tool_start":
                    tracer.increment_tool(trace_id)
                    tool_name = event.get("name", "")
                    tool_input = str(data.get("input", ""))[:300]
                    current_tool_span = tracer.start_span(
                        trace_id, SpanType.TOOL_CALL, f"tool:{tool_name}",
                        input_data={"tool_name": tool_name, "input": tool_input},
                        metadata={"tool_name": tool_name, "input": tool_input[:200]},
                    )
                    yield f"data: {json.dumps({'type': 'tool_start', 'tool_name': tool_name, 'input': tool_input[:200]}, ensure_ascii=False)}\n\n"

                elif kind == "on_tool_end":
                    tool_name = event.get("name", "")
                    output = str(data.get("output", ""))[:500]
                    if current_tool_span and current_tool_span.status == "running":
                        current_tool_span.metadata["output"] = output[:300]
                        current_tool_span.metadata["status"] = "success"
                        current_tool_span.finish("success", {"output": output[:300]})
                        yield f"data: {json.dumps({'type': 'tool_end', 'tool_name': tool_name, 'output': output[:200], 'duration_ms': round(current_tool_span.duration_ms)}, ensure_ascii=False)}\n\n"
                        current_tool_span = None

        except Exception as exc:
            err_span = tracer.start_span(trace_id, SpanType.ERROR, "error",
                                         input_data={"error": str(exc)})
            err_span.finish("error")
            tracer.finish_trace(trace_id, "error", full_content)
            trace_writer.on_trace_finish(tracer.get_trace(trace_id))
            yield f"data: {json.dumps({'type': 'error', 'content': str(exc)}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'trace_id': trace_id}, ensure_ascii=False)}\n\n"
            return

        tracer.finish_trace(trace_id, "success", full_content)

        # 最终推送剩余的中间件 spans
        remaining_mw = flush_mw_spans()
        for mw_span in remaining_mw:
            yield f"data: {json.dumps({'type': 'mw_span', 'span': mw_span}, ensure_ascii=False)}\n\n"

        # 合并所有中间件 spans 到 Tracer（供 /api/traces/{id} 查询）
        all_mw_spans = tracing_middleware.get_spans(thread_id)
        tracing_middleware.clear(thread_id)
        trace_obj = tracer.get_trace(trace_id)
        if trace_obj and all_mw_spans:
            for mw_span in all_mw_spans:
                span = tracer.start_span(
                    trace_id,
                    mw_span.get("type", "unknown"),
                    mw_span.get("name", ""),
                    metadata=mw_span.get("metadata", {}),
                )
                # 使用中间件记录的原始时间戳，确保排序正确
                span.start_time = mw_span.get("timestamp", span.start_time)
                span.duration_ms = mw_span.get("duration_ms", 0)
                span.status = "success"
                span.end_time = span.start_time + span.duration_ms / 1000
                if mw_span.get("children"):
                    span.metadata["children"] = mw_span["children"]

        # 持久化到 PG（在所有 span 合并完成后）
        trace_final = tracer.get_trace(trace_id)
        if trace_final:
            trace_writer.on_trace_finish(trace_final)

        yield f"data: {json.dumps({'type': 'done', 'trace_id': trace_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/chat/sync")
async def chat_sync(req: ChatRequest):
    """同步对话"""
    files = _uploaded_files.get(req.thread_id, [])
    has_images = any(f.get("fileType") == "image" for f in files)
    agent = await _get_agent(multimodal=has_images)
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

    messages = []
    for msg in req.history:
        if msg.get("role") == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg.get("role") == "assistant":
            messages.append(AIMessage(content=msg["content"]))
    messages.append(HumanMessage(content=req.message))

    trace = tracer.start_trace(req.thread_id, req.message, model="doubao-1-5-pro-32k-250115", agent_name="CRM-Agent")
    trace_writer.on_trace_start(trace)

    result = await agent.ainvoke({"messages": messages},
                                  config={"configurable": {"thread_id": req.thread_id}})
    msgs = result.get("messages", [])

    content = ""
    for msg in reversed(msgs):
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    # 记录工具调用 spans
    for msg in msgs:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                span = tracer.start_span(trace.trace_id, SpanType.TOOL_CALL, f"tool:{tc.get('name', '')}",
                                         input_data={"args": str(tc.get("args", {}))[:200]})
                span.finish("success")
                tracer.increment_tool(trace.trace_id)
        elif isinstance(msg, ToolMessage):
            pass  # 已在 tool_call span 中记录

    tracer.finish_trace(trace.trace_id, "success", content)

    # 合并中间件 spans（sync 模式也需要）
    from src.middleware.tracing import tracing_middleware
    all_mw_spans = tracing_middleware.get_spans(req.thread_id)
    tracing_middleware.clear(req.thread_id)
    if all_mw_spans:
        for mw_span in all_mw_spans:
            span = tracer.start_span(
                trace.trace_id,
                mw_span.get("type", "unknown"),
                mw_span.get("name", ""),
                metadata=mw_span.get("metadata", {}),
            )
            span.start_time = mw_span.get("timestamp", span.start_time)
            span.duration_ms = mw_span.get("duration_ms", 0)
            span.status = "success"
            span.end_time = span.start_time + span.duration_ms / 1000
            if mw_span.get("children"):
                span.metadata["children"] = mw_span["children"]

    # 持久化到 PG
    trace_final = tracer.get_trace(trace.trace_id)
    if trace_final:
        trace_writer.on_trace_finish(trace_final)

    return {"content": content, "thread_id": req.thread_id, "trace_id": trace.trace_id}


@app.get("/api/traces")
async def list_traces(limit: int = 50):
    """Trace 列表 — 优先内存，合并 PG 历史数据"""
    # 内存中的 traces
    mem_traces = tracer.get_all_traces(limit)
    mem_list = [
        {
            "trace_id": t.trace_id,
            "thread_id": t.thread_id,
            "user_input": t.user_input[:100],
            "status": t.status,
            "total_duration_ms": round(t.total_duration_ms),
            "total_tokens": t.total_tokens,
            "iteration_count": t.iteration_count,
            "tool_count": t.tool_count,
            "span_count": len(t.spans),
            "start_time": t.start_time,
            "model": t.model,
            "agent_name": t.agent_name,
        } for t in mem_traces
    ]
    mem_ids = {t["trace_id"] for t in mem_list}

    # PG 中的 traces（排除内存中已有的）
    db_traces = trace_writer.read_traces(limit)
    for dt in db_traces:
        if dt["trace_id"] not in mem_ids:
            mem_list.append({
                "trace_id": dt["trace_id"],
                "thread_id": dt.get("thread_id", ""),
                "user_input": (dt.get("user_input") or "")[:100],
                "status": dt.get("status", ""),
                "total_duration_ms": dt.get("duration_ms", 0),
                "total_tokens": dt.get("total_tokens", 0),
                "iteration_count": dt.get("iteration_count", 0),
                "tool_count": dt.get("tool_count", 0),
                "span_count": dt.get("span_count", 0),
                "start_time": (dt.get("start_time") or 0) / 1000,  # ms → s
                "model": dt.get("model", ""),
                "agent_name": dt.get("agent_name", ""),
            })

    # 按 start_time 降序排序
    mem_list.sort(key=lambda x: x.get("start_time", 0), reverse=True)
    return {"traces": mem_list[:limit], "total": len(mem_list)}


@app.get("/api/traces/{trace_id}")
async def get_trace(trace_id: str):
    """Trace 详情 — 优先内存，fallback PG"""
    # 优先从内存读（实时数据）
    trace = tracer.get_trace(trace_id)
    if trace is not None:
        return {
            "trace": trace.to_dict(),
            "timeline": trace.to_timeline(),
        }

    # 内存没有 → 从 PG 读（历史数据）
    db_trace = trace_writer.read_trace_detail(trace_id)
    if db_trace is not None:
        return {"trace": db_trace}

    return JSONResponse({"error": "Trace not found"}, status_code=404)


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = os.path.join(os.path.dirname(__file__), "frontend.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return f.read()
    return "<h1>DeepAgent API</h1>"


@app.get("/trace", response_class=HTMLResponse)
async def trace_explorer():
    """Trace Explorer 独立页面"""
    html_path = os.path.join(os.path.dirname(__file__), "trace_explorer.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return f.read()
    return "<h1>Trace Explorer — 页面未找到</h1>"


@app.get("/sessions", response_class=HTMLResponse)
async def session_browser():
    """Session 浏览器独立页面"""
    html_path = os.path.join(os.path.dirname(__file__), "session_browser.html")
    if os.path.exists(html_path):
        with open(html_path, encoding="utf-8") as f:
            return f.read()
    return "<h1>Session Browser — 页面未找到</h1>"
