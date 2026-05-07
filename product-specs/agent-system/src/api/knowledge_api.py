"""知识库管理 REST API

由 server.py 通过 `app.include_router(knowledge_router)` 挂载。

路由前缀：/api/knowledge

提供能力：
    - 知识库 CRUD
    - 数据集 CRUD
    - Schema CRUD
    - Agent 授权绑定
    - 文档上传 / 列表 / 删除 / 详情
    - 入库任务进度查询
    - 检索审计日志查询
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile, File
from pydantic import BaseModel, Field

from src.store.knowledge_dao import (
    KnowledgeBaseBindingDAO,
    KnowledgeBaseDAO,
    KnowledgeChunkDAO,
    KnowledgeDatasetDAO,
    KnowledgeDocumentDAO,
    KnowledgeIngestLogDAO,
    KnowledgeSchemaDAO,
    KnowledgeSearchLogDAO,
)
from src.store.knowledge_models import (
    KnowledgeBaseBindingRow,
    KnowledgeBaseRow,
    KnowledgeDatasetRow,
    KnowledgeSchemaRow,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


# ═══════════════════════════════════════════════════════════
# Provider 获取（从 app.state 注入）
# ═══════════════════════════════════════════════════════════

def _get_provider(request: Request):
    """从 app.state 获取已注入的 KnowledgeProvider 实例

    server.py 启动时应调用：
        app.state.knowledge_provider = provider
    """
    provider = getattr(request.app.state, "knowledge_provider", None)
    if provider is None:
        raise HTTPException(503, "知识库未启用，请在应用配置中开启 knowledge.enabled")
    return provider


def _require_tenant(tenant_id: int) -> None:
    if tenant_id <= 0:
        raise HTTPException(400, "tenant_id 必填且必须为正整数")


# ═══════════════════════════════════════════════════════════
# 1. 知识库 CRUD
# ═══════════════════════════════════════════════════════════

class CreateKnowledgeBaseReq(BaseModel):
    tenant_id: int
    api_key: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    owner: str = ""
    default_top_k: int = Field(default=5, ge=1, le=50)
    enable_rerank: bool = True
    enable_self_query: bool = True
    schema_id: int = 0


@router.post("")
async def create_knowledge_base(req: CreateKnowledgeBaseReq, request: Request):
    _require_tenant(req.tenant_id)
    # 查重
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
        enable_rerank=1 if req.enable_rerank else 0,
        enable_self_query=1 if req.enable_self_query else 0,
        schema_id=req.schema_id,
    )
    KnowledgeBaseDAO.insert(kb)
    logger.info("KB created: id=%s tenant=%s api_key=%s", kb.id, kb.tenant_id, kb.api_key)
    return {"id": kb.id, "api_key": kb.api_key, "name": kb.name}


@router.get("")
async def list_knowledge_bases(
    tenant_id: int = Query(..., gt=0),
    agent_name: str = Query(""),
    request: Request = None,
):
    provider = _get_provider(request)
    kbs = await provider.list_knowledge_bases(tenant_id, agent_name=agent_name)
    return {
        "items": [
            {
                "id": kb.id,
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


@router.delete("/{kb_id}")
async def delete_knowledge_base(kb_id: int):
    ok = KnowledgeBaseDAO.soft_delete(kb_id)
    if not ok:
        raise HTTPException(404, "知识库不存在")
    return {"deleted": True, "id": kb_id}


# ═══════════════════════════════════════════════════════════
# 2. Agent 授权绑定
# ═══════════════════════════════════════════════════════════

class BindAgentReq(BaseModel):
    tenant_id: int
    knowledge_base_id: int
    agent_name: str = Field(description="Agent 名称，传 * 表示全局可见")
    scope: str = Field(default="read", pattern="^(read|write)$")
    override_top_k: int = 0


@router.post("/bindings")
async def bind_agent(req: BindAgentReq):
    _require_tenant(req.tenant_id)
    # 检查 KB 是否存在
    kb = KnowledgeBaseDAO.get_by_id(req.knowledge_base_id)
    if kb is None or kb.tenant_id != req.tenant_id:
        raise HTTPException(404, "知识库不存在")

    binding = KnowledgeBaseBindingRow(
        tenant_id=req.tenant_id,
        knowledge_base_id=req.knowledge_base_id,
        agent_name=req.agent_name,
        scope=req.scope,
        override_top_k=req.override_top_k,
    )
    KnowledgeBaseBindingDAO.insert(binding)
    return {"id": binding.id, "agent_name": binding.agent_name}


@router.get("/bindings/{agent_name}")
async def list_bindings_for_agent(
    agent_name: str,
    tenant_id: int = Query(..., gt=0),
):
    kb_ids = KnowledgeBaseBindingDAO.list_kb_ids_for_agent(tenant_id, agent_name)
    return {"agent_name": agent_name, "knowledge_base_ids": kb_ids}


# ═══════════════════════════════════════════════════════════
# 3. 数据集 CRUD
# ═══════════════════════════════════════════════════════════

class CreateDatasetReq(BaseModel):
    tenant_id: int
    knowledge_base_id: int
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    chunk_strategy: str = Field(default="lkeap", pattern="^(lkeap|local_header|sliding_window)$")
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
    return {"id": ds.id, "name": ds.name}


@router.get("/datasets")
async def list_datasets(
    tenant_id: int = Query(..., gt=0),
    knowledge_base_id: int = Query(..., gt=0),
):
    rows = KnowledgeDatasetDAO.list_by_kb(tenant_id, knowledge_base_id)
    return {
        "items": [
            {
                "id": r.id, "name": r.name, "description": r.description,
                "chunk_strategy": r.chunk_strategy,
                "document_count": r.document_count,
                "chunk_count": r.chunk_count,
            }
            for r in rows
        ],
    }


# ═══════════════════════════════════════════════════════════
# 4. Schema CRUD（用于 Self-Querying + 自动打标）
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
    return {"id": row.id, "name": row.name}


@router.get("/schemas/for-kb/{kb_id}")
async def get_schema_for_kb(kb_id: int, tenant_id: int = Query(..., gt=0)):
    """获取 KB 专属 Schema，无则回退租户默认"""
    row = KnowledgeSchemaDAO.get_for_kb(tenant_id, kb_id)
    if row is None:
        return {"fields": []}
    try:
        fields = json.loads(row.fields or "[]")
    except json.JSONDecodeError:
        fields = []
    return {
        "id": row.id,
        "name": row.name,
        "version": row.version,
        "fields": fields,
    }


# ═══════════════════════════════════════════════════════════
# 5. 文档上传 / 列表 / 详情 / 删除
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

    # 保存到临时文件（provider 内部会拷贝到 upload_dir）
    suffix = os.path.splitext(file.filename or "")[1] or ""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = await provider.ingest_document(
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
            file_path=tmp_path,
            file_name=file.filename or os.path.basename(tmp_path),
            user_metadata={"title": title} if title else None,
            dataset_id=dataset_id,
        )
        return {
            "task_id": result.task_id,
            "doc_id": result.doc_id,
            "status": result.status,
            "reused": result.reused,
            "message": result.message,
        }
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.get("/documents")
async def list_documents(
    tenant_id: int = Query(..., gt=0),
    knowledge_base_id: int = Query(..., gt=0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    rows = KnowledgeDocumentDAO.list_by_kb(tenant_id, knowledge_base_id, limit, offset)
    return {
        "items": [_doc_row_to_dict(r) for r in rows],
        "total": len(rows),
    }


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str, request: Request):
    provider = _get_provider(request)
    info = await provider.get_document_info(doc_id)
    if info is None:
        raise HTTPException(404, "文档不存在")
    return {
        "doc_id": info.doc_id,
        "title": info.title,
        "file_name": info.file_name,
        "file_type": info.file_type,
        "knowledge_base_id": info.knowledge_base_id,
        "summary": info.summary,
        "chunk_count": info.chunk_count,
        "quality_score": info.quality_score,
        "metadata": info.metadata,
        "created_at": info.created_at,
    }


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str, request: Request,
    tenant_id: int = Query(..., gt=0),
):
    provider = _get_provider(request)
    ok = await provider.delete_document(tenant_id, doc_id)
    if not ok:
        raise HTTPException(404, "文档不存在或不属于该租户")
    return {"deleted": True, "doc_id": doc_id}


@router.get("/documents/{doc_id}/chunks")
async def list_chunks(doc_id: str, limit: int = Query(200, ge=1, le=1000)):
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


# ═══════════════════════════════════════════════════════════
# 6. 入库任务进度
# ═══════════════════════════════════════════════════════════

@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str, request: Request):
    provider = _get_provider(request)
    status = await provider.get_ingest_status(task_id)
    if status is None:
        raise HTTPException(404, "任务不存在")
    return status


# ═══════════════════════════════════════════════════════════
# 7. 检索审计反馈
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
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _kb_to_dict(kb: KnowledgeBaseRow) -> dict:
    return {
        "id": kb.id,
        "tenant_id": kb.tenant_id,
        "api_key": kb.api_key,
        "name": kb.name,
        "description": kb.description,
        "owner": kb.owner,
        "default_top_k": kb.default_top_k,
        "min_score": kb.min_score,
        "enable_rerank": bool(kb.enable_rerank),
        "enable_self_query": bool(kb.enable_self_query),
        "schema_id": kb.schema_id,
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
