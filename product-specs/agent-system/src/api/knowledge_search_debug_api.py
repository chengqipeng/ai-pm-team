"""知识库检索调试 API — 完整链路可视化

提供类似对话框的检索调试界面后端支持，返回完整的检索链路节点：
    1. 用户问题（原始输入）
    2. 查询改写（Query Rewrite）
    3. Self-Querying 关键字/过滤条件提取
    4. 多路召回详情（向量 + BM25 + 文档元数据）
    5. 命中分片列表（含原始分数）
    6. RRF 排序详情（三维度归一化加权）
    7. 最终排序结果（命中文档 + 综合分数）
    8. 回答生成建议（基于命中内容的上下文）

路由前缀：/api/knowledge/search-debug
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.store.knowledge_dao import (
    KnowledgeBaseDAO,
    KnowledgeSchemaDAO,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge/search-debug", tags=["knowledge-search-debug"])


# ═══════════════════════════════════════════════════════════
# 请求/响应模型
# ═══════════════════════════════════════════════════════════

class SearchDebugRequest(BaseModel):
    """检索调试请求"""
    tenant_id: int = Field(..., gt=0)
    knowledge_base_id: int = Field(..., gt=0)
    query: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    top_k: int = Field(default=5, ge=1, le=50)
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    enable_self_query: bool = Field(default=True, description="是否启用 Self-Querying")
    enable_rerank: bool = Field(default=True, description="是否启用重排序")
    conversation_history: list[dict] | None = Field(default=None, description="对话历史（用于查询改写）")


class PipelineNode(BaseModel):
    """流水线节点"""
    step: int
    name: str
    name_en: str
    status: str = "success"  # success / skipped / failed
    duration_ms: int = 0
    input_data: Any = None
    output_data: Any = None
    detail: str = ""


class ChunkHit(BaseModel):
    """命中分片"""
    chunk_id: str
    doc_id: str
    document_title: str = ""
    content: str
    section_title: str = ""
    chunk_type: str = "Text"
    chunk_index: int = 0
    raw_score: float = 0.0
    final_score: float = 0.0
    metadata: dict = Field(default_factory=dict)


class RRFDetail(BaseModel):
    """RRF 排序详情"""
    doc_id: str
    document_title: str = ""
    alpha_score: float = 0.0  # 维度 A：切片 RRF 聚合
    beta_score: float = 0.0   # 维度 B：文档元数据 RRF
    gamma_score: float = 0.0  # 维度 C：文档属性（质量+时效+热度）
    final_score: float = 0.0
    chunk_count: int = 0
    alpha_detail: str = ""
    beta_detail: str = ""
    gamma_detail: str = ""


class SearchDebugResponse(BaseModel):
    """检索调试响应 — 完整链路"""
    trace_id: str
    total_duration_ms: int
    pipeline_nodes: list[PipelineNode]
    chunk_hits: list[ChunkHit]
    rrf_details: list[RRFDetail]
    final_answer_context: str = ""
    summary: str = ""


# ═══════════════════════════════════════════════════════════
# 调试检索 API
# ═══════════════════════════════════════════════════════════

@router.post("", response_model=SearchDebugResponse)
async def search_with_debug(req: SearchDebugRequest, request: Request):
    """执行检索并返回完整链路调试信息

    与普通 search 不同，此接口：
    - 返回每个步骤的输入/输出/耗时
    - 返回所有命中分片的原始分数和最终分数
    - 返回 RRF 三维度打分详情
    - 返回可用于回答的上下文拼接
    """
    provider = _get_provider(request)
    retriever = provider._retriever

    trace_id = f"dbg_{uuid.uuid4().hex[:16]}"
    t_start = time.time()
    nodes: list[PipelineNode] = []

    # ── Node 1: 用户问题 ──
    nodes.append(PipelineNode(
        step=1,
        name="用户问题",
        name_en="user_query",
        input_data={"query": req.query, "conversation_history": req.conversation_history},
        output_data={"query": req.query},
        detail=f"原始用户输入：{req.query}",
    ))

    # ── Node 2: 查询改写 + 关键词提取 ──
    t0 = time.time()
    rewritten_query = req.query
    extracted_keywords: list[str] = []
    rewrite_raw = ""
    rewrite_status = "skipped"

    if retriever._llm:
        try:
            rw_result = await retriever._rewrite_query(
                req.query, req.conversation_history,
            )
            rewritten_query = rw_result.get("rewritten_query", req.query)
            extracted_keywords = rw_result.get("keywords", [])
            rewrite_raw = json.dumps(rw_result, ensure_ascii=False)
            rewrite_status = "success"
        except Exception as exc:
            rewrite_status = "failed"
            rewrite_raw = str(exc)
    else:
        # 无 LLM 时用本地关键词提取
        extracted_keywords = retriever._local_keywords(req.query)
        rewrite_raw = f"LLM 未注入，使用本地 jieba 关键词提取: {extracted_keywords}"
        rewrite_status = "success" if extracted_keywords else "skipped"

    nodes.append(PipelineNode(
        step=2,
        name="查询改写与关键词提取",
        name_en="query_rewrite",
        status=rewrite_status,
        duration_ms=int((time.time() - t0) * 1000),
        input_data={
            "original_query": req.query,
            "conversation_history": req.conversation_history,
            "has_llm": retriever._llm is not None,
        },
        output_data={
            "rewritten_query": rewritten_query,
            "keywords": extracted_keywords,
            "changed": rewritten_query != req.query,
        },
        detail=rewrite_raw if len(rewrite_raw) < 500 else rewrite_raw[:500] + "...",
    ))

    # ── Node 3: Self-Querying（关键字提取 + 过滤条件） ──
    t0 = time.time()
    semantic_query = rewritten_query
    extracted_filters: dict = {}
    self_query_raw = ""

    if req.enable_self_query and retriever._llm:
        try:
            sq_result = await retriever._self_query(
                rewritten_query, req.tenant_id, req.knowledge_base_id,
            )
            semantic_query = sq_result.get("semantic_query", rewritten_query)
            extracted_filters = sq_result.get("filters") or {}
            self_query_raw = json.dumps(sq_result, ensure_ascii=False)
            sq_status = "success"
        except Exception as exc:
            sq_status = "failed"
            self_query_raw = str(exc)
    else:
        sq_status = "skipped"
        self_query_raw = "LLM 未注入或 Self-Querying 未启用"

    nodes.append(PipelineNode(
        step=3,
        name="关键字提取与过滤条件",
        name_en="self_querying",
        status=sq_status,
        duration_ms=int((time.time() - t0) * 1000),
        input_data={"query": rewritten_query, "enable_self_query": req.enable_self_query},
        output_data={
            "semantic_query": semantic_query,
            "extracted_filters": extracted_filters,
        },
        detail=self_query_raw,
    ))

    # ── Node 4-1: Embedding + 切片级混合检索（dense + BM25） ──
    t0 = time.time()
    filter_expr = retriever._build_chunk_filter(req.knowledge_base_id, extracted_filters)
    doc_filter = retriever._build_doc_filter(req.knowledge_base_id, extracted_filters)
    chunk_limit = max(req.top_k * 5, 30)
    doc_limit = max(req.top_k * 5, 50)

    # Embedding
    query_vec: list[float] = []
    embed_status = "success"
    embed_error = ""
    embed_ms = 0
    t_embed = time.time()
    try:
        query_vec = await retriever._embed(semantic_query)
    except Exception as exc:
        embed_status = "failed"
        embed_error = f"{type(exc).__name__}: {exc}"
        logger.warning("Debug search embedding failed: %s", exc)
    embed_ms = int((time.time() - t_embed) * 1000)

    # A 路：切片级 hybrid_search
    chunk_results: list[dict] = []
    chunk_recall_error = ""
    t_chunk = time.time()
    try:
        chunk_results_raw = await retriever._recall_chunks(
            req.tenant_id, query_vec, semantic_query, filter_expr, chunk_limit,
        )
        if isinstance(chunk_results_raw, Exception):
            chunk_recall_error = f"{type(chunk_results_raw).__name__}: {chunk_results_raw}"
        else:
            chunk_results = chunk_results_raw
    except Exception as exc:
        chunk_recall_error = f"{type(exc).__name__}: {exc}"
    chunk_recall_ms = int((time.time() - t_chunk) * 1000)
    step4_1_ms = int((time.time() - t0) * 1000)

    nodes.append(PipelineNode(
        step=4,
        name="切片混合检索 (向量+BM25)",
        name_en="chunk_hybrid_search",
        status="success" if chunk_results else ("failed" if embed_status == "failed" or chunk_recall_error else "skipped"),
        duration_ms=step4_1_ms,
        input_data={
            "semantic_query": semantic_query,
            "filter": filter_expr,
            "embedding_dim": len(query_vec),
            "embedding_status": embed_status,
            "embedding_error": embed_error,
            "embedding_ms": embed_ms,
            "chunk_limit": chunk_limit,
            "dense_weight": 0.3,
            "sparse_weight": 0.7,
        },
        output_data={
            "hits": len(chunk_results),
            "error": chunk_recall_error,
            "recall_ms": chunk_recall_ms,
            "top5_scores": [round(r.get("score", 0), 4) for r in chunk_results[:5]],
        },
        detail=(
            f"Embedding {embed_ms}ms (dim={len(query_vec)}) → "
            f"VDB hybrid_search {chunk_recall_ms}ms → 命中 {len(chunk_results)} 条切片"
            + (f"\n❌ {chunk_recall_error}" if chunk_recall_error else "")
        ),
    ))

    # ── Node 4-2: 文档级元数据检索（摘要向量 ANN + 加权文本 BM25） ──
    t0 = time.time()
    doc_meta_hybrid: list[dict] = []
    doc_recall_error = ""
    try:
        doc_meta_raw = await retriever._recall_doc_metadata_hybrid(
            req.tenant_id, query_vec, semantic_query, doc_filter, doc_limit,
        )
        if isinstance(doc_meta_raw, Exception):
            doc_recall_error = f"{type(doc_meta_raw).__name__}: {doc_meta_raw}"
        else:
            doc_meta_hybrid = doc_meta_raw
    except Exception as exc:
        doc_recall_error = f"{type(exc).__name__}: {exc}"
    step4_2_ms = int((time.time() - t0) * 1000)

    doc_meta_rank = [r.get("id", "") for r in doc_meta_hybrid if r.get("id")]

    nodes.append(PipelineNode(
        step=5,
        name="文档元数据检索 (摘要ANN+BM25)",
        name_en="doc_metadata_hybrid",
        status="success" if doc_meta_hybrid else ("failed" if doc_recall_error else "skipped"),
        duration_ms=step4_2_ms,
        input_data={
            "semantic_query": semantic_query,
            "filter": doc_filter,
            "doc_limit": doc_limit,
            "dense_weight": 0.5,
            "sparse_weight": 0.5,
            "bm25_fields": "title×3 + summary×2 + keywords×2 + candidate×1 + toc×1",
        },
        output_data={
            "hits": len(doc_meta_rank),
            "error": doc_recall_error,
            "matched_doc_ids": doc_meta_rank[:5],
        },
        detail=(
            f"文档级 hybrid_search → 命中 {len(doc_meta_rank)} 个文档"
            + (f"\n❌ {doc_recall_error}" if doc_recall_error else "")
        ),
    ))

    # 安全机制：如果有过滤条件但召回为 0，去掉过滤重试
    filter_fallback_used = False
    if not chunk_results and extracted_filters and query_vec:
        fallback_filter = retriever._build_chunk_filter(req.knowledge_base_id, {})
        fallback_doc_filter = retriever._build_doc_filter(req.knowledge_base_id, {})
        try:
            fb_chunks, fb_docs = await asyncio.gather(
                retriever._recall_chunks(
                    req.tenant_id, query_vec, semantic_query, fallback_filter, chunk_limit,
                ),
                retriever._recall_doc_metadata_hybrid(
                    req.tenant_id, query_vec, semantic_query, fallback_doc_filter, doc_limit,
                ),
                return_exceptions=True,
            )
            if not isinstance(fb_chunks, Exception) and fb_chunks:
                chunk_results = fb_chunks
                filter_fallback_used = True
            if not isinstance(fb_docs, Exception) and fb_docs:
                doc_meta_hybrid = fb_docs
                doc_meta_rank = [r.get("id", "") for r in doc_meta_hybrid if r.get("id")]
        except Exception:
            pass
        if filter_fallback_used:
            # 追加一个降级说明节点
            nodes.append(PipelineNode(
                step=5,
                name="过滤降级重试",
                name_en="filter_fallback",
                status="success" if chunk_results else "failed",
                duration_ms=0,
                input_data={"reason": "原始过滤条件导致召回为空", "removed_filters": extracted_filters},
                output_data={"chunk_hits_after_fallback": len(chunk_results)},
                detail=f"⚠️ 去掉过滤条件后重试，召回 {len(chunk_results)} 条切片",
            ))

    # 诊断信息：当召回为 0 时，检查 VDB 中是否有该 KB 的数据
    vdb_diagnosis = ""
    vdb_chunk_count = -1
    vdb_doc_count = -1
    pg_chunk_stats: dict = {}
    if not chunk_results and not doc_meta_hybrid:
        try:
            vdb = retriever._vdb
            vdb_doc_count = vdb.count_docs(str(req.tenant_id))
            from tcvectordb.model.document import Filter
            vdb._ensure_collections()
            kb_filter = f'tenant_id = "{req.tenant_id}" and knowledge_base_id = "{req.knowledge_base_id}" and status = "active"'
            try:
                chunk_query_result = vdb._chunk_coll.query(
                    filter=Filter(kb_filter),
                    output_fields=["id"],
                    limit=5,
                )
                if isinstance(chunk_query_result, list):
                    vdb_chunk_count = len(chunk_query_result)
                else:
                    vdb_chunk_count = len(vdb._parse_results(chunk_query_result))
            except Exception as e2:
                vdb_chunk_count = -1
                vdb_diagnosis += f"VDB chunk query error: {e2}; "

            try:
                from src.store.knowledge_dao import KnowledgeChunkDAO, KnowledgeDocumentDAO
                docs = KnowledgeDocumentDAO.list_by_kb(
                    req.tenant_id, req.knowledge_base_id, limit=10, offset=0,
                )
                if docs:
                    total_chunks_in_pg = 0
                    synced_count = 0
                    not_synced_count = 0
                    failed_count = 0
                    for doc in docs:
                        chunks_in_doc = KnowledgeChunkDAO.list_by_doc(doc.doc_id)
                        for c in chunks_in_doc:
                            total_chunks_in_pg += 1
                            if c.vector_synced == 1:
                                synced_count += 1
                            elif c.vector_synced == 0:
                                not_synced_count += 1
                            elif c.vector_synced in (2, 3):
                                failed_count += 1
                    pg_chunk_stats = {
                        "total_docs_in_pg": len(docs),
                        "total_chunks_in_pg": total_chunks_in_pg,
                        "vector_synced": synced_count,
                        "vector_not_synced": not_synced_count,
                        "vector_failed": failed_count,
                    }
                else:
                    pg_chunk_stats = {"total_docs_in_pg": 0}
            except Exception as pg_exc:
                pg_chunk_stats = {"error": str(pg_exc)}

            if vdb_chunk_count == 0:
                total_pg = pg_chunk_stats.get("total_chunks_in_pg", 0)
                synced = pg_chunk_stats.get("vector_synced", 0)
                not_synced = pg_chunk_stats.get("vector_not_synced", 0)
                failed = pg_chunk_stats.get("vector_failed", 0)
                if total_pg == 0:
                    vdb_diagnosis += "⚠️ PG 中该知识库也无切片数据。文档可能未完成入库流水线。"
                elif not_synced > 0 or failed > 0:
                    vdb_diagnosis += f"⚠️ PG 有 {total_pg} 切片，已同步={synced}, 未同步={not_synced}, 失败={failed}。需要执行向量补偿。"
                elif synced > 0:
                    vdb_diagnosis += f"⚠️ PG 标记已同步 {synced} 切片，但 VDB 中无数据。VDB 可能被清空，需要重建。"
            elif vdb_chunk_count > 0 and embed_status == "failed":
                vdb_diagnosis += f"VDB 有 {vdb_chunk_count} 切片，但 Embedding 失败：{embed_error}"
        except Exception as diag_exc:
            vdb_diagnosis += f"诊断异常: {diag_exc}"

        # 诊断节点
        if vdb_diagnosis:
            nodes.append(PipelineNode(
                step=5,
                name="召回诊断",
                name_en="recall_diagnosis",
                status="failed",
                input_data={"vdb_chunk_count": vdb_chunk_count, "pg_chunk_stats": pg_chunk_stats},
                output_data={"diagnosis": vdb_diagnosis},
                detail=vdb_diagnosis,
            ))

    # ── Node 6: Hydrate（切片内容填充） ──
    t0 = time.time()
    chunks = await retriever._hydrate_and_expand(chunk_results, req.tenant_id)
    hydrate_ms = int((time.time() - t0) * 1000)

    # 构建命中分片列表（含原始分数）
    chunk_hits: list[ChunkHit] = []
    for c in chunks:
        chunk_hits.append(ChunkHit(
            chunk_id=c.chunk_id,
            doc_id=c.document_id,
            document_title=c.document_title,
            content=c.content[:500],  # 截断避免响应过大
            section_title=c.section_title,
            chunk_type=c.chunk_type,
            chunk_index=c.chunk_index,
            raw_score=round(c.score, 6),
            metadata=c.metadata,
        ))

    nodes.append(PipelineNode(
        step=6,
        name="命中分片详情",
        name_en="chunk_hydration",
        status="success" if chunks else "skipped",
        duration_ms=hydrate_ms,
        input_data={"raw_chunk_count": len(chunk_results)},
        output_data={
            "hydrated_chunks": len(chunks),
            "unique_docs": len({c.document_id for c in chunks}),
            "top5_raw_scores": [round(c.score, 4) for c in sorted(chunks, key=lambda x: x.score, reverse=True)[:5]],
        },
        detail=f"填充 {len(chunks)} 个切片内容，涉及 {len({c.document_id for c in chunks})} 个文档",
    ))

    # ── Node 6: RRF 三维度打分 ──
    t0 = time.time()
    rrf_details: list[RRFDetail] = []

    if chunks:
        # 复现 retriever._score_and_rank 的内部逻辑以获取中间值
        doc_cache = await retriever._load_doc_meta_cache(chunks, req.tenant_id)

        # 切片 RRF
        chunks_sorted = sorted(chunks, key=lambda c: c.score, reverse=True)
        chunk_rrf: dict[str, float] = {}
        for rank, c in enumerate(chunks_sorted):
            if c.chunk_id:
                chunk_rrf[c.chunk_id] = 1.0 / (retriever._K_CHUNK + rank + 1)

        # 按 doc 分组聚合
        doc_chunks: dict[str, list[tuple[Any, float]]] = {}
        for c in chunks:
            did = c.document_id
            if not did:
                continue
            rrf = chunk_rrf.get(c.chunk_id, 0.0)
            doc_chunks.setdefault(did, []).append((c, rrf))

        doc_rrf: dict[str, float] = {}
        for did, items in doc_chunks.items():
            items.sort(key=lambda x: x[1], reverse=True)
            agg = items[0][1]
            for i in range(1, len(items)):
                agg += items[i][1] * math.pow(retriever._CHUNK_DECAY, i)
            doc_rrf[did] = agg

        # 维度 A 归一化
        floor = retriever._NORM_FLOOR
        max_rrf = max(doc_rrf.values()) if doc_rrf else 0
        min_rrf = min(doc_rrf.values()) if doc_rrf else 0
        rrf_range = max_rrf - min_rrf

        doc_norm_a: dict[str, float] = {}
        for did, score in doc_rrf.items():
            if rrf_range > 0:
                doc_norm_a[did] = (score - min_rrf) / rrf_range * (1.0 - floor) + floor
            else:
                items = doc_chunks.get(did, [])
                if items:
                    avg = sum(c.score for c, _ in items) / len(items)
                    avg = max(0.0, min(1.0, avg))
                    doc_norm_a[did] = avg * (1.0 - floor) + floor
                else:
                    doc_norm_a[did] = (1.0 + floor) / 2.0

        # 维度 B
        doc_norm_b: dict[str, float] = {}
        for did in doc_chunks.keys():
            boost = 0.0
            try:
                idx_s = doc_meta_rank.index(did)
                boost += 1.0 / (retriever._K_SUMMARY + idx_s + 1)
            except ValueError:
                pass
            try:
                idx_m = doc_meta_rank.index(did)
                boost += 1.0 / (retriever._K_META_TEXT + idx_m + 1)
            except ValueError:
                pass
            boost *= retriever._METADATA_WEIGHT
            doc_norm_b[did] = (
                min(boost / retriever._MAX_METADATA_BOOST, 1.0)
                if retriever._MAX_METADATA_BOOST > 0 else 0.0
            )

        # 维度 C
        now_ms = int(time.time() * 1000)
        doc_norm_c: dict[str, float] = {}
        for did in doc_chunks.keys():
            meta = doc_cache.get(did) or {}
            if "quality_score_x10k" in meta:
                quality = float(meta.get("quality_score_x10k") or 0) / 10000.0
            else:
                quality = float(meta.get("quality_score") or 0.5)
            quality = max(0.0, min(1.0, quality)) if quality else 0.5
            recency = 0.5
            ref_ts = int(meta.get("date_published") or 0) or int(meta.get("created_at") or 0)
            if ref_ts and ref_ts > 0:
                age_ms = max(0, now_ms - ref_ts)
                recency = math.pow(0.5, age_ms / retriever._RECENCY_HALFLIFE_MS)
            hit_score = 0.0
            hit = int(meta.get("search_hit_count") or 0)
            if hit > 0:
                hit_score = min(1.0, math.log10(hit + 1) / math.log10(1000))
            boost = (
                quality * retriever._QUALITY_WEIGHT
                + recency * retriever._RECENCY_WEIGHT
                + hit_score * retriever._HIT_WEIGHT
            )
            doc_norm_c[did] = min(boost / retriever._MAX_ATTR_BOOST, 1.0)

        # 计算 finalScore 并构建详情
        doc_titles: dict[str, str] = {}
        for c in chunks:
            if c.document_id and c.document_title:
                doc_titles[c.document_id] = c.document_title

        for did in doc_chunks.keys():
            na = doc_norm_a.get(did, 0.0)
            nb = doc_norm_b.get(did, 0.0)
            nc = doc_norm_c.get(did, 0.0)
            final = round(retriever._ALPHA * na + retriever._BETA * nb + retriever._GAMMA * nc, 4)

            rrf_details.append(RRFDetail(
                doc_id=did,
                document_title=doc_titles.get(did, ""),
                alpha_score=round(na, 4),
                beta_score=round(nb, 4),
                gamma_score=round(nc, 4),
                final_score=final,
                chunk_count=len(doc_chunks[did]),
                alpha_detail=f"切片RRF聚合={round(doc_rrf.get(did, 0), 6)}, 归一化后={round(na, 4)} (α={retriever._ALPHA})",
                beta_detail=f"文档元数据排名贡献={round(nb, 4)} (β={retriever._BETA})",
                gamma_detail=f"质量={round(doc_norm_c.get(did, 0) * retriever._MAX_ATTR_BOOST / max(retriever._QUALITY_WEIGHT, 0.001), 2) if doc_norm_c.get(did) else 0}, 时效+热度 (γ={retriever._GAMMA})",
            ))

        # 按 finalScore 排序
        rrf_details.sort(key=lambda x: x.final_score, reverse=True)

        # 更新 chunk_hits 的 final_score
        effective_threshold = await retriever._resolve_threshold(req.threshold, req.knowledge_base_id)
        for ch in chunk_hits:
            did = ch.doc_id
            na = doc_norm_a.get(did, 0.0)
            nb = doc_norm_b.get(did, 0.0)
            nc = doc_norm_c.get(did, 0.0)
            ch.final_score = round(retriever._ALPHA * na + retriever._BETA * nb + retriever._GAMMA * nc, 4)

        # 过滤 + 排序
        chunk_hits = [ch for ch in chunk_hits if ch.final_score >= effective_threshold]
        chunk_hits.sort(key=lambda x: x.final_score, reverse=True)
        chunk_hits = chunk_hits[:req.top_k]
    else:
        effective_threshold = await retriever._resolve_threshold(req.threshold, req.knowledge_base_id)

    rrf_ms = int((time.time() - t0) * 1000)

    nodes.append(PipelineNode(
        step=7,
        name="RRF 三维度加权排序",
        name_en="rrf_scoring",
        status="success" if rrf_details else "skipped",
        duration_ms=rrf_ms,
        input_data={
            "alpha_weight": retriever._ALPHA,
            "beta_weight": retriever._BETA,
            "gamma_weight": retriever._GAMMA,
            "threshold": effective_threshold,
            "rrf_k_chunk": retriever._K_CHUNK,
            "rrf_k_summary": retriever._K_SUMMARY,
            "chunk_decay": retriever._CHUNK_DECAY,
            "norm_floor": retriever._NORM_FLOOR,
        },
        output_data={
            "scored_docs": len(rrf_details),
            "passed_threshold": len(chunk_hits),
            "threshold_used": effective_threshold,
        },
        detail=(
            f"三维度加权: α(切片RRF)={retriever._ALPHA}, "
            f"β(文档元数据)={retriever._BETA}, "
            f"γ(质量+时效+热度)={retriever._GAMMA}; "
            f"阈值={effective_threshold}, 通过={len(chunk_hits)}条"
        ),
    ))

    # ── Node 8: 最终排序结果 ──
    nodes.append(PipelineNode(
        step=8,
        name="综合排序结果",
        name_en="final_ranking",
        input_data={"top_k": req.top_k, "threshold": effective_threshold},
        output_data={
            "result_count": len(chunk_hits),
            "top_scores": [ch.final_score for ch in chunk_hits[:5]],
            "hit_documents": list({ch.doc_id: ch.document_title for ch in chunk_hits}.values())[:10],
        },
        detail=f"最终返回 {len(chunk_hits)} 个分片，来自 {len({ch.doc_id for ch in chunk_hits})} 个文档",
    ))

    # ── Node 9: 回答上下文生成 ──
    answer_context = ""
    if chunk_hits:
        context_parts = []
        for i, ch in enumerate(chunk_hits[:5]):
            context_parts.append(
                f"[来源{i+1}] {ch.document_title or ch.doc_id} - {ch.section_title or '正文'}\n"
                f"{ch.content}"
            )
        answer_context = "\n\n---\n\n".join(context_parts)

    nodes.append(PipelineNode(
        step=9,
        name="回答上下文",
        name_en="answer_context",
        input_data={"top_chunks_used": min(5, len(chunk_hits))},
        output_data={"context_length": len(answer_context)},
        detail=(
            f"基于 Top-{min(5, len(chunk_hits))} 分片拼接回答上下文，"
            f"共 {len(answer_context)} 字符。"
            f"LLM 可基于此上下文回答用户问题。"
        ),
    ))

    total_ms = int((time.time() - t_start) * 1000)

    # 生成摘要
    summary_parts = [
        f"查询: \"{req.query}\"",
        f"语义查询: \"{semantic_query}\"" if semantic_query != req.query else "",
        f"过滤条件: {json.dumps(extracted_filters, ensure_ascii=False)}" if extracted_filters else "",
        f"召回: 切片{len(chunk_results)}条 + 文档{len(doc_meta_rank)}条",
        f"最终命中: {len(chunk_hits)}条 (阈值{effective_threshold})",
        f"耗时: {total_ms}ms",
    ]
    summary = " | ".join(p for p in summary_parts if p)

    return SearchDebugResponse(
        trace_id=trace_id,
        total_duration_ms=total_ms,
        pipeline_nodes=nodes,
        chunk_hits=chunk_hits,
        rrf_details=rrf_details,
        final_answer_context=answer_context,
        summary=summary,
    )


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

def _get_provider(request: Request):
    """从 app.state 获取 KnowledgeProvider"""
    provider = getattr(request.app.state, "knowledge_provider", None)
    if provider is None:
        raise HTTPException(503, "知识库 Provider 未启用")
    return provider
