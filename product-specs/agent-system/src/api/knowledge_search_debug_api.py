"""知识库检索调试 API — 完整链路可视化

提供类似对话框的检索调试界面后端支持，返回完整的检索链路节点：
    1. 用户问题（原始输入）
    2. 查询改写 + 关键词提取（Query Rewrite）
    3. Self-Querying 关键字/过滤条件提取
    4. Phase 1 并行召回（总览 + 路A + 路B 分别展示）
       4a. 路A 切片hybrid召回（全局，不带元数据filter）
       4b. 路B 文档元数据hybrid召回（带元数据filter）
    5. Phase 2 定向召回（有 filter 时，用文档元数据命中的 Top-50 doc_id 定向搜切片）
    6. 命中分片详情（Hydrate + 上下文扩展）
    7. RRF 三维度加权排序（α切片RRF + β文档元数据 + γ文档属性）
    8. 综合排序结果（threshold 过滤 + top_k）
    9. 回答上下文（拼接 Top-N 分片供 LLM 回答）

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
    KnowledgeDocumentDAO,
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
    # 并行执行标记：同一 parallel_group 的节点表示并行执行
    parallel_group: str | None = None  # 如 "phase1_recall" 表示路A和路B并行
    # 层级标记：父节点的 name_en，用于前端渲染层级缩进
    parent_node: str | None = None  # 如 "phase1_parallel_recall" 表示是 Phase 1 的子节点
    # 子步骤编号：用于同一 step 内的子步骤排序和命名
    sub_step: str | None = None  # 如 "a" / "b"，前端可拼接为 "Step 4a"


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
    hit_documents: list[dict] = Field(default_factory=list, description="路B命中的所有文档列表(doc_id + title)")
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
    schema_fields_info = ""

    if req.enable_self_query and retriever._llm:
        # 先获取 Schema 信息用于展示
        try:
            from src.store.knowledge_dao import KnowledgeSchemaDAO
            schema = KnowledgeSchemaDAO.get_effective_schema(
                req.tenant_id, req.knowledge_base_id,
            )
            if schema and schema.fields:
                fields_data = json.loads(schema.fields) if isinstance(schema.fields, str) else schema.fields
                schema_fields_info = json.dumps(fields_data, ensure_ascii=False, indent=2)
        except Exception:
            schema_fields_info = "Schema 加载失败"

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

    # 构建过滤条件提取的说明
    filter_extraction_note = ""
    if sq_status == "success" and not extracted_filters:
        filter_extraction_note = (
            "未提取到过滤条件。当前查询是纯语义查询（产品名/型号/技术术语），"
            "不包含明确的分类意图。\n"
            "如需触发元数据过滤，请在查询中包含分类词，例如：\n"
            "  • \"制造业的产品手册\" → filters={docCategory:\"产品手册\", industryVertical:\"制造业\"}\n"
            "  • \"售前阶段的成功案例\" → filters={docCategory:\"成功案例\", businessStage:\"售前咨询\"}\n"
            "  • \"给技术人员的FAQ\" → filters={docCategory:\"FAQ\", targetAudience:\"技术人员\"}"
        )
    elif sq_status == "success" and extracted_filters:
        filter_extraction_note = "成功提取过滤条件：" + json.dumps(extracted_filters, ensure_ascii=False)

    nodes.append(PipelineNode(
        step=3,
        name="关键字提取与过滤条件",
        name_en="self_querying",
        status=sq_status,
        duration_ms=int((time.time() - t0) * 1000),
        input_data={
            "query": rewritten_query,
            "enable_self_query": req.enable_self_query,
            "schema_fields": schema_fields_info if schema_fields_info else "未加载",
        },
        output_data={
            "semantic_query": semantic_query,
            "extracted_filters": extracted_filters,
            "filter_extraction_note": filter_extraction_note,
        },
        detail=(
            (self_query_raw if len(self_query_raw) < 300 else self_query_raw[:300] + "...")
            + ("\n\n" + filter_extraction_note if filter_extraction_note else "")
        ),
    ))

    # ── Node 4: Phase 1 — 并行召回（切片 hybrid + 文档元数据 hybrid 同时执行） ──
    t0 = time.time()
    global_chunk_filter = retriever._build_chunk_filter(req.knowledge_base_id, {})  # 全局不带元数据 filter
    doc_filter = retriever._build_doc_filter(req.knowledge_base_id, extracted_filters)
    chunk_limit = max(req.top_k * 10, 50)
    doc_limit = max(req.top_k * 10, 50)

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

    # Phase 1: 两路并行 — A 路切片 hybrid + B 路文档元数据 hybrid
    chunk_results_global: list[dict] = []
    doc_meta_hybrid: list[dict] = []
    chunk_recall_error = ""
    doc_recall_error = ""

    t_parallel = time.time()
    try:
        results = await asyncio.gather(
            retriever._recall_chunks(
                req.tenant_id, query_vec, semantic_query, global_chunk_filter, chunk_limit,
            ),
            retriever._recall_doc_metadata_hybrid(
                req.tenant_id, query_vec, semantic_query, doc_filter, doc_limit,
            ),
            return_exceptions=True,
        )
        # A 路结果
        if isinstance(results[0], Exception):
            chunk_recall_error = f"{type(results[0]).__name__}: {results[0]}"
        else:
            chunk_results_global = results[0] or []
        # B 路结果
        if isinstance(results[1], Exception):
            doc_recall_error = f"{type(results[1]).__name__}: {results[1]}"
        else:
            doc_meta_hybrid = results[1] or []
    except Exception as exc:
        chunk_recall_error = f"gather failed: {exc}"
        doc_recall_error = f"gather failed: {exc}"
    parallel_ms = int((time.time() - t_parallel) * 1000)
    phase1_ms = int((time.time() - t0) * 1000)

    doc_meta_rank = [r.get("id", "") for r in doc_meta_hybrid if r.get("id")]

    # 路B 降级：如果带 filter 的路B返回 0 结果，去掉 filter 重试（确保 β 维度有打分）
    doc_meta_filter_fallback = False
    doc_meta_actual_values: dict = {}  # 诊断用：VDB 中文档的实际字段值
    if not doc_meta_rank and extracted_filters and query_vec:
        # 诊断：查一下 VDB 中该知识库文档的实际 filter 字段值
        try:
            from tcvectordb.model.document import Filter as _DiagFilter
            retriever._vdb._ensure_collections()
            diag_filter_expr = (
                f'tenant_id = "{req.tenant_id}" '
                f'and knowledge_base_id = "{req.knowledge_base_id}" '
                f'and status = "active"'
            )
            diag_results = retriever._vdb._doc_meta_coll.query(
                filter=_DiagFilter(diag_filter_expr),
                output_fields=["id", "doc_category", "industry", "business_stage",
                               "target_audience", "product_service", "title"],
                limit=20,
            )
            if isinstance(diag_results, list):
                diag_docs = diag_results
            else:
                diag_docs = retriever._vdb._parse_results(diag_results)

            # 汇总实际值
            for field in ["doc_category", "industry", "business_stage", "target_audience", "product_service"]:
                values = sorted({d.get(field, "") for d in diag_docs if d.get(field)})
                doc_meta_actual_values[field] = values if values else ["(全部为空)"]
            doc_meta_actual_values["_total_docs"] = len(diag_docs)
            doc_meta_actual_values["_sample_docs"] = [
                {"id": d.get("id", ""), "title": (d.get("title") or "")[:40],
                 "doc_category": d.get("doc_category", ""), "industry": d.get("industry", "")}
                for d in diag_docs[:5]
            ]
        except Exception as diag_exc:
            doc_meta_actual_values = {"_error": str(diag_exc)}

        fallback_doc_filter = retriever._build_doc_filter(req.knowledge_base_id, {})
        try:
            doc_meta_fb = await retriever._recall_doc_metadata_hybrid(
                req.tenant_id, query_vec, semantic_query, fallback_doc_filter, doc_limit,
            )
            if not isinstance(doc_meta_fb, Exception) and doc_meta_fb:
                doc_meta_hybrid = doc_meta_fb
                doc_meta_rank = [r.get("id", "") for r in doc_meta_hybrid if r.get("id")]
                doc_meta_filter_fallback = True
        except Exception:
            pass

        if doc_meta_filter_fallback:
            # 构建不匹配原因分析
            mismatch_analysis = []
            for filter_key, filter_val in extracted_filters.items():
                # 映射 camelCase → VDB 字段名
                field_map = {
                    "docCategory": "doc_category",
                    "industryVertical": "industry",
                    "businessStage": "business_stage",
                    "targetAudience": "target_audience",
                    "productService": "product_service",
                }
                vdb_field = field_map.get(filter_key, filter_key)
                actual = doc_meta_actual_values.get(vdb_field, [])
                if actual == ["(全部为空)"]:
                    mismatch_analysis.append(
                        f"{filter_key}=\"{filter_val}\": VDB中该字段全部为空（文档未被打标）"
                    )
                elif filter_val not in actual:
                    mismatch_analysis.append(
                        f"{filter_key}=\"{filter_val}\": 不匹配。VDB中实际值={actual}"
                    )

            nodes.append(PipelineNode(
                step=4,
                name="路B降级：分类过滤无匹配，改为纯语义召回",
                name_en="doc_meta_filter_fallback",
                status="success",
                duration_ms=0,
                input_data={
                    "第一次调用（带分类filter）": {
                        "filter": doc_filter,
                        "result": "0 个文档",
                    },
                    "降级调用（仅基础条件）": {
                        "filter": fallback_doc_filter,
                        "result": f"{len(doc_meta_rank)} 个文档",
                    },
                    "不匹配原因分析": mismatch_analysis,
                    "VDB中文档实际字段值": doc_meta_actual_values,
                },
                output_data={
                    "recovered_doc_count": len(doc_meta_rank),
                    "top5_doc_ids": doc_meta_rank[:5],
                    "用途": "恢复的文档用于β维度打分 + Phase 2定向召回范围",
                },
                detail=(
                    "路B降级触发：带分类filter("
                    + json.dumps(extracted_filters, ensure_ascii=False)
                    + ")查询返回0文档 → 去掉分类条件后按纯语义召回 "
                    + str(len(doc_meta_rank)) + " 个文档。"
                    + (" 不匹配原因：" + "; ".join(mismatch_analysis) if mismatch_analysis else "")
                ),
            ))

    # ── Node 4: Phase 1 总览（Embedding + 并行执行模式） ──
    nodes.append(PipelineNode(
        step=4,
        name="Phase 1 并行召回 (切片hybrid + 文档元数据hybrid)",
        name_en="phase1_parallel_recall",
        status="success" if (chunk_results_global or doc_meta_hybrid) else (
            "failed" if (embed_status == "failed" or chunk_recall_error or doc_recall_error) else "skipped"
        ),
        duration_ms=phase1_ms,
        input_data={
            "semantic_query": semantic_query,
            "execution_mode": "asyncio.gather (路A ∥ 路B 并行执行)",
            "embedding_dim": len(query_vec),
            "embedding_status": embed_status,
            "embedding_error": embed_error,
            "embedding_ms": embed_ms,
            "并行说明": "路A和路B通过 asyncio.gather 同时发起，总耗时 = max(路A, 路B)，非相加",
        },
        output_data={
            "路A_切片命中": len(chunk_results_global),
            "路B_文档命中": len(doc_meta_rank),
            "parallel_ms": parallel_ms,
            "total_phase1_ms": phase1_ms,
        },
        detail=(
            f"Embedding {embed_ms}ms (dim={len(query_vec)}) → "
            f"路A ∥ 路B 并行执行 {parallel_ms}ms: "
            f"路A 切片hybrid命中 {len(chunk_results_global)} 条, "
            f"路B 文档元数据hybrid命中 {len(doc_meta_rank)} 个文档"
            + (f"\n❌ Embedding: {embed_error}" if embed_error else "")
        ),
    ))

    # ── Node 4a: 路A — 切片级 hybrid_search（与路B并行执行） ──
    route_a_status = "success" if chunk_results_global else ("failed" if chunk_recall_error else "skipped")
    nodes.append(PipelineNode(
        step=4,
        name="⫘ 路A 切片hybrid召回 (全局，不带元数据filter)",
        name_en="phase1_route_a_chunk_hybrid",
        status=route_a_status,
        duration_ms=parallel_ms,
        parallel_group="phase1_recall",
        parent_node="phase1_parallel_recall",
        sub_step="a",
        input_data={
            "collection": "kb_chunks",
            "search_type": "hybrid_search (dense + sparse)",
            "semantic_query": semantic_query,
            "filter": global_chunk_filter,
            "chunk_limit": chunk_limit,
            "dense_weight": 0.3,
            "sparse_weight": 0.7,
            "执行方式": "与路B并行 (asyncio.gather)",
            "设计意图": "全局不带元数据 filter，确保语义相关切片不会因打标不准而被漏掉",
        },
        output_data={
            "命中切片数": len(chunk_results_global),
            "error": chunk_recall_error or None,
            "top5_scores": [round(r.get("score", 0), 4) for r in chunk_results_global[:5]],
            "top5_chunks": [
                {
                    "chunk_id": r.get("id", ""),
                    "doc_id": r.get("doc_id", ""),
                    "score": round(r.get("score", 0), 4),
                    "section_title": (r.get("section_title") or "")[:50],
                    "content_preview": (r.get("content") or "")[:80],
                }
                for r in chunk_results_global[:5]
            ],
        },
        detail=(
            f"[并行] kb_chunks.hybrid_search → 命中 {len(chunk_results_global)} 条切片"
            + (f"\n❌ {chunk_recall_error}" if chunk_recall_error else "")
            + (f"\nTop-1 score: {chunk_results_global[0].get('score', 0):.4f}" if chunk_results_global else "")
        ),
    ))

    # ── Node 4b: 路B — 文档元数据 hybrid_search（与路A并行执行） ──
    route_b_status = "success" if doc_meta_rank else ("failed" if doc_recall_error else "skipped")
    if doc_meta_filter_fallback:
        route_b_status = "success"

    # 构建路B详细查询逻辑描述
    route_b_query_logic = {
        "1_集合": "kb_doc_metadata（每份文档一条记录）",
        "2_调用方式": "tcvectordb hybrid_search（一次调用融合 ANN + BM25）",
        "3_ANN路（dense）": {
            "field": "vector",
            "数据来源": "文档摘要(summary)的 embedding 向量",
            "维度": len(query_vec),
            "作用": "语义级文档召回 — 找到整体主题相关的文档",
            "权重": f"dense_weight={0.5}",
        },
        "4_BM25路（sparse）": {
            "field": "sparse_vector",
            "数据来源": "5路加权文本拼接后的 BM25Encoder 编码",
            "加权拼接规则": {
                "title": "×3（标题命中权重最高）",
                "summary": "×2（摘要命中次之）",
                "keywords": "×2（LLM提取的关键词）",
                "candidate_keywords": "×1（jieba TF-IDF候选）",
                "toc": "×1（外部路径 + 章节大纲）",
            },
            "编码方式": "BM25Encoder.encode_texts(加权拼接文本) → sparse_vector",
            "查询编码": "BM25Encoder.encode_queries(semantic_query) → query_sparse",
            "作用": "关键词级文档召回 — 标题/摘要/关键词精确匹配",
            "权重": f"sparse_weight={0.5}",
        },
        "5_融合方式": "WeightedRerank(field_list=['vector','sparse_vector'], weight=[0.5, 0.5])",
        "6_过滤条件": {
            "filter_expr": doc_filter,
            "含义": "knowledge_base_id + status=active + 元数据分类条件(来自Self-Querying)",
            "注意": "路B带元数据filter，路A不带 — 这是两路的核心区别",
        },
        "7_返回值": f"按融合分降序的 doc_id 列表（Top-{doc_limit}），列表位置即 rank",
        "8_用途": [
            "β维度打分：doc_id 在列表中的 rank → 1/(K_SUMMARY + rank + 1) + 1/(K_META_TEXT + rank + 1)",
            "Phase 2 定向召回：取 Top-50 doc_id 作为切片定向搜索范围",
        ],
        "9_降级机制": "带filter返回0结果时 → 去掉分类条件重试（纯语义召回）→ 确保β维度有打分数据",
    }

    nodes.append(PipelineNode(
        step=4,
        name="⫘ 路B 文档元数据hybrid召回 (带元数据filter)",
        name_en="phase1_route_b_doc_meta_hybrid",
        status=route_b_status,
        duration_ms=parallel_ms,
        parallel_group="phase1_recall",
        parent_node="phase1_parallel_recall",
        sub_step="b",
        input_data={
            "collection": "kb_doc_metadata",
            "search_type": "hybrid_search (summary ANN + 加权BM25)",
            "semantic_query": semantic_query,
            "filter": doc_filter,
            "doc_limit": doc_limit,
            "dense_weight": 0.5,
            "sparse_weight": 0.5,
            "执行方式": "与路A并行 (asyncio.gather)",
            "查询逻辑详解": route_b_query_logic,
        },
        output_data={
            "命中文档数": len(doc_meta_rank),
            "error": doc_recall_error or None,
            "filter_fallback_triggered": doc_meta_filter_fallback,
            "top5_doc_ids": doc_meta_rank[:5],
            "用途": "① β维度打分 ② Phase 2 定向召回的文档范围",
        },
        detail=(
            f"[并行] kb_doc_metadata.hybrid_search → 命中 {len(doc_meta_rank)} 个文档\n"
            f"查询逻辑：ANN(summary向量, dense=0.5) + BM25(title×3+summary×2+keywords×2+candidate×1+toc×1, sparse=0.5)\n"
            f"Filter: {doc_filter}"
            + (f"\n⚠️ 降级触发：原始 filter 无结果，去掉分类条件后重试成功" if doc_meta_filter_fallback else "")
            + (f"\n❌ {doc_recall_error}" if doc_recall_error else "")
            + (f"\nTop-5 doc_ids: {doc_meta_rank[:5]}" if doc_meta_rank else "")
        ),
    ))

    # ── Node 5: Phase 2 — 定向召回（有 filter 时触发） ──
    t0 = time.time()
    chunk_results_targeted: list[dict] = []
    has_filters = bool(extracted_filters)
    phase2_status = "skipped"
    phase2_detail = ""
    phase2_skip_reason = ""
    target_doc_ids: list[str] = []

    if has_filters and doc_meta_rank and query_vec:
        target_doc_ids = doc_meta_rank[:50]
        targeted_filter = retriever._build_chunk_filter_with_doc_ids(
            req.knowledge_base_id, target_doc_ids,
        )
        targeted_limit = max(req.top_k * 3, 20)
        try:
            chunk_results_targeted = await retriever._recall_chunks(
                req.tenant_id, query_vec, semantic_query, targeted_filter, targeted_limit,
            )
            phase2_status = "success" if chunk_results_targeted else "skipped"
            phase2_detail = (
                f"用路B命中的 Top-{len(target_doc_ids)} 文档ID定向搜切片 → "
                f"命中 {len(chunk_results_targeted)} 条"
            )
        except Exception as exc:
            phase2_status = "failed"
            phase2_detail = f"定向召回失败: {exc}"
    elif not has_filters:
        phase2_skip_reason = "Self-Querying 未提取到元数据过滤条件（filters 为空）"
        _nl = "\n"
        phase2_detail = (
            f"跳过 Phase 2 定向召回。{_nl}"
            f"原因：{phase2_skip_reason}{_nl}"
            f"说明：Phase 2 仅在用户查询包含明确的分类意图时触发，"
            f"例如「制造业的成功案例」、「售前阶段的培训材料」等。{_nl}"
            f"当前查询 \"{semantic_query}\" 是纯语义查询（产品名/型号/技术术语），"
            f"由路A全局hybrid_search直接通过向量+BM25匹配，无需定向召回。{_nl}"
            f"触发示例：试试 \"制造业的产品手册\"、\"金融行业成功案例\"、"
            f"\"售前阶段培训材料\" 等包含分类词的查询。"
        )
    elif has_filters and not doc_meta_rank:
        phase2_skip_reason = "有过滤条件但路B文档元数据召回无结果"
        _nl = "\n"
        phase2_detail = (
            f"跳过 Phase 2 定向召回。{_nl}"
            f"原因：{phase2_skip_reason}{_nl}"
            f"过滤条件：{json.dumps(extracted_filters, ensure_ascii=False)}{_nl}"
            f"可能原因：该知识库中没有匹配这些元数据标签的文档，"
            f"或文档入库时未完成自动打标。"
        )
    elif has_filters and not query_vec:
        phase2_skip_reason = "有过滤条件但 Embedding 失败"
        _nl = "\n"
        phase2_detail = (
            f"跳过 Phase 2 定向召回。{_nl}"
            f"原因：{phase2_skip_reason}{_nl}"
            f"Embedding 错误：{embed_error}"
        )

    phase2_ms = int((time.time() - t0) * 1000)

    # 构建触发条件说明
    trigger_conditions = {
        "condition_1_has_filters": {
            "satisfied": has_filters,
            "description": "Self-Querying 提取了元数据过滤条件",
            "current_value": extracted_filters if extracted_filters else "{}（空）",
            "how_to_satisfy": (
                "在查询中包含明确的分类意图词，例如：\n"
                "  • 行业分类：\"制造业的...\"、\"金融行业...\"、\"零售业...\"\n"
                "  • 文档类型：\"产品手册\"、\"成功案例\"、\"FAQ\"、\"培训材料\"\n"
                "  • 业务阶段：\"售前阶段...\"、\"实施阶段...\"、\"售后...\"\n"
                "  • 目标受众：\"给技术人员的...\"、\"面向管理层的...\"\n"
                "注意：产品名称（如\"罗斯蒙特\"）、型号（如\"3051\"）不会触发过滤，"
                "它们通过语义+BM25检索匹配"
            ),
        },
        "condition_2_doc_meta_rank": {
            "satisfied": bool(doc_meta_rank),
            "description": "路B文档元数据召回有结果",
            "current_value": f"{len(doc_meta_rank)} 个文档",
        },
        "condition_3_query_vec": {
            "satisfied": bool(query_vec),
            "description": "Embedding 成功",
            "current_value": (f"dim={len(query_vec)}" if query_vec else "失败"),
        },
    }

    nodes.append(PipelineNode(
        step=5,
        name="Phase 2 定向召回 (元数据命中文档内搜切片)",
        name_en="phase2_targeted_recall",
        status=phase2_status,
        duration_ms=phase2_ms,
        input_data={
            "trigger_conditions": trigger_conditions,
            "has_filters": has_filters,
            "effective_filters": extracted_filters,
            "skip_reason": phase2_skip_reason,
            "target_doc_count": len(target_doc_ids),
            "target_doc_ids_sample": target_doc_ids[:5],
            "targeted_limit": max(req.top_k * 3, 20) if has_filters else 0,
        },
        output_data={
            "targeted_chunk_hits": len(chunk_results_targeted),
            "top5_scores": [round(r.get("score", 0), 4) for r in chunk_results_targeted[:5]],
        },
        detail=phase2_detail,
    ))

    # Phase 3: 合并去重（全局 ∪ 定向）
    chunk_results = retriever._merge_chunk_results(chunk_results_global, chunk_results_targeted)

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
                input_data={"reason": "合并后召回为空（全局+定向均无结果）", "removed_filters": extracted_filters},
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

    # 补充 document_title：如果 VDB 未返回 title，从 PG 批量拉取
    doc_ids_missing_title = list({
        c.document_id for c in chunks
        if c.document_id and not c.document_title
    })
    pg_doc_titles: dict[str, str] = {}
    if doc_ids_missing_title:
        try:
            pg_docs = KnowledgeDocumentDAO.get_by_doc_ids(doc_ids_missing_title)
            pg_doc_titles = {
                d.doc_id: (d.title or d.file_name or "")
                for d in pg_docs
            }
        except Exception as exc:
            logger.debug("Fallback load doc titles from PG failed: %s", exc)

    # 构建命中分片列表（含原始分数）
    chunk_hits: list[ChunkHit] = []
    for c in chunks:
        title = c.document_title or pg_doc_titles.get(c.document_id, "")
        chunk_hits.append(ChunkHit(
            chunk_id=c.chunk_id,
            doc_id=c.document_id,
            document_title=title,
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

        # 维度 A 归一化（理论锚点，对齐 data-process）
        chunk_limit = len(chunks_sorted) if chunks_sorted else 30
        theoretical_max_rrf = 1.0 / (retriever._K_CHUNK + 1)
        theoretical_min_rrf = 1.0 / (retriever._K_CHUNK + chunk_limit + 1)
        rrf_range = theoretical_max_rrf - theoretical_min_rrf

        doc_norm_a: dict[str, float] = {}
        for did, score in doc_rrf.items():
            if rrf_range > 0:
                norm = (score - theoretical_min_rrf) / rrf_range
                doc_norm_a[did] = max(0.0, min(1.0, norm))
            else:
                doc_norm_a[did] = 0.5

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
        effective_threshold = await retriever._resolve_threshold(req.threshold, req.knowledge_base_id)
        doc_titles: dict[str, str] = {}
        for c in chunks:
            if c.document_id and c.document_title:
                doc_titles[c.document_id] = c.document_title
        # 合并 PG fallback 标题（VDB 未返回 title 的文档）
        for did, title in pg_doc_titles.items():
            if did not in doc_titles and title:
                doc_titles[did] = title
        # 补充：对 doc_chunks 中仍缺 title 的文档再查一次 PG
        missing_title_doc_ids = [did for did in doc_chunks.keys() if did not in doc_titles]
        if missing_title_doc_ids:
            try:
                extra_pg_docs = KnowledgeDocumentDAO.get_by_doc_ids(missing_title_doc_ids)
                for d in extra_pg_docs:
                    if d.doc_id not in doc_titles:
                        doc_titles[d.doc_id] = d.title or d.file_name or ""
            except Exception:
                pass

        for did in doc_chunks.keys():
            na = doc_norm_a.get(did, 0.0)
            nb = doc_norm_b.get(did, 0.0)
            nc = doc_norm_c.get(did, 0.0)
            raw_score = retriever._ALPHA * na + retriever._BETA * nb + retriever._GAMMA * nc
            final = round(raw_score * (1.0 - effective_threshold) + effective_threshold, 4)

            # 构建 α 维度详细说明
            chunk_count_for_doc = len(doc_chunks[did])
            alpha_raw = doc_rrf.get(did, 0)
            alpha_detail_text = (
                f"切片RRF聚合分={alpha_raw:.6f} → 归一化normA={na:.4f}\n"
                f"  命中{chunk_count_for_doc}个切片, "
                f"聚合方式: seg[0]"
                + (f" + Σseg[i]×0.2^i (衰减聚合)" if chunk_count_for_doc > 1 else "")
                + f"\n  理论锚点: max={theoretical_max_rrf:.6f}, min={theoretical_min_rrf:.6f}"
                + f"\n  加权贡献: α({retriever._ALPHA}) × {na:.4f} = {retriever._ALPHA * na:.4f}"
            )

            # 构建 β 维度详细说明
            beta_boost_raw = 0.0
            beta_rank_info = ""
            try:
                idx_s = doc_meta_rank.index(did)
                s_contrib = 1.0 / (retriever._K_SUMMARY + idx_s + 1)
                beta_boost_raw += s_contrib
                beta_rank_info += f"摘要ANN排名#{idx_s+1} → 贡献={s_contrib:.6f}; "
            except ValueError:
                beta_rank_info += "摘要ANN未命中; "
            try:
                idx_m = doc_meta_rank.index(did)
                m_contrib = 1.0 / (retriever._K_META_TEXT + idx_m + 1)
                beta_boost_raw += m_contrib
                beta_rank_info += f"BM25排名#{idx_m+1} → 贡献={m_contrib:.6f}"
            except ValueError:
                beta_rank_info += "BM25未命中"
            beta_detail_text = (
                f"文档元数据排名贡献: normB={nb:.4f}\n"
                f"  {beta_rank_info}\n"
                f"  boost = ({beta_boost_raw:.6f}) × METADATA_WEIGHT({retriever._METADATA_WEIGHT}) = {beta_boost_raw * retriever._METADATA_WEIGHT:.6f}\n"
                f"  归一化: boost / MAX_BOOST({retriever._MAX_METADATA_BOOST:.6f}) = {nb:.4f}\n"
                f"  加权贡献: β({retriever._BETA}) × {nb:.4f} = {retriever._BETA * nb:.4f}"
            )

            # 构建 γ 维度详细说明
            meta = doc_cache.get(did) or {}
            if "quality_score_x10k" in meta:
                quality_val = float(meta.get("quality_score_x10k") or 0) / 10000.0
            else:
                quality_val = float(meta.get("quality_score") or 0.5)
            quality_val = max(0.0, min(1.0, quality_val)) if quality_val else 0.5
            recency_val = 0.5
            ref_ts = int(meta.get("date_published") or 0) or int(meta.get("created_at") or 0)
            if ref_ts and ref_ts > 0:
                age_ms = max(0, now_ms - ref_ts)
                recency_val = math.pow(0.5, age_ms / retriever._RECENCY_HALFLIFE_MS)
            hit_val = 0.0
            hit_count = int(meta.get("search_hit_count") or 0)
            if hit_count > 0:
                hit_val = min(1.0, math.log10(hit_count + 1) / math.log10(1000))
            gamma_detail_text = (
                f"文档属性综合: normC={nc:.4f}\n"
                f"  质量分: {quality_val:.3f} × {retriever._QUALITY_WEIGHT} = {quality_val * retriever._QUALITY_WEIGHT:.4f}\n"
                f"  时效性: {recency_val:.3f} × {retriever._RECENCY_WEIGHT} = {recency_val * retriever._RECENCY_WEIGHT:.4f}"
                + (f" (发布距今{(now_ms - ref_ts) / 86400000:.0f}天)" if ref_ts > 0 else " (无发布时间,默认0.5)")
                + f"\n  热度: {hit_val:.3f} × {retriever._HIT_WEIGHT} = {hit_val * retriever._HIT_WEIGHT:.4f}"
                + (f" (被检索{hit_count}次)" if hit_count > 0 else " (未被检索过)")
                + f"\n  加权贡献: γ({retriever._GAMMA}) × {nc:.4f} = {retriever._GAMMA * nc:.4f}"
            )

            rrf_details.append(RRFDetail(
                doc_id=did,
                document_title=doc_titles.get(did, ""),
                alpha_score=round(na, 4),
                beta_score=round(nb, 4),
                gamma_score=round(nc, 4),
                final_score=final,
                chunk_count=len(doc_chunks[did]),
                alpha_detail=alpha_detail_text,
                beta_detail=beta_detail_text,
                gamma_detail=gamma_detail_text,
            ))

        # 按 finalScore 排序
        rrf_details.sort(key=lambda x: x.final_score, reverse=True)

        # 更新 chunk_hits 的 final_score
        for ch in chunk_hits:
            did = ch.doc_id
            na = doc_norm_a.get(did, 0.0)
            nb = doc_norm_b.get(did, 0.0)
            nc = doc_norm_c.get(did, 0.0)
            raw_score = retriever._ALPHA * na + retriever._BETA * nb + retriever._GAMMA * nc
            ch.final_score = round(raw_score * (1.0 - effective_threshold) + effective_threshold, 4)

        # 过滤 + 排序
        chunk_hits = [ch for ch in chunk_hits if ch.final_score >= effective_threshold]
        chunk_hits.sort(key=lambda x: x.final_score, reverse=True)
        chunk_hits = chunk_hits[:req.top_k]
    else:
        effective_threshold = await retriever._resolve_threshold(req.threshold, req.knowledge_base_id)

    rrf_ms = int((time.time() - t0) * 1000)

    # 构建三维度加权的详细描述
    rrf_detail_lines = [
        f"═══ 三维度归一化加权排序 ═══",
        f"",
        f"公式: finalScore = α·normA + β·normB + γ·normC",
        f"映射: mappedScore = rawScore × (1 - threshold) + threshold → [{effective_threshold}, 1.0]",
        f"",
        f"── α 维度：切片相关性 (权重={retriever._ALPHA}) ──",
        f"  数据来源: 路A 切片hybrid_search返回的融合分(dense 30% + BM25 70%)",
        f"  计算步骤:",
        f"    1. 切片按score降序排名 → RRF贡献 = 1/(K_CHUNK + rank + 1), K_CHUNK={retriever._K_CHUNK}",
        f"    2. 同文档多切片几何衰减聚合: docScore = seg[0] + Σ seg[i] × {retriever._CHUNK_DECAY}^i",
        f"    3. 理论锚点归一化: normA = (docScore - theoreticalMin) / (theoreticalMax - theoreticalMin)",
        f"       theoreticalMax = 1/(K+1) = {1.0/(retriever._K_CHUNK+1):.6f} (排名第1)",
        f"       theoreticalMin = 1/(K+N+1), N=召回切片数",
        f"  含义: 衡量文档中切片与查询的语义+关键词相关程度，多切片命中会提升文档得分",
        f"",
        f"── β 维度：文档元数据 (权重={retriever._BETA}) ──",
        f"  数据来源: 路B 文档元数据hybrid_search的排名位置",
        f"  计算步骤:",
        f"    1. 摘要ANN贡献 = 1/(K_SUMMARY + rank + 1), K_SUMMARY={retriever._K_SUMMARY}",
        f"    2. 加权BM25贡献 = 1/(K_META_TEXT + rank + 1), K_META_TEXT={retriever._K_META_TEXT}",
        f"       BM25加权拼接: title×3 + summary×2 + keywords×2 + candidate×1 + toc×1",
        f"    3. boost = (ANN贡献 + BM25贡献) × METADATA_WEIGHT({retriever._METADATA_WEIGHT})",
        f"    4. normB = boost / MAX_METADATA_BOOST({retriever._MAX_METADATA_BOOST:.6f})",
        f"  含义: 衡量文档整体（标题/摘要/关键词）与查询的匹配度，补充切片级检索的文档级信号",
        f"",
        f"── γ 维度：文档属性 (权重={retriever._GAMMA}) ──",
        f"  数据来源: VDB kb_doc_metadata集合中的文档属性字段",
        f"  子维度:",
        f"    • 质量分 (quality_weight={retriever._QUALITY_WEIGHT}): LLM评估的文档质量 [0,1]",
        f"    • 时效性 (recency_weight={retriever._RECENCY_WEIGHT}): 半衰期={retriever._RECENCY_HALFLIFE_MS/86400000:.0f}天的指数衰减",
        f"    • 热度 (hit_weight={retriever._HIT_WEIGHT}): log10(hit_count+1)/log10(1000) 对数归一化",
        f"  计算: normC = (quality×{retriever._QUALITY_WEIGHT} + recency×{retriever._RECENCY_WEIGHT} + hit×{retriever._HIT_WEIGHT}) / MAX_ATTR_BOOST({retriever._MAX_ATTR_BOOST})",
        f"  含义: 高质量、近期更新、频繁被检索命中的文档获得额外加分",
        f"",
        f"── 阈值过滤 ──",
        f"  threshold={effective_threshold} (来源: {'调用方显式指定' if req.threshold is not None else '知识库配置 / 系统默认'})",
        f"  mappedScore < threshold 的文档被过滤",
        f"  通过阈值: {len(chunk_hits)}条 / 总评分: {len(rrf_details)}个文档",
    ]
    rrf_detail_text = "\n".join(rrf_detail_lines)

    nodes.append(PipelineNode(
        step=7,
        name="RRF 三维度加权排序",
        name_en="rrf_scoring",
        status="success" if rrf_details else "skipped",
        duration_ms=rrf_ms,
        input_data={
            "公式说明": {
                "总公式": "finalScore = α·normA + β·normB + γ·normC",
                "分数映射": f"mappedScore = rawScore × (1 - {effective_threshold}) + {effective_threshold} → [{effective_threshold}, 1.0]",
            },
            "α_切片相关性": {
                "权重": retriever._ALPHA,
                "数据来源": "路A 切片hybrid_search (dense 30% + BM25 70%)",
                "RRF_K值": retriever._K_CHUNK,
                "多切片衰减系数": retriever._CHUNK_DECAY,
                "归一化方式": "理论锚点归一化 (theoreticalMax=1/(K+1), theoreticalMin=1/(K+N+1))",
                "聚合方式": "同文档多切片几何衰减: docScore = seg[0] + Σ seg[i] × 0.2^i",
            },
            "β_文档元数据": {
                "权重": retriever._BETA,
                "数据来源": "路B 文档元数据hybrid_search (摘要ANN 50% + 加权BM25 50%)",
                "K_SUMMARY": retriever._K_SUMMARY,
                "K_META_TEXT": retriever._K_META_TEXT,
                "METADATA_WEIGHT": retriever._METADATA_WEIGHT,
                "BM25加权规则": "title×3 + summary×2 + keywords×2 + candidate_keywords×1 + toc×1",
                "计算": "boost = (1/(K_SUMMARY+rank+1) + 1/(K_META_TEXT+rank+1)) × METADATA_WEIGHT",
            },
            "γ_文档属性": {
                "权重": retriever._GAMMA,
                "数据来源": "VDB kb_doc_metadata 集合属性字段",
                "子维度": {
                    "quality_score": f"LLM评估的文档质量 [0,1], 子权重={retriever._QUALITY_WEIGHT}",
                    "recency": f"时效性指数衰减, 半衰期={retriever._RECENCY_HALFLIFE_MS/86400000:.0f}天, 子权重={retriever._RECENCY_WEIGHT}",
                    "hit_count": f"检索热度 log10归一化, 子权重={retriever._HIT_WEIGHT}",
                },
                "MAX_ATTR_BOOST": retriever._MAX_ATTR_BOOST,
            },
            "阈值配置": {
                "threshold": effective_threshold,
                "来源": "调用方显式指定" if req.threshold is not None else "知识库min_score配置 / 系统默认0.3",
                "作用": f"mappedScore < {effective_threshold} 的文档被过滤掉",
            },
        },
        output_data={
            "scored_docs": len(rrf_details),
            "passed_threshold": len(chunk_hits),
            "filtered_out": len(rrf_details) - len(chunk_hits),
            "threshold_used": effective_threshold,
            "score_range": {
                "max": rrf_details[0].final_score if rrf_details else 0,
                "min": rrf_details[-1].final_score if rrf_details else 0,
            },
        },
        detail=rrf_detail_text,
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

    # 构建路B命中文档汇总（包含所有文档级召回结果）
    hit_documents: list[dict] = []
    if doc_meta_hybrid:
        # 从路B结果中提取 doc_id 和 title
        route_b_doc_ids = [r.get("id", "") for r in doc_meta_hybrid if r.get("id")]
        # 从 PG 批量获取标题（路B VDB 可能没有返回 title）
        route_b_titles: dict[str, str] = {}
        if route_b_doc_ids:
            try:
                pg_docs_for_route_b = KnowledgeDocumentDAO.get_by_doc_ids(route_b_doc_ids)
                route_b_titles = {
                    d.doc_id: (d.title or d.file_name or "")
                    for d in pg_docs_for_route_b
                }
            except Exception:
                pass

        # 统计每个文档的切片命中数（从 chunk_hits 中聚合）
        doc_chunk_counts: dict[str, int] = {}
        for ch in chunk_hits:
            doc_chunk_counts[ch.doc_id] = doc_chunk_counts.get(ch.doc_id, 0) + 1

        for rank, r in enumerate(doc_meta_hybrid):
            did = r.get("id", "")
            if not did:
                continue
            title = r.get("title") or route_b_titles.get(did, "") or did
            hit_documents.append({
                "rank": rank + 1,
                "doc_id": did,
                "title": title,
                "score": round(float(r.get("score", 0)), 4),
                "chunk_count": doc_chunk_counts.get(did, 0),
            })

    return SearchDebugResponse(
        trace_id=trace_id,
        total_duration_ms=total_ms,
        pipeline_nodes=nodes,
        chunk_hits=chunk_hits,
        rrf_details=rrf_details,
        hit_documents=hit_documents,
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
