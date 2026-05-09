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

    # ── Node 2: 查询改写 ──
    t0 = time.time()
    rewritten_query = req.query
    # TODO: 接入查询改写模块（当前直通）
    nodes.append(PipelineNode(
        step=2,
        name="查询改写",
        name_en="query_rewrite",
        status="skipped",
        duration_ms=int((time.time() - t0) * 1000),
        input_data={"original_query": req.query},
        output_data={"rewritten_query": rewritten_query},
        detail="当前版本未启用查询改写，原始查询直通",
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

    # ── Node 4: 多路召回 ──
    t0 = time.time()
    filter_expr = retriever._build_chunk_filter(req.knowledge_base_id, extracted_filters)
    doc_filter = retriever._build_doc_filter(req.knowledge_base_id, extracted_filters)
    chunk_limit = max(req.top_k * 5, 30)
    doc_limit = max(req.top_k * 5, 50)

    # Embedding
    query_vec: list[float] = []
    embed_status = "success"
    try:
        query_vec = await retriever._embed(semantic_query)
    except Exception as exc:
        embed_status = "failed"
        logger.warning("Debug search embedding failed: %s", exc)

    # 三路并行召回
    chunk_results: list[dict] = []
    doc_meta_hybrid: list[dict] = []

    try:
        chunk_results_raw, doc_meta_raw = await asyncio.gather(
            retriever._recall_chunks(
                req.tenant_id, query_vec, semantic_query, filter_expr, chunk_limit,
            ),
            retriever._recall_doc_metadata_hybrid(
                req.tenant_id, query_vec, semantic_query, doc_filter, doc_limit,
            ),
            return_exceptions=True,
        )
        if not isinstance(chunk_results_raw, Exception):
            chunk_results = chunk_results_raw
        if not isinstance(doc_meta_raw, Exception):
            doc_meta_hybrid = doc_meta_raw
    except Exception as exc:
        logger.warning("Debug search recall failed: %s", exc)

    doc_meta_rank = [r.get("id", "") for r in doc_meta_hybrid if r.get("id")]
    recall_ms = int((time.time() - t0) * 1000)

    nodes.append(PipelineNode(
        step=4,
        name="多路召回",
        name_en="multi_path_recall",
        status="success" if chunk_results else "failed",
        duration_ms=recall_ms,
        input_data={
            "semantic_query": semantic_query,
            "chunk_filter": filter_expr,
            "doc_filter": doc_filter,
            "embedding_dim": len(query_vec),
            "embedding_status": embed_status,
            "chunk_limit": chunk_limit,
            "doc_limit": doc_limit,
        },
        output_data={
            "chunk_hits": len(chunk_results),
            "doc_metadata_hits": len(doc_meta_rank),
            "recall_paths": [
                {"path": "A: VDB chunk hybrid_search (dense+sparse)", "hits": len(chunk_results)},
                {"path": "B: VDB doc_metadata hybrid (ANN+BM25)", "hits": len(doc_meta_rank)},
            ],
        },
        detail=f"切片召回 {len(chunk_results)} 条，文档元数据召回 {len(doc_meta_rank)} 条",
    ))

    # ── Node 5: Hydrate（切片内容填充） ──
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
        step=5,
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
        step=6,
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

    # ── Node 7: 最终排序结果 ──
    nodes.append(PipelineNode(
        step=7,
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

    # ── Node 8: 回答上下文生成 ──
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
        step=8,
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
