"""知识库管理 REST API

由 server.py 通过 `app.include_router(knowledge_router)` 挂载。

路由前缀：/api/knowledge

⚠️ 路由声明顺序很重要：所有具体路径（/documents、/datasets 等）必须在
参数化 /{kb_id} 之前声明，否则 FastAPI 会把 "documents" 当成 kb_id 解析。

路由分组：
    - 文档相关：/documents/*
    - 数据集:   /datasets/*
    - Schema:   /schemas/*
    - 任务:     /tasks/*
    - 审计:     /search-logs/*
    - 知识库:   / 和 /{kb_id}（必须放最后）
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from src.store.knowledge_dao import (
    KnowledgeBaseDAO,
    KnowledgeChunkDAO,
    KnowledgeDatasetDAO,
    KnowledgeDocumentDAO,
    KnowledgeIngestLogDAO,
    KnowledgeSchemaDAO,
    KnowledgeSearchLogDAO,
)
from src.store.knowledge_models import (
    KnowledgeBaseRow,
    KnowledgeDatasetRow,
    KnowledgeSchemaRow,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

def _get_provider(request: Request):
    """从 app.state 获取已注入的 KnowledgeProvider 实例

    server.py 启动时应调用：
        app.state.knowledge_provider = provider

    若 Provider 未启用，前端收到 503 + 明确错误信息。
    """
    provider = getattr(request.app.state, "knowledge_provider", None)
    if provider is None:
        logger.error(
            "KnowledgeProvider 未注入到 app.state — "
            "请在 server.py 启动时调用 build_knowledge_provider() 并挂 app.state.knowledge_provider"
        )
        raise HTTPException(
            503,
            "知识库 Provider 未启用。请在 server.py 启动时挂载 "
            "app.state.knowledge_provider（调用 build_knowledge_provider）"
        )
    return provider


def _require_tenant(tenant_id: int) -> None:
    if tenant_id <= 0:
        raise HTTPException(400, "tenant_id 必填且必须为正整数")


def _kb_to_dict(kb: KnowledgeBaseRow) -> dict:
    return {
        # ⚠️ id 是雪花 BIGINT，超过 JS Number 精度上限（2^53），必须用 string 传给前端
        "id": str(kb.id),
        "tenant_id": kb.tenant_id,
        "api_key": kb.api_key,
        "name": kb.name,
        "description": kb.description,
        "owner": kb.owner,
        "default_top_k": kb.default_top_k,
        "min_score": kb.min_score,
        "enable_rerank": bool(kb.enable_rerank),
        "enable_self_query": bool(kb.enable_self_query),
        "schema_id": str(kb.schema_id) if kb.schema_id else "0",
        "document_count": kb.document_count,
        "chunk_count": kb.chunk_count,
        "status": kb.status,
        "created_at": kb.created_at,
        "updated_at": kb.updated_at,
    }


def _doc_row_to_dict(r) -> dict:
    try:
        md = json.loads(r.metadata) if r.metadata else {}
    except json.JSONDecodeError:
        md = {}
    return {
        "doc_id": r.doc_id,
        "title": r.title,
        "file_name": r.file_name,
        "file_type": r.file_type,
        "file_size": r.file_size,
        "knowledge_base_id": str(r.knowledge_base_id),
        "parse_status": r.parse_status,
        "clean_status": r.clean_status,
        "chunk_status": r.chunk_status,
        "chunk_count": r.chunk_count,
        "segment_count": r.segment_count,
        "quality_score": r.quality_score,
        "summary": r.summary,
        "metadata": md,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


# ═══════════════════════════════════════════════════════════
# 1. 文档（/documents/*）— 必须在 /{kb_id} 之前声明
# ═══════════════════════════════════════════════════════════

@router.post("/documents/upload")
async def upload_document(
    request: Request,
    tenant_id: int = Query(..., gt=0),
    knowledge_base_id: int = Query(..., gt=0),
    dataset_id: int = Query(0, ge=0),
    title: str = Query(""),
    file: UploadFile = File(...),
):
    """上传文档 → 存本地 → 入队 → 立即返回 task_id"""
    provider = _get_provider(request)

    # ── 前置校验 ──
    if not file or not file.filename:
        logger.warning("Upload rejected: empty file (tenant=%s kb=%s)", tenant_id, knowledge_base_id)
        raise HTTPException(400, "未提供有效文件")

    kb = KnowledgeBaseDAO.get_by_id(knowledge_base_id)
    if kb is None or kb.tenant_id != tenant_id:
        logger.warning(
            "Upload rejected: kb not found or tenant mismatch "
            "(tenant=%s kb=%s file=%s)",
            tenant_id, knowledge_base_id, file.filename,
        )
        raise HTTPException(404, f"知识库 id={knowledge_base_id} 不存在或不属于该租户")

    # ── 落临时文件 ──
    suffix = os.path.splitext(file.filename or "")[1] or ""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        file_size = len(content)
        logger.info(
            "Upload received: tenant=%s kb=%s file=%s size=%d type=%s tmp=%s",
            tenant_id, knowledge_base_id, file.filename, file_size, suffix, tmp_path,
        )
    except Exception as exc:
        logger.exception(
            "Upload failed to save tmp file: tenant=%s kb=%s file=%s: %s",
            tenant_id, knowledge_base_id, file.filename, exc,
        )
        raise HTTPException(500, f"临时文件写入失败: {exc}")

    try:
        result = await provider.ingest_document(
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
            file_path=tmp_path,
            file_name=file.filename,
            user_metadata={"title": title} if title else None,
            dataset_id=dataset_id,
        )
        logger.info(
            "Upload queued: tenant=%s kb=%s file=%s task_id=%s doc_id=%s status=%s reused=%s",
            tenant_id, knowledge_base_id, file.filename,
            result.task_id, result.doc_id, result.status, result.reused,
        )
        return {
            "task_id": result.task_id,
            "doc_id": result.doc_id,
            "status": result.status,
            "reused": result.reused,
            "message": result.message,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "Upload ingest_document failed: tenant=%s kb=%s file=%s: %s",
            tenant_id, knowledge_base_id, file.filename, exc,
        )
        raise HTTPException(500, f"文档入库失败: {type(exc).__name__}: {exc}")
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError as exc:
                logger.debug("Failed to remove tmp file %s: %s", tmp_path, exc)


@router.get("/documents")
async def list_documents(
    tenant_id: int = Query(..., gt=0),
    knowledge_base_id: int = Query(..., gt=0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """文档列表（直接走 DAO，不依赖 provider）"""
    rows = KnowledgeDocumentDAO.list_by_kb(tenant_id, knowledge_base_id, limit, offset)
    return {
        "items": [_doc_row_to_dict(r) for r in rows],
        "total": len(rows),
    }


@router.get("/documents/{doc_id}/chunks")
async def list_document_chunks(
    doc_id: str,
    limit: int = Query(200, ge=1, le=1000),
):
    """查看文档的切片（调试/审计用）"""
    rows = KnowledgeChunkDAO.list_by_doc(doc_id)
    return {
        "items": [
            {
                "chunk_id": r.chunk_id,
                "chunk_index": r.chunk_index,
                "chunk_type": r.chunk_type,
                "section_title": r.section_title,
                "section_path": r.section_path,
                "content_tokens": r.content_tokens,
                "vector_synced": r.vector_synced,
                "hit_count": r.hit_count,
                "content_preview": r.content[:200] + ("…" if len(r.content) > 200 else ""),
            }
            for r in rows[:limit]
        ],
        "total": len(rows),
    }


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    """文档详情（直接走 DAO，不依赖 provider）"""
    row = KnowledgeDocumentDAO.get_by_doc_id(doc_id)
    if row is None:
        raise HTTPException(404, "文档不存在")
    try:
        md = json.loads(row.metadata) if row.metadata else {}
    except json.JSONDecodeError:
        md = {}
    try:
        qs = json.loads(row.quality_signals) if row.quality_signals else {}
    except json.JSONDecodeError:
        qs = {}
    return {
        "doc_id": row.doc_id,
        "title": row.title,
        "file_name": row.file_name,
        "file_type": row.file_type,
        "file_size": row.file_size,
        "knowledge_base_id": str(row.knowledge_base_id),
        "summary": row.summary,
        "keywords": row.keywords,
        "candidate_keywords": row.candidate_keywords,
        "chunk_count": row.chunk_count,
        "segment_count": row.segment_count,
        "quality_score": row.quality_score,
        "quality_signals": qs,
        "metadata": md,
        "parse_status": row.parse_status,
        "clean_status": row.clean_status,
        "chunk_status": row.chunk_status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    request: Request,
    tenant_id: int = Query(..., gt=0),
):
    provider = _get_provider(request)
    ok = await provider.delete_document(tenant_id, doc_id)
    if not ok:
        raise HTTPException(404, "文档不存在或不属于该租户")
    return {"deleted": True, "doc_id": doc_id}


# ═══════════════════════════════════════════════════════════
# 2. 数据集（/datasets/*）
# ═══════════════════════════════════════════════════════════

class CreateDatasetReq(BaseModel):
    tenant_id: int
    knowledge_base_id: int
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    chunk_strategy: str = Field(
        default="lkeap",
        pattern="^(lkeap|local_header|sliding_window)$",
    )
    chunk_size: int = Field(default=800, ge=100, le=4000)
    chunk_overlap: int = Field(default=200, ge=0, le=1000)


@router.post("/datasets")
async def create_dataset(req: CreateDatasetReq):
    _require_tenant(req.tenant_id)
    kb = KnowledgeBaseDAO.get_by_id(req.knowledge_base_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")

    ds = KnowledgeDatasetRow(
        tenant_id=req.tenant_id,
        knowledge_base_id=req.knowledge_base_id,
        name=req.name,
        description=req.description,
        chunk_strategy=req.chunk_strategy,
        chunk_size=req.chunk_size,
        chunk_overlap=req.chunk_overlap,
    )
    KnowledgeDatasetDAO.insert(ds)
    return {"id": str(ds.id), "name": ds.name}


@router.get("/datasets")
async def list_datasets(
    tenant_id: int = Query(..., gt=0),
    knowledge_base_id: int = Query(..., gt=0),
):
    rows = KnowledgeDatasetDAO.list_by_kb(tenant_id, knowledge_base_id)
    return {
        "items": [
            {
                "id": str(r.id), "name": r.name, "description": r.description,
                "chunk_strategy": r.chunk_strategy,
                "document_count": r.document_count,
                "chunk_count": r.chunk_count,
            }
            for r in rows
        ],
    }


# ═══════════════════════════════════════════════════════════
# 3. Schema（/schemas/*）
# ═══════════════════════════════════════════════════════════

class CreateSchemaReq(BaseModel):
    tenant_id: int
    name: str = Field(min_length=1, max_length=100)
    knowledge_base_id: int = Field(default=0, description="0 表示租户默认 Schema")
    fields: list[dict] = Field(
        description=(
            "字段定义列表，每项形如："
            '{"field": "docCategory", "type": "enum", "required": true, '
            '"description": "...", "enum": ["产品手册", "成功案例"]}'
        ),
    )


@router.post("/schemas")
async def create_schema(req: CreateSchemaReq):
    _require_tenant(req.tenant_id)
    row = KnowledgeSchemaRow(
        tenant_id=req.tenant_id,
        name=req.name,
        knowledge_base_id=req.knowledge_base_id,
        fields=json.dumps(req.fields, ensure_ascii=False),
    )
    KnowledgeSchemaDAO.insert(row)
    return {"id": str(row.id), "name": row.name}


@router.get("/schemas/for-kb/{kb_id}")
async def get_schema_for_kb(kb_id: int, tenant_id: int = Query(..., gt=0)):
    """获取 KB 专属 Schema，无则回退租户默认，再无则回退系统默认(tenant_id=0)"""
    # 1. KB 专属
    row = KnowledgeSchemaDAO.get_for_kb(tenant_id, kb_id)
    # 2. 回退系统默认
    if row is None:
        row = KnowledgeSchemaDAO.get_for_kb(0, 0)
    if row is None:
        return {"fields": [], "source": "none"}
    try:
        fields = json.loads(row.fields or "[]")
    except json.JSONDecodeError:
        fields = []
    return {
        "id": str(row.id),
        "name": row.name,
        "version": row.version,
        "fields": fields,
        "source": "system_default" if row.tenant_id == 0 else "custom",
    }


# ═══════════════════════════════════════════════════════════
# 4. 任务（/tasks/*）
# ═══════════════════════════════════════════════════════════

@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str, request: Request):
    provider = _get_provider(request)
    status = await provider.get_ingest_status(task_id)
    if status is None:
        raise HTTPException(404, "任务不存在")
    return status


# ═══════════════════════════════════════════════════════════
# 5. 检索审计反馈（/search-logs/*）
# ═══════════════════════════════════════════════════════════

class FeedbackReq(BaseModel):
    trace_id: str
    user_feedback: str = Field(pattern="^(good|bad)$")
    feedback_comment: str = ""


@router.post("/search-logs/feedback")
async def submit_feedback(req: FeedbackReq):
    ok = KnowledgeSearchLogDAO.update_feedback(
        req.trace_id, req.user_feedback, req.feedback_comment,
    )
    if not ok:
        raise HTTPException(404, "未找到对应的检索记录")
    return {"updated": True}


# ═══════════════════════════════════════════════════════════
# 6. 知识库 CRUD（/ 和 /{kb_id}）— 必须放最后
# ═══════════════════════════════════════════════════════════

class CreateKnowledgeBaseReq(BaseModel):
    tenant_id: int
    api_key: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    owner: str = ""
    default_top_k: int = Field(default=5, ge=1, le=50)
    min_score: float = Field(default=0.3, ge=0.0, le=1.0)
    enable_rerank: bool = True
    enable_self_query: bool = True
    schema_id: int = 0


@router.post("")
async def create_knowledge_base(req: CreateKnowledgeBaseReq):
    _require_tenant(req.tenant_id)
    exists = KnowledgeBaseDAO.get_by_api_key(req.tenant_id, req.api_key)
    if exists:
        raise HTTPException(409, f"知识库 api_key={req.api_key} 已存在")

    kb = KnowledgeBaseRow(
        tenant_id=req.tenant_id,
        api_key=req.api_key,
        name=req.name,
        description=req.description,
        owner=req.owner,
        default_top_k=req.default_top_k,
        min_score=req.min_score,
        enable_rerank=1 if req.enable_rerank else 0,
        enable_self_query=1 if req.enable_self_query else 0,
        schema_id=req.schema_id,
    )
    KnowledgeBaseDAO.insert(kb)
    logger.info("KB created: id=%s tenant=%s api_key=%s", kb.id, kb.tenant_id, kb.api_key)
    return {"id": str(kb.id), "api_key": kb.api_key, "name": kb.name}


@router.get("")
async def list_knowledge_bases(
    tenant_id: int = Query(..., gt=0),
):
    """列出租户下的所有知识库

    不依赖 provider — 直接走 DAO，便于前端在 provider 未初始化时也可读。
    """
    _require_tenant(tenant_id)
    kbs = KnowledgeBaseDAO.list_by_tenant(tenant_id)
    return {
        "items": [
            {
                "id": str(kb.id),
                "api_key": kb.api_key,
                "name": kb.name,
                "description": kb.description,
                "default_top_k": kb.default_top_k,
                "document_count": kb.document_count,
                "chunk_count": kb.chunk_count,
            }
            for kb in kbs
        ],
    }


@router.get("/{kb_id}")
async def get_knowledge_base(kb_id: int):
    kb = KnowledgeBaseDAO.get_by_id(kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    return _kb_to_dict(kb)


@router.post("/{kb_id}/recompute-stats")
async def recompute_kb_stats(kb_id: int):
    """从实际文档重算 KB 统计（纠错；尤其用于修复负数或历史脏数据）"""
    kb = KnowledgeBaseDAO.get_by_id(kb_id)
    if kb is None:
        raise HTTPException(404, "知识库不存在")
    result = KnowledgeBaseDAO.recompute_stats(kb_id)
    logger.info(
        "KB stats recomputed: kb_id=%s document_count=%d chunk_count=%d",
        kb_id, result["document_count"], result["chunk_count"],
    )
    return result


@router.post("/maintenance/decay-hit-counts")
async def decay_hit_counts(decay_factor: float = Query(0.7, ge=0.1, le=1.0)):
    """热度衰减 — 手动触发（也可通过调度自动执行）"""
    doc_count = KnowledgeDocumentDAO.decay_hit_counts(decay_factor)
    chunk_count = KnowledgeChunkDAO.decay_hit_counts(decay_factor)
    logger.info(
        "Hit counts decayed: factor=%.2f docs=%d chunks=%d",
        decay_factor, doc_count, chunk_count,
    )
    return {
        "decay_factor": decay_factor,
        "documents_decayed": doc_count,
        "chunks_decayed": chunk_count,
    }


@router.get("/maintenance/schedules")
async def list_schedules():
    """列出所有调度任务"""
    from src.knowledge.scheduler import ScheduleDAO
    tasks = ScheduleDAO.list_all()
    for t in tasks:
        t["id"] = str(t["id"])
        try:
            t["params"] = json.loads(t.get("params") or "{}")
        except (json.JSONDecodeError, TypeError):
            t["params"] = {}
    return {"items": tasks}


class UpdateScheduleReq(BaseModel):
    enabled: bool | None = None
    interval_days: float | None = Field(None, ge=0.0007, le=365, description="[兼容] 执行间隔（天），最小约 1 分钟")
    interval_ms: int | None = Field(None, ge=60_000, description="执行间隔（毫秒），最小 60000（1 分钟）")
    params: dict | None = None


@router.put("/maintenance/schedules/{name}")
async def update_schedule(name: str, req: UpdateScheduleReq):
    """更新调度任务配置"""
    from src.knowledge.scheduler import ScheduleDAO
    if req.interval_ms is not None:
        interval_ms = req.interval_ms
    elif req.interval_days is not None:
        interval_ms = int(req.interval_days * 24 * 60 * 60 * 1000)
    else:
        interval_ms = None
    params_json = json.dumps(req.params, ensure_ascii=False) if req.params is not None else None
    enabled = int(req.enabled) if req.enabled is not None else None
    ok = ScheduleDAO.update_config(
        name,
        enabled=enabled,
        interval_ms=interval_ms,
        params=params_json,
    )
    if not ok:
        raise HTTPException(404, f"调度任务 '{name}' 不存在")
    return {"updated": True, "name": name}


@router.post("/maintenance/schedules/{name}/run")
async def run_schedule_now(name: str, request: Request):
    """立即执行某个调度任务（不等下次到期）"""
    from src.knowledge.scheduler import ScheduleDAO, ScheduleExecutor
    task = ScheduleDAO.get_by_name(name)
    if not task:
        raise HTTPException(404, f"调度任务 '{name}' 不存在")
    # 注入 VDB 引用（如果 provider 存在），让 VDB 同步类任务能工作
    provider = getattr(request.app.state, "knowledge_provider", None)
    vdb = getattr(provider, "_vdb", None) if provider else None
    executor = ScheduleExecutor(vdb=vdb)
    try:
        params = json.loads(task.get("params") or "{}")
    except (json.JSONDecodeError, TypeError):
        params = {}
    result = await executor._execute(task["task_type"], params)
    # 更新执行记录
    next_run = int(time.time() * 1000) + task["interval_ms"]
    ScheduleDAO.mark_run(name, "success", json.dumps(result, ensure_ascii=False), next_run)
    return {"name": name, "status": "success", "result": result}


@router.delete("/{kb_id}")
async def delete_knowledge_base(kb_id: int):
    ok = KnowledgeBaseDAO.soft_delete(kb_id)
    if not ok:
        raise HTTPException(404, "知识库不存在")
    return {"deleted": True, "id": str(kb_id)}
