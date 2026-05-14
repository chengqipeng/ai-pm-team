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
    """上传文档 → 存本地 → 入队 → 立即返回 task_id

    自动检测压缩包格式（ZIP/TAR 等），如果是压缩包则自动解压并批量入库。
    """
    from src.knowledge.archive_extractor import is_archive

    provider = _get_provider(request)

    # ── 前置校验 ──
    if not file or not file.filename:
        logger.warning("Upload rejected: empty file (tenant=%s kb=%s)", tenant_id, knowledge_base_id)
        raise HTTPException(400, "未提供有效文件")

    # ── 压缩包自动检测：转发到 archive 处理流程 ──
    if is_archive(file.filename):
        return await upload_archive(
            request=request,
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
            dataset_id=dataset_id,
            title=title,
            file=file,
        )

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


@router.post("/documents/upload-archive")
async def upload_archive(
    request: Request,
    tenant_id: int = Query(..., gt=0),
    knowledge_base_id: int = Query(..., gt=0),
    dataset_id: int = Query(0, ge=0),
    title: str = Query("", description="自定义标题前缀（可选，留空则使用原文件名）"),
    file: UploadFile = File(...),
):
    """上传压缩包（ZIP/TAR/TAR.GZ 等）→ 解压 → 遍历所有文档 → 逐一入库

    支持格式：.zip, .tar, .tar.gz, .tgz, .tar.bz2, .tar.xz, .rar, .gz
    压缩包内支持的文档格式：PDF/DOCX/PPTX/XLSX/MD/TXT/HTML/CSV 等

    返回：
        - total: 压缩包内文件总数
        - submitted: 成功提交入库的文件数
        - skipped: 跳过的不支持格式文件数
        - results: 每个文件的入库结果（task_id, doc_id, status）
    """
    from src.knowledge.archive_extractor import ArchiveExtractor, is_archive

    provider = _get_provider(request)

    # ── 前置校验 ──
    if not file or not file.filename:
        raise HTTPException(400, "未提供有效文件")

    if not is_archive(file.filename):
        raise HTTPException(
            400,
            f"不支持的压缩格式: {file.filename}。"
            "支持 ZIP/TAR/TAR.GZ/TGZ/TAR.BZ2/TAR.XZ/RAR/GZ",
        )

    kb = KnowledgeBaseDAO.get_by_id(knowledge_base_id)
    if kb is None or kb.tenant_id != tenant_id:
        raise HTTPException(404, f"知识库 id={knowledge_base_id} 不存在或不属于该租户")

    # ── 保存压缩包到临时文件 ──
    suffix = os.path.splitext(file.filename or "")[1] or ""
    # 处理 .tar.gz 等复合后缀
    if file.filename and file.filename.lower().endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
        suffix = "." + ".".join(file.filename.rsplit(".", 2)[-2:])

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        logger.info(
            "Archive upload received: tenant=%s kb=%s file=%s size=%d tmp=%s",
            tenant_id, knowledge_base_id, file.filename, len(content), tmp_path,
        )
    except Exception as exc:
        logger.exception(
            "Archive upload failed to save tmp: tenant=%s kb=%s file=%s: %s",
            tenant_id, knowledge_base_id, file.filename, exc,
        )
        raise HTTPException(500, f"临时文件写入失败: {exc}")

    # ── 解压 ──
    extractor = ArchiveExtractor()
    extract_result = extractor.extract(tmp_path, archive_name=file.filename)

    # 清理压缩包临时文件
    try:
        os.unlink(tmp_path)
    except OSError:
        pass

    if not extract_result.success:
        raise HTTPException(400, f"压缩包解压失败: {extract_result.error}")

    if not extract_result.files:
        extractor.cleanup(extract_result.extract_dir)
        raise HTTPException(
            400,
            f"压缩包内没有支持的文档文件。"
            f"跳过的文件: {extract_result.skipped_files[:10]}",
        )

    # ── 逐一提交入库 ──
    results: list[dict] = []
    submitted = 0
    errors: list[dict] = []

    try:
        for extracted_file in extract_result.files:
            # 构造文档标题：自定义前缀 + 压缩包内相对路径
            if title:
                doc_title = f"{title}/{extracted_file.relative_path}"
            else:
                doc_title = extracted_file.relative_path

            try:
                result = await provider.ingest_document(
                    tenant_id=tenant_id,
                    knowledge_base_id=knowledge_base_id,
                    file_path=extracted_file.file_path,
                    file_name=extracted_file.file_name,
                    user_metadata={
                        "title": doc_title,
                        "archive_source": file.filename,
                        "archive_path": extracted_file.relative_path,
                    },
                    dataset_id=dataset_id,
                )
                results.append({
                    "file_name": extracted_file.file_name,
                    "relative_path": extracted_file.relative_path,
                    "file_size": extracted_file.file_size,
                    "task_id": result.task_id,
                    "doc_id": result.doc_id,
                    "status": result.status,
                    "reused": result.reused,
                    "message": result.message,
                })
                submitted += 1
            except Exception as exc:
                logger.warning(
                    "Archive ingest failed for %s: %s",
                    extracted_file.relative_path, exc,
                )
                errors.append({
                    "file_name": extracted_file.file_name,
                    "relative_path": extracted_file.relative_path,
                    "error": str(exc),
                })
    finally:
        # 清理解压临时目录
        extractor.cleanup(extract_result.extract_dir)

    logger.info(
        "Archive upload complete: tenant=%s kb=%s archive=%s "
        "total=%d submitted=%d skipped=%d errors=%d",
        tenant_id, knowledge_base_id, file.filename,
        len(extract_result.files), submitted,
        len(extract_result.skipped_files), len(errors),
    )

    return {
        "archive_name": file.filename,
        "total_files": len(extract_result.files) + len(extract_result.skipped_files),
        "supported_files": len(extract_result.files),
        "submitted": submitted,
        "skipped": len(extract_result.skipped_files),
        "skipped_files": extract_result.skipped_files[:20],  # 最多返回 20 个
        "errors": errors,
        "results": results,
    }


@router.get("/documents")
async def list_documents(
    tenant_id: int = Query(..., gt=0),
    knowledge_base_id: int = Query(..., gt=0),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: str = Query("", max_length=200, description="按文档名称模糊搜索"),
):
    """文档列表（直接走 DAO，不依赖 provider）"""
    rows = KnowledgeDocumentDAO.list_by_kb(tenant_id, knowledge_base_id, limit, offset, search)
    total = KnowledgeDocumentDAO.count_by_kb(tenant_id, knowledge_base_id, search)
    return {
        "items": [_doc_row_to_dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
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


@router.get("/documents/{doc_id}/vector-status")
async def check_document_vector_status(
    doc_id: str,
    request: Request,
    tenant_id: int = Query(..., gt=0),
):
    """验证文档切片在 VDB 中的实际同步状态

    对比 PG 中的 vector_synced 标记与 VDB 中的实际数据，
    返回精确的同步状态统计。
    """
    provider = _get_provider(request)
    vdb = provider._vdb

    # 从 PG 查切片
    rows = KnowledgeChunkDAO.list_by_doc(doc_id)
    if not rows:
        return {"doc_id": doc_id, "status": "no_chunks", "pg_total": 0}

    pg_synced = sum(1 for r in rows if r.vector_synced == 1)
    pg_pending = sum(1 for r in rows if r.vector_synced == 0)
    pg_retry = sum(1 for r in rows if r.vector_synced == 2)
    pg_dead = sum(1 for r in rows if r.vector_synced == 3)

    # 验证 VDB 中实际存在的切片数
    vdb_count = 0
    vdb_error = ""
    try:
        from tcvectordb.model.document import Filter
        vdb._ensure_collections()
        vdb_filter = f'tenant_id = "{tenant_id}" and doc_id = "{doc_id}" and status = "active"'
        result = vdb._chunk_coll.query(
            filter=Filter(vdb_filter),
            output_fields=["id"],
            limit=min(len(rows) + 10, 1000),
        )
        if isinstance(result, list):
            vdb_count = len(result)
        else:
            vdb_count = len(vdb._parse_results(result))
    except Exception as exc:
        vdb_error = f"{type(exc).__name__}: {exc}"

    # 判断整体状态
    if vdb_error:
        overall = "vdb_error"
    elif vdb_count == len(rows):
        overall = "fully_synced"
    elif vdb_count > 0:
        overall = "partially_synced"
    else:
        overall = "not_in_vdb"

    return {
        "doc_id": doc_id,
        "status": overall,
        "pg_total": len(rows),
        "pg_synced": pg_synced,
        "pg_pending": pg_pending,
        "pg_retry": pg_retry,
        "pg_dead": pg_dead,
        "vdb_actual_count": vdb_count,
        "vdb_error": vdb_error,
        "match": vdb_count == pg_synced,
        "message": {
            "fully_synced": f"✅ 全部 {vdb_count} 个切片已同步到向量库",
            "partially_synced": f"⚠️ 部分同步：VDB 中有 {vdb_count}/{len(rows)} 个切片",
            "not_in_vdb": f"❌ 向量库中无数据（PG 标记已同步 {pg_synced} 个）",
            "vdb_error": f"⚠️ 向量库连接异常: {vdb_error}",
        }.get(overall, ""),
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


@router.get("/documents/{doc_id}/preview")
async def preview_document(
    doc_id: str,
    request: Request,
    tenant_id: int = Query(..., gt=0),
    expires: int = Query(3600, ge=300, le=86400, description="预签名 URL 有效期（秒），默认 1 小时"),
):
    """获取原文档预览 URL

    返回一个带签名的 COS 临时访问 URL，前端可直接用于：
    - PDF: 嵌入 <iframe> 或 PDF.js 渲染
    - 图片: 直接 <img src="...">
    - Office 文档: 可配合在线预览服务（如腾讯文档预览）

    签名 URL 有时效性（默认 1 小时），过期后需重新请求。
    """
    row = KnowledgeDocumentDAO.get_by_doc_id(doc_id)
    if row is None:
        raise HTTPException(404, "文档不存在")
    if row.tenant_id != tenant_id:
        raise HTTPException(403, "无权访问该文档")

    raw_url = row.raw_url
    if not raw_url:
        raise HTTPException(404, "文档原文件 URL 不存在（可能上传时未保存）")

    # 判断是否为 COS URL（以 https:// 开头且包含 .cos. 域名）
    is_cos_url = raw_url.startswith("https://") and ".cos." in raw_url

    if is_cos_url:
        # 从 app.state 获取 COS 客户端生成预签名 URL
        provider = getattr(request.app.state, "knowledge_provider", None)
        cos_client = getattr(provider, "_cos", None) if provider else None

        if cos_client is None:
            # COS 客户端未配置，直接返回原始 URL（适用于公开桶）
            logger.warning(
                "Preview: COS client not available, returning raw URL: doc=%s",
                doc_id,
            )
            return {
                "doc_id": doc_id,
                "file_name": row.file_name,
                "file_type": row.file_type,
                "file_size": row.file_size,
                "preview_url": raw_url,
                "url_type": "direct",
                "expires_in": None,
            }

        try:
            preview_url = cos_client.get_presigned_url_from_raw(raw_url, expires=expires)
        except ValueError as exc:
            logger.error(
                "Preview: failed to generate presigned URL: doc=%s raw_url=%s: %s",
                doc_id, raw_url[:80], exc,
            )
            raise HTTPException(
                500, f"生成预览 URL 失败: {exc}"
            )

        return {
            "doc_id": doc_id,
            "file_name": row.file_name,
            "file_type": row.file_type,
            "file_size": row.file_size,
            "preview_url": preview_url,
            "url_type": "presigned",
            "expires_in": expires,
        }
    else:
        # 本地路径 — 通过 StreamingResponse 直接返回文件内容
        from fastapi.responses import FileResponse

        if not os.path.exists(raw_url):
            raise HTTPException(404, "原文件已被删除或不可访问")

        # 推断 Content-Type
        import mimetypes
        content_type, _ = mimetypes.guess_type(row.file_name)
        if not content_type:
            content_type = "application/octet-stream"

        return FileResponse(
            path=raw_url,
            filename=row.file_name,
            media_type=content_type,
            headers={
                "Content-Disposition": f'inline; filename="{row.file_name}"',
            },
        )


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


class BatchDeleteRequest(BaseModel):
    """批量删除文档请求体"""
    tenant_id: int = Field(..., gt=0)
    doc_ids: list[str] = Field(..., min_length=1, max_length=100, description="要删除的文档 ID 列表，最多 100 个")


@router.post("/documents/batch-delete")
async def batch_delete_documents(
    request: Request,
    body: BatchDeleteRequest,
):
    """批量删除文档

    一次最多删除 100 个文档。返回每个文档的删除结果。
    """
    provider = _get_provider(request)

    results: list[dict] = []
    success_count = 0
    fail_count = 0

    for doc_id in body.doc_ids:
        try:
            ok = await provider.delete_document(body.tenant_id, doc_id)
            if ok:
                results.append({"doc_id": doc_id, "deleted": True})
                success_count += 1
            else:
                results.append({"doc_id": doc_id, "deleted": False, "error": "文档不存在或不属于该租户"})
                fail_count += 1
        except Exception as exc:
            logger.warning("Batch delete failed for doc_id=%s: %s", doc_id, exc)
            results.append({"doc_id": doc_id, "deleted": False, "error": str(exc)})
            fail_count += 1

    return {
        "total": len(body.doc_ids),
        "success": success_count,
        "failed": fail_count,
        "results": results,
    }


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
    document_count 返回实时统计（含所有未删除文档），确保删除后前端立即看到变化。
    chunk_count 使用缓存值（仅统计已入库成功的切片）。
    """
    _require_tenant(tenant_id)
    kbs = KnowledgeBaseDAO.list_by_tenant(tenant_id)
    items = []
    for kb in kbs:
        # 实时查询文档总数（包含处理中的），确保删除后前端立即看到变化
        real_doc_count = KnowledgeDocumentDAO.count_by_kb(tenant_id, kb.id)
        # 实时查询切片总数（从文档表 SUM chunk_count）
        real_chunk_count = KnowledgeDocumentDAO.sum_chunks_by_kb(tenant_id, kb.id)
        items.append({
            "id": str(kb.id),
            "api_key": kb.api_key,
            "name": kb.name,
            "description": kb.description,
            "default_top_k": kb.default_top_k,
            "document_count": real_doc_count,
            "chunk_count": real_chunk_count,
        })
    return {"items": items}


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


# ═══════════════════════════════════════════════════════════
# 7. 向量补偿（/maintenance/resync-vectors）
# ═══════════════════════════════════════════════════════════

@router.post("/maintenance/resync-vectors")
async def resync_vectors(
    request: Request,
    tenant_id: int = Query(..., gt=0),
    knowledge_base_id: int = Query(..., gt=0),
    doc_id: str = Query("", description="指定单个文档 ID（留空则处理整个知识库）"),
):
    """向量补偿 — 对 PG 中已有切片但 VDB 中缺失的文档重新执行 Phase 4（向量化+写入VDB）

    适用场景：
    - 文档显示"已入库"但检索不到
    - VDB 被清空/重建后需要重新同步
    - Phase 4 曾经失败（vector_synced=0/2/3）

    流程：
    1. 查 PG 中该 KB 下所有文档（或指定单个文档）
    2. 对每个文档的 chunks 检查 vector_synced 状态
    3. 对未同步的 chunks 重新 embedding + 写入 VDB
    4. 重建 doc_metadata（摘要向量 + BM25 文本）
    """
    logger.warning(
        "resync-vectors start: tenant=%s kb=%s doc_id=%s",
        tenant_id, knowledge_base_id, doc_id or "(all)",
    )
    import asyncio

    provider = _get_provider(request)
    vdb = provider._vdb

    # 获取 embedding 函数
    retriever = provider._retriever
    embedding_fn = retriever._embedding_fn
    lkeap = retriever._lkeap

    async def embed_texts(texts: list[str]) -> list[list[float]]:
        """批量 embedding — 分批处理避免超时"""
        if not texts:
            return []

        if embedding_fn:
            if asyncio.iscoroutinefunction(embedding_fn):
                results = []
                for t in texts:
                    results.append(await embedding_fn(t))
                return results
            else:
                results = []
                for t in texts:
                    results.append(await asyncio.to_thread(embedding_fn, t))
                return results
        elif lkeap:
            # LKEAP 单次只接受 1 个 Input，逐条调用但用有界并发加速
            concurrency = 2
            sem = asyncio.Semaphore(concurrency)
            results: list[list[float]] = [None] * len(texts)  # type: ignore

            async def _embed_one(idx: int, text: str):
                async with sem:
                    vecs = await asyncio.to_thread(lkeap.get_embedding, [text])
                    results[idx] = vecs[0] if vecs and vecs[0] else []

            await asyncio.gather(*(_embed_one(i, t) for i, t in enumerate(texts)))
            return results
        else:
            raise HTTPException(503, "Embedding 服务未配置（embedding_fn 和 lkeap 均为 None）")

    # 1. 查该 KB 下的所有文档（或指定单个文档）
    if doc_id:
        single_doc = KnowledgeDocumentDAO.get_by_doc_id(doc_id)
        if single_doc is None:
            raise HTTPException(404, f"文档 {doc_id} 不存在")
        docs = [single_doc]
    else:
        docs = KnowledgeDocumentDAO.list_by_kb(tenant_id, knowledge_base_id, limit=200, offset=0)
    if not docs:
        return {"status": "no_docs", "message": "该知识库无文档", "synced": 0}

    logger.warning("resync-vectors: found %d docs to process", len(docs))

    # 预检：验证 VDB 连接可用
    try:
        vdb._ensure_collections()
        logger.warning("resync-vectors: VDB connection OK")
    except Exception as exc:
        logger.exception("resync-vectors: VDB connection failed: %s", exc)
        raise HTTPException(503, f"向量数据库连接失败: {type(exc).__name__}: {exc}")

    total_chunks_synced = 0
    total_docs_processed = 0
    errors: list[str] = []

    for doc in docs:
        current_doc_id = doc.doc_id
        # 2. 查该文档的所有 chunks
        chunks = KnowledgeChunkDAO.list_by_doc(current_doc_id)
        if not chunks:
            continue

        # 3. 筛选需要同步的 chunks（vector_synced != 1，或者强制全量重建）
        pending_chunks = [c for c in chunks if c.vector_synced != 1]
        # 如果所有 chunks 都已同步，检查 VDB 中是否真的有数据
        if not pending_chunks:
            # 验证 VDB 中是否存在
            try:
                from tcvectordb.model.document import Filter
                vdb._ensure_collections()
                check_filter = (
                    f'tenant_id = "{tenant_id}" and doc_id = "{current_doc_id}" and status = "active"'
                )
                check_result = vdb._chunk_coll.query(
                    filter=Filter(check_filter),
                    output_fields=["id"],
                    limit=1,
                )
                vdb_has_data = bool(check_result) and (
                    len(check_result) > 0 if isinstance(check_result, list)
                    else len(vdb._parse_results(check_result)) > 0
                )
            except Exception:
                vdb_has_data = False

            if vdb_has_data:
                continue  # VDB 中确实有数据，跳过
            else:
                # VDB 中没有但 PG 标记已同步 → 需要全量重建
                pending_chunks = chunks

        # 4. 对 pending_chunks 执行 embedding + 写入 VDB
        try:
            logger.warning(
                "resync-vectors: processing doc=%s chunks=%d (pending=%d)",
                current_doc_id, len(chunks), len(pending_chunks),
            )
            texts = [c.content[:2000] for c in pending_chunks]
            vectors = await embed_texts(texts)

            chunk_records: list[dict] = []
            synced_ids: list[str] = []
            for c, vec in zip(pending_chunks, vectors):
                if not vec:
                    continue
                chunk_records.append({
                    "id": c.chunk_id,
                    "vector": vec,
                    "tenant_id": str(c.tenant_id),
                    "knowledge_base_id": str(c.knowledge_base_id),
                    "dataset_id": str(c.dataset_id),
                    "doc_id": c.doc_id,
                    "chunk_type": c.chunk_type,
                    "doc_category": c.doc_category or "",
                    "industry": c.industry or "",
                    "business_stage": c.business_stage or "",
                    "target_audience": c.target_audience or "",
                    "product_service": c.product_service or "",
                    "status": "active",
                    "date_published": c.date_published or 0,
                    "content": c.content[:8000],
                    "section_title": c.section_title or "",
                    "chunk_index": c.chunk_index,
                })
                synced_ids.append(c.chunk_id)

            if chunk_records:
                # 分批写入 VDB（每批 20 条，避免单次请求过大超时）
                batch_size = 20
                for batch_start in range(0, len(chunk_records), batch_size):
                    batch = chunk_records[batch_start:batch_start + batch_size]
                    await asyncio.to_thread(vdb.upsert_chunks, batch)
                # 更新 PG 中的 vector_synced 状态
                dim = len(vectors[0]) if vectors and vectors[0] else 0
                await asyncio.to_thread(
                    KnowledgeChunkDAO.mark_vector_synced,
                    synced_ids, "resync/manual", dim,
                )
                total_chunks_synced += len(synced_ids)

            # 5. 重建 doc_metadata（摘要向量）
            summary = doc.summary or ""
            if summary:
                summary_vecs = await embed_texts([summary])
                summary_vec = summary_vecs[0] if summary_vecs else None
            else:
                # 无摘要时用文档前 500 字作为替代
                fallback_text = pending_chunks[0].content[:500] if pending_chunks else ""
                if fallback_text:
                    summary_vecs = await embed_texts([fallback_text])
                    summary_vec = summary_vecs[0] if summary_vecs else None
                else:
                    summary_vec = None

            if summary_vec:
                # 构建 doc_metadata 记录
                keywords_str = doc.keywords or ""
                candidate_str = doc.candidate_keywords or ""
                try:
                    keywords_list = json.loads(keywords_str) if keywords_str else []
                except (json.JSONDecodeError, TypeError):
                    keywords_list = []
                try:
                    candidates_list = json.loads(candidate_str) if candidate_str else []
                except (json.JSONDecodeError, TypeError):
                    candidates_list = []

                # 构建 toc（从 chunks 的 section_title 聚合）
                toc_parts = []
                seen_sections = set()
                for c in chunks:
                    if c.section_title and c.section_title not in seen_sections:
                        toc_parts.append(c.section_title)
                        seen_sections.add(c.section_title)
                toc = " > ".join(toc_parts) if toc_parts else ""

                doc_meta_record = {
                    "id": current_doc_id,
                    "vector": summary_vec,
                    "tenant_id": str(tenant_id),
                    "knowledge_base_id": str(knowledge_base_id),
                    "dataset_id": str(doc.dataset_id) if hasattr(doc, 'dataset_id') else "0",
                    "title": doc.title or doc.file_name or "",
                    "summary": summary[:2000],
                    "keywords": ", ".join(keywords_list) if keywords_list else "",
                    "candidate_keywords": ", ".join(candidates_list[:20]) if candidates_list else "",
                    "toc": toc[:2000],
                    "doc_category": "",
                    "industry": "",
                    "business_stage": "",
                    "target_audience": "",
                    "product_service": "",
                    "status": "active",
                    "quality_score_x10k": int((doc.quality_score or 0.5) * 10000),
                    "date_published": doc.created_at or 0,
                    "created_at": doc.created_at or 0,
                    "search_hit_count": 0,
                }

                # 从 metadata JSON 中提取 Schema 字段
                try:
                    md = json.loads(doc.metadata) if doc.metadata else {}
                    doc_meta_record["doc_category"] = md.get("docCategory", "")
                    doc_meta_record["industry"] = md.get("industryVertical", "")
                    doc_meta_record["business_stage"] = md.get("businessStage", "")
                    doc_meta_record["target_audience"] = md.get("targetAudience", "")
                    doc_meta_record["product_service"] = md.get("productService", "")
                except (json.JSONDecodeError, TypeError):
                    pass

                await asyncio.to_thread(vdb.upsert_doc_metadata, [doc_meta_record])

            total_docs_processed += 1

        except Exception as exc:
            err_msg = f"doc={current_doc_id} ({doc.title}): {type(exc).__name__}: {exc}"
            errors.append(err_msg)
            logger.exception("resync-vectors failed for %s: %s", current_doc_id, exc)

    result = {
        "status": "success" if not errors else "partial",
        "total_docs": len(docs),
        "docs_processed": total_docs_processed,
        "chunks_synced": total_chunks_synced,
        "errors": errors[:10],  # 最多返回 10 条错误
    }
    logger.warning(
        "resync-vectors done: tenant=%s kb=%s docs=%d chunks=%d errors=%d",
        tenant_id, knowledge_base_id, total_docs_processed, total_chunks_synced, len(errors),
    )
    return result


@router.delete("/{kb_id}")
async def delete_knowledge_base(kb_id: int):
    ok = KnowledgeBaseDAO.soft_delete(kb_id)
    if not ok:
        raise HTTPException(404, "知识库不存在")
    return {"deleted": True, "id": str(kb_id)}
