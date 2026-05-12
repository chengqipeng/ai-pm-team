"""知识检索引擎 — 多阶段召回 + RRF + 归一化多维度加权（全 VDB 版）

对应 doc/知识库体系设计方案.md §五。

检索链路：
    Query
      │
      ├── Step 1: 查询改写 + 关键词提取（LLM / jieba）
      ├── Step 2: Self-Querying（LLM 提取 metadata filter）
      │
      ├── Step 3 Phase 1: asyncio.gather 并行
      │     ├── [A] VDB kb_chunks.hybrid_search (dense+BM25, 全局不带元数据filter)
      │     └── [B] VDB kb_doc_metadata.hybrid_search (summary ANN + 加权BM25, 带filter)
      │
      ├── Step 3.5 Phase 2: 定向召回（仅当有 filter 且路B有结果时）
      │     └── [A'] VDB kb_chunks.hybrid_search (doc_id IN 路B Top-50)
      │
      ├── Phase 3: 合并去重（全局 ∪ 定向，按 score 降序）
      │
      ├── Step 4: Hydrate + Parent-Child 上下文扩展
      │
      ├── Step 5: 三维度归一化加权
      │     切片→文档聚合（docScore = seg[0] + Σ seg[i] × 0.2^i）
      │     finalScore = α·normA + β·normB + γ·normC
      │       α (0.7): 切片 RRF 聚合分 → 理论锚点归一化 [0, 1]
      │       β (0.1): 路B融合排名 RRF × METADATA_WEIGHT → [0, 1]
      │       γ (0.2): quality + recency + hit → [0, 1]（来自 VDB 文档属性）
      │     映射: finalScore = rawScore × (1 - threshold) + threshold
      │
      ├── Step 6: threshold 过滤 + 排序 → top_k
      │
      └── Step 7: 热度+1 + 审计日志（异步）
      ▼
    List<KnowledgeChunk>
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from typing import Any

from src.store.knowledge_dao import (
    KnowledgeBaseDAO, KnowledgeDocumentDAO,
    KnowledgeSchemaDAO, KnowledgeSearchLogDAO,
)
from src.store.knowledge_models import KnowledgeSearchLogRow

from .lkeap_client import TencentLKEAPClient
from .provider import KnowledgeChunk
from .vdb_writer import KnowledgeVectorStore

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Prompt 模板
# ═══════════════════════════════════════════════════════════

QUERY_REWRITE_PROMPT = """你是一个专业的检索查询优化器。请根据用户的原始问题和对话历史，生成优化后的检索查询。

## 任务
将用户的口语化/简短/模糊问题改写为更适合知识库检索的形式，同时提取核心关键词。

## 改写规则
1. 补全指代：如果对话历史中有上下文，将"它"、"这个"等指代词替换为具体实体
2. 扩展缩写：将缩写/简称展开为全称（如"3051" → "罗斯蒙特3051压力变送器"）
3. 语义增强：添加同义词或相关术语提升召回率（如"参数" → "技术参数 规格 性能指标"）
4. 去除噪音：去掉"请问"、"帮我"、"我想知道"等无检索价值的词
5. 保持核心意图：不要改变用户的原始查询意图

## 关键词提取规则
1. 提取 3-8 个核心关键词，按重要性排序
2. 包含：产品名称、型号、技术术语、核心概念
3. 排除：停用词、语气词、连接词

## 对话历史
{conversation_history}

## 用户当前问题
{query}

## 输出要求
严格以 JSON 格式输出（不要任何其他说明文字）：
{{
  "rewritten_query": "改写后的检索查询（一句话，适合语义检索）",
  "keywords": ["关键词1", "关键词2", "关键词3"],
  "intent": "用户意图的一句话描述",
  "expansion_terms": ["扩展词1", "扩展词2"]
}}

示例：
- 用户问"3051参数" → {{"rewritten_query": "罗斯蒙特3051压力变送器技术参数规格", "keywords": ["罗斯蒙特", "3051", "压力变送器", "参数", "规格"], "intent": "查询3051压力变送器的技术参数", "expansion_terms": ["技术规格", "性能指标", "量程"]}}
- 用户问"怎么安装" + 历史提到3051 → {{"rewritten_query": "罗斯蒙特3051压力变送器安装方法步骤", "keywords": ["3051", "安装", "方法", "步骤"], "intent": "查询3051的安装方法", "expansion_terms": ["安装指南", "接线", "调试"]}}
- 用户问"价格多少" → {{"rewritten_query": "产品价格报价", "keywords": ["价格", "报价"], "intent": "查询产品价格", "expansion_terms": ["选型", "订购"]}}
"""


SELF_QUERY_PROMPT = """你是一个查询分析器。根据用户的自然语言查询，判断是否需要元数据过滤。

## 可用的过滤字段
{schema_fields}

## 用户查询
{query}

## 输出要求
以 JSON 格式输出（不要任何其他说明文字）：
{{
  "semantic_query": "用于语义检索的核心查询（保留用户原始问题的核心词汇）",
  "filters": {{
    "字段名": "值"
  }}
}}

## 关键规则（必须严格遵守）
1. **宁可不过滤，也不要错误过滤**。过滤条件只在用户明确表达了分类意图时才添加。
2. 如果用户查询是产品名称、型号、品牌名、技术术语，**不要**添加任何过滤条件，直接返回空 filters。
3. 只有当用户明确说出了分类词（如"成功案例"、"制造业"、"售前阶段"）时，才添加对应的 filter。
4. **不要**从产品名称推断 productService 过滤 — 产品名称应该通过语义检索匹配，不是通过 filter 精确匹配。
5. **不要**从文档类型推断 docCategory 过滤 — 除非用户明确说"我要看产品手册"、"给我成功案例"。
6. semantic_query 应保留用户原始查询的核心词汇，不要过度改写。
7. filters 返回空对象 {{}} 是最安全的默认选择。

## 示例
- "罗斯蒙特" → {{"semantic_query": "罗斯蒙特", "filters": {{}}}}
- "3051压力变送器参数" → {{"semantic_query": "3051压力变送器参数", "filters": {{}}}}
- "制造业的成功案例" → {{"semantic_query": "成功案例", "filters": {{"docCategory": "成功案例", "industryVertical": "制造业"}}}}
- "怎么配置审批流" → {{"semantic_query": "怎么配置审批流", "filters": {{}}}}
- "给我看售前阶段的培训材料" → {{"semantic_query": "培训材料", "filters": {{"docCategory": "培训材料", "businessStage": "售前咨询"}}}}
"""


# ═══════════════════════════════════════════════════════════
# KnowledgeRetriever
# ═══════════════════════════════════════════════════════════

class KnowledgeRetriever:
    """知识检索引擎 — 全 VDB 多路召回 + 归一化多维度加权"""

    # ── 融合参数（对齐 data-process DocumentSearchServiceImpl） ──
    _K_CHUNK = 60.0       # 对齐 EMBEDDING_K
    _K_ES = 40.0          # 对齐 ES_K（VDB sparse/BM25 路的 RRF K 值）
    _K_SUMMARY = 60.0
    _K_META_TEXT = 60.0

    # 多切片命中衰减（同一文档多个 chunk 命中时，按分数降序几何衰减聚合）
    _CHUNK_DECAY = 0.2

    # 三维度权重
    _ALPHA = 0.7
    _BETA = 0.1
    _GAMMA = 0.2

    # 元数据加权子权重
    _METADATA_WEIGHT = 0.15
    _MAX_METADATA_BOOST = (1.0 / (_K_SUMMARY + 1) + 1.0 / (_K_META_TEXT + 1)) * _METADATA_WEIGHT

    # 文档属性子权重
    _QUALITY_WEIGHT = 0.1
    _RECENCY_WEIGHT = 0.05
    _HIT_WEIGHT = 0.05
    _MAX_ATTR_BOOST = _QUALITY_WEIGHT + _RECENCY_WEIGHT + _HIT_WEIGHT
    _RECENCY_HALFLIFE_MS = 180.0 * 24 * 60 * 60 * 1000

    # threshold 默认值
    _DEFAULT_THRESHOLD = 0.3

    # 切片回查字段（VDB 直接返回，不再回 PG）
    _CHUNK_OUTPUT_FIELDS = [
        "id", "doc_id", "chunk_index", "content", "section_title",
        "chunk_type", "doc_category", "industry", "business_stage",
        "target_audience", "product_service", "date_published",
    ]

    def __init__(
        self,
        vector_store: KnowledgeVectorStore,
        lkeap: TencentLKEAPClient | None = None,
        llm: Any = None,
        embedding_fn: Any = None,
        expand_context_n: int = 1,
    ) -> None:
        self._vdb = vector_store
        self._lkeap = lkeap
        self._llm = llm
        self._embedding_fn = embedding_fn
        self._expand_n = expand_context_n

    # ── 对外入口 ──

    async def search(
        self,
        tenant_id: int,
        query: str,
        knowledge_base_id: int | None = None,
        filters: dict | None = None,
        top_k: int = 5,
        threshold: float | None = None,
        enable_self_query: bool = True,
        conversation_history: list | None = None,
        user_id: str = "",
        thread_id: str = "",
        trace_id: str = "",
    ) -> list[KnowledgeChunk]:
        """完整检索流水线（全 VDB）

        threshold 优先级：调用方显式 > KB.min_score > _DEFAULT_THRESHOLD
        """
        t0 = time.time()
        timings: dict[str, int] = {}

        effective_threshold = await self._resolve_threshold(threshold, knowledge_base_id)

        # Step 1: 查询改写 + 关键词提取
        rewritten_query = query
        extracted_keywords: list[str] = []
        if self._llm and conversation_history:
            ts = time.time()
            try:
                rw = await self._rewrite_query(query, conversation_history)
                rewritten_query = rw.get("rewritten_query", query)
                extracted_keywords = rw.get("keywords", [])
            except Exception as exc:
                logger.warning("Query rewrite failed: %s", exc)
            timings["rewrite_ms"] = int((time.time() - ts) * 1000)

        # Step 2: Self-Querying
        semantic_query = rewritten_query
        effective_filters = filters or {}
        if enable_self_query and self._llm and not filters:
            ts = time.time()
            try:
                sq = await self._self_query(rewritten_query, tenant_id, knowledge_base_id)
                semantic_query = sq.get("semantic_query", rewritten_query)
                effective_filters = sq.get("filters") or {}
            except Exception as exc:
                logger.warning("Self-query failed: %s", exc)
            timings["self_query_ms"] = int((time.time() - ts) * 1000)

        # Step 3: Phase 1 — 全局召回（不带元数据 filter 的切片 + 带 filter 的文档元数据）
        # 对齐 data-process: ①② 全局切片 + ③④ 元数据召回
        ts = time.time()
        global_chunk_filter = self._build_chunk_filter(knowledge_base_id, {})  # 全局不带元数据 filter
        doc_filter = self._build_doc_filter(knowledge_base_id, effective_filters)
        chunk_limit = max(top_k * 5, 30)
        doc_limit = max(top_k * 5, 50)

        query_vec: list[float] = []
        try:
            query_vec = await self._embed(semantic_query)
        except Exception as exc:
            logger.warning("Embedding failed: %s", exc)

        chunk_results_global, doc_meta_hybrid = await asyncio.gather(
            self._recall_chunks(
                tenant_id, query_vec, semantic_query, global_chunk_filter, chunk_limit,
            ),
            self._recall_doc_metadata_hybrid(
                tenant_id, query_vec, semantic_query, doc_filter, doc_limit,
            ),
            return_exceptions=True,
        )

        if isinstance(chunk_results_global, Exception):
            logger.warning("Chunk recall (global) failed: %s", chunk_results_global)
            chunk_results_global = []
        if isinstance(doc_meta_hybrid, Exception):
            logger.debug("Doc metadata hybrid recall failed: %s", doc_meta_hybrid)
            doc_meta_hybrid = []

        # B1+B2 合并后按融合分排序的 doc_id 列表（用于 β 维度 + Phase 2 定向）
        doc_meta_rank: list[str] = [r.get("id", "") for r in doc_meta_hybrid if r.get("id")]

        # 路B 降级：如果带 filter 的路B返回 0 结果，去掉分类条件重试
        # 场景：Self-Querying 提取了 {docCategory:"产品手册", industryVertical:"制造业"}
        #       但知识库中文档未被打标为这些值 → 路B返回0
        # 降级：去掉分类条件，仅按语义（摘要向量+BM25）召回文档
        # 目的：确保 β 维度有打分数据 + Phase 2 有定向范围
        doc_meta_filter_fallback = False
        if not doc_meta_rank and effective_filters and query_vec:
            logger.info(
                "Doc metadata hybrid: 0 results with filters=%s. "
                "Retrying without category filters (pure semantic) for β scoring + Phase 2.",
                effective_filters,
            )
            fallback_doc_filter = self._build_doc_filter(knowledge_base_id, {})
            try:
                doc_meta_fb = await self._recall_doc_metadata_hybrid(
                    tenant_id, query_vec, semantic_query, fallback_doc_filter, doc_limit,
                )
                if not isinstance(doc_meta_fb, Exception) and doc_meta_fb:
                    doc_meta_hybrid = doc_meta_fb
                    doc_meta_rank = [r.get("id", "") for r in doc_meta_hybrid if r.get("id")]
                    doc_meta_filter_fallback = True
                    logger.info(
                        "Doc metadata fallback success: %d docs recovered (pure semantic, no category filter)",
                        len(doc_meta_rank),
                    )
            except Exception as exc:
                logger.debug("Doc metadata fallback failed: %s", exc)

        timings["phase1_ms"] = int((time.time() - ts) * 1000)
        logger.debug(
            "Phase1 recall: global_chunks=%d doc_meta=%d",
            len(chunk_results_global), len(doc_meta_rank),
        )

        # Step 3.5: Phase 2 — 定向召回（对齐 data-process Phase 2）
        # 仅当有元数据过滤条件且文档元数据 RRF 有结果时触发
        # 用元数据 RRF 命中的 Top-50 文档 ID 作为定向范围，在这些文档内精确搜切片
        chunk_results_targeted: list[dict] = []
        has_filters = bool(effective_filters)
        if has_filters and doc_meta_rank and query_vec:
            ts_p2 = time.time()
            target_doc_ids = doc_meta_rank[:50]  # 上限 50，避免 filter 过长
            targeted_filter = self._build_chunk_filter_with_doc_ids(
                knowledge_base_id, target_doc_ids,
            )
            targeted_limit = max(top_k * 3, 20)
            try:
                chunk_results_targeted = await self._recall_chunks(
                    tenant_id, query_vec, semantic_query, targeted_filter, targeted_limit,
                )
            except Exception as exc:
                logger.warning("Phase2 targeted recall failed: %s", exc)
                chunk_results_targeted = []
            timings["phase2_ms"] = int((time.time() - ts_p2) * 1000)
            logger.debug(
                "Phase2 targeted recall: target_docs=%d chunks=%d",
                len(target_doc_ids), len(chunk_results_targeted),
            )

        # Phase 3: 合并去重（全局 ∪ 定向），按 score 降序
        chunk_results = self._merge_chunk_results(chunk_results_global, chunk_results_targeted)

        # 安全机制：如果合并后仍为空且有 filter，去掉过滤重试文档元数据
        if not chunk_results and effective_filters and query_vec:
            logger.info(
                "Recall empty with filters=%s, retrying doc_meta without filters",
                effective_filters,
            )
            fallback_doc_filter = self._build_doc_filter(knowledge_base_id, {})
            try:
                doc_meta_fb = await self._recall_doc_metadata_hybrid(
                    tenant_id, query_vec, semantic_query, fallback_doc_filter, doc_limit,
                )
                if doc_meta_fb:
                    doc_meta_hybrid = doc_meta_fb
                    doc_meta_rank = [r.get("id", "") for r in doc_meta_hybrid if r.get("id")]
            except Exception:
                pass
            # 用全局无 filter 的切片结果（Phase 1 已经是全局的）
            chunk_results = chunk_results_global
            effective_filters = {}
            if chunk_results:
                logger.info("Fallback: using global chunks=%d", len(chunk_results))

        summary_doc_ids = doc_meta_rank
        meta_bm25_doc_ids = doc_meta_rank

        timings["vector_search_ms"] = int((time.time() - ts) * 1000)
        logger.debug(
            "Multi-path recall final: chunks=%d (global=%d targeted=%d) doc_meta=%d",
            len(chunk_results), len(chunk_results_global),
            len(chunk_results_targeted), len(doc_meta_rank),
        )

        # Step 4: 把 VDB 切片结果包装成 KnowledgeChunk（Hydrate + 扩展）
        chunks = await self._hydrate_and_expand(chunk_results, tenant_id)
        if not chunks:
            asyncio.create_task(self._log_search(
                tenant_id=tenant_id, knowledge_base_id=knowledge_base_id,
                user_id=user_id, thread_id=thread_id, trace_id=trace_id,
                raw_query=query, rewritten_query=rewritten_query,
                semantic_query=semantic_query, filters=effective_filters,
                chunks=[], vector_hit=len(chunk_results), bm25_hit=0,
                timings=timings, total_ms=int((time.time() - t0) * 1000),
            ))
            return []

        # Step 5: 三维度归一化加权（γ 属性从 VDB 文档元数据集合读）
        doc_cache = await self._load_doc_meta_cache(chunks, tenant_id)
        chunks = self._score_and_rank(
            chunks=chunks,
            summary_rank=summary_doc_ids,
            meta_text_rank=meta_bm25_doc_ids,
            doc_cache=doc_cache,
            threshold=effective_threshold,
            top_k=top_k,
        )

        if chunks:
            logger.debug(
                "Final ranked: hits=%d top_score=%.4f threshold=%.4f",
                len(chunks), chunks[0].score, effective_threshold,
            )
        else:
            logger.info(
                "No chunks passed threshold=%.4f (raw hits=%d)",
                effective_threshold, len(chunk_results),
            )

        if chunks:
            asyncio.create_task(self._record_hits(chunks))

        total_ms = int((time.time() - t0) * 1000)
        asyncio.create_task(self._log_search(
            tenant_id=tenant_id, knowledge_base_id=knowledge_base_id,
            user_id=user_id, thread_id=thread_id, trace_id=trace_id,
            raw_query=query, rewritten_query=rewritten_query,
            semantic_query=semantic_query, filters=effective_filters,
            chunks=chunks, vector_hit=len(chunk_results),
            bm25_hit=len(summary_doc_ids) + len(meta_bm25_doc_ids),
            timings=timings, total_ms=total_ms,
        ))

        return chunks

    # ══════════════════════════════════════════════════════
    # 召回（三路）
    # ══════════════════════════════════════════════════════

    async def _recall_chunks(
        self, tenant_id: int, query_vec: list[float], query_text: str,
        filter_expr: str, top_k: int,
    ) -> list[dict]:
        """A 路：VDB 切片 hybrid_search（dense + sparse）"""
        if not query_vec:
            return []
        return await asyncio.to_thread(
            self._vdb.search_chunks,
            tenant_id=str(tenant_id),
            vector=query_vec,
            query_text=query_text,
            extra_filter=filter_expr,
            top_k=top_k,
            output_fields=self._CHUNK_OUTPUT_FIELDS,
        )

    async def _recall_doc_metadata_hybrid(
        self, tenant_id: int, query_vec: list[float], query_text: str,
        doc_filter: str, top_k: int,
    ) -> list[dict]:
        """B 路合并：文档级 hybrid_search（一次调用融合 ANN + BM25）"""
        if not query_vec:
            return []
        return await asyncio.to_thread(
            self._vdb.search_doc_metadata_hybrid,
            tenant_id=str(tenant_id),
            query_vector=query_vec,
            query_text=query_text,
            extra_filter=doc_filter,
            top_k=top_k,
        )

    # ══════════════════════════════════════════════════════
    # 三维度归一化加权
    # ══════════════════════════════════════════════════════

    def _score_and_rank(
        self,
        chunks: list[KnowledgeChunk],
        summary_rank: list[str],
        meta_text_rank: list[str],
        doc_cache: dict[str, dict],
        threshold: float,
        top_k: int,
    ) -> list[KnowledgeChunk]:
        """三维度归一化加权排序（对齐 data-process normalizeAndMerge）

        与 data-process 的对齐点：
        1. RRF 归一化使用理论锚点（theoreticalMax/Min），而非实际 min-max
        2. finalScore = rawScore * (1 - threshold) + threshold 映射到 [threshold, 1]
        3. 元数据/属性归一化方式一致
        """
        if not chunks:
            return chunks

        # ── 1. 切片 A 路 RRF 贡献（对齐 computeSegmentRrf） ──
        # VDB hybrid_search 返回的 score 已经是融合分，按 score 降序排名
        chunks_sorted = sorted(chunks, key=lambda c: c.score, reverse=True)
        chunk_rrf: dict[str, float] = {}
        for rank, c in enumerate(chunks_sorted):
            if c.chunk_id:
                # 对齐 data-process: 向量路 1/(EMBEDDING_K + rank + 1)
                # VDB hybrid_search 已融合 dense+sparse，视为等价于
                # data-process 中 embedding + ES 两路 RRF 的合并结果
                chunk_rrf[c.chunk_id] = 1.0 / (self._K_CHUNK + rank + 1)

        # ── 2. 按 doc_id 分组聚合（几何衰减，对齐 aggregateToDocLevel） ──
        doc_chunks: dict[str, list[tuple[KnowledgeChunk, float]]] = {}
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
                agg += items[i][1] * math.pow(self._CHUNK_DECAY, i)
            doc_rrf[did] = agg

        # ── 3. 维度 A 归一化：理论锚点归一化 → [0, 1]（对齐 data-process） ──
        # 理论最大 RRF = 排名第 1 时的单切片得分 = 1/(K+1)
        # 理论最小 RRF = 排名最后时的得分 ≈ 1/(K + chunk_limit + 1)
        chunk_limit = len(chunks_sorted)
        theoretical_max_rrf = 1.0 / (self._K_CHUNK + 1)
        theoretical_min_rrf = 1.0 / (self._K_CHUNK + chunk_limit + 1)
        rrf_range = theoretical_max_rrf - theoretical_min_rrf

        doc_norm_a: dict[str, float] = {}
        for did, score in doc_rrf.items():
            if rrf_range > 0:
                norm = (score - theoretical_min_rrf) / rrf_range
                doc_norm_a[did] = max(0.0, min(1.0, norm))
            else:
                doc_norm_a[did] = 0.5

        # ── 4. 维度 B：元数据加权（对齐 computeMetadataBoost） ──
        doc_norm_b: dict[str, float] = {}
        doc_ids_all = set(doc_chunks.keys())
        for did in doc_ids_all:
            boost = 0.0
            try:
                idx_s = summary_rank.index(did)
                boost += 1.0 / (self._K_SUMMARY + idx_s + 1)
            except ValueError:
                pass
            try:
                idx_m = meta_text_rank.index(did)
                boost += 1.0 / (self._K_META_TEXT + idx_m + 1)
            except ValueError:
                pass
            boost *= self._METADATA_WEIGHT
            doc_norm_b[did] = (
                min(boost / self._MAX_METADATA_BOOST, 1.0)
                if self._MAX_METADATA_BOOST > 0 else 0.0
            )

        # ── 5. 维度 C：文档属性（对齐 computeAttributeBoost） ──
        now_ms = int(time.time() * 1000)
        doc_norm_c: dict[str, float] = {}
        for did in doc_ids_all:
            meta = doc_cache.get(did) or {}
            # quality_score 写入时 ×10000 存 Uint64，读取时 ÷10000 复原
            if "quality_score_x10k" in meta:
                quality = float(meta.get("quality_score_x10k") or 0) / 10000.0
            else:
                quality = float(meta.get("quality_score") or 0.5)
            quality = max(0.0, min(1.0, quality)) if quality else 0.5

            recency = 0.5
            ref_ts = int(meta.get("date_published") or 0) or int(meta.get("created_at") or 0)
            if ref_ts and ref_ts > 0:
                age_ms = max(0, now_ms - ref_ts)
                recency = math.pow(0.5, age_ms / self._RECENCY_HALFLIFE_MS)

            hit_score = 0.0
            hit = int(meta.get("search_hit_count") or 0)
            if hit > 0:
                hit_score = min(1.0, math.log10(hit + 1) / math.log10(1000))

            attribute_boost = (
                quality * self._QUALITY_WEIGHT
                + recency * self._RECENCY_WEIGHT
                + hit_score * self._HIT_WEIGHT
            )
            doc_norm_c[did] = min(attribute_boost / self._MAX_ATTR_BOOST, 1.0)

        # ── 6. 三维度加权合并 + 映射到 [threshold, 1]（对齐 data-process） ──
        for c in chunks:
            did = c.document_id or ""
            na = doc_norm_a.get(did, 0.0)
            nb = doc_norm_b.get(did, 0.0)
            nc = doc_norm_c.get(did, 0.0)
            # rawScore ∈ [0, 1]
            raw_score = self._ALPHA * na + self._BETA * nb + self._GAMMA * nc
            # 映射到 [threshold, 1.0]，与 data-process 对齐
            final_score = raw_score * (1.0 - threshold) + threshold
            c.score = round(final_score, 4)

        # ── 7. threshold 过滤 + 排序 + top_k ──
        if threshold > 0:
            chunks = [c for c in chunks if c.score >= threshold]
        chunks.sort(key=lambda c: c.score, reverse=True)
        return chunks[:top_k]

    async def _load_doc_meta_cache(
        self, chunks: list[KnowledgeChunk], tenant_id: int,
    ) -> dict[str, dict]:
        """批量从 VDB kb_doc_metadata 拉文档属性（γ 维度数据源）"""
        doc_ids = list({c.document_id for c in chunks if c.document_id})
        if not doc_ids:
            return {}
        try:
            return await asyncio.to_thread(
                self._vdb.get_doc_metadata,
                tenant_id=str(tenant_id),
                doc_ids=doc_ids,
            )
        except Exception as exc:
            logger.debug("Load doc metadata cache failed: %s", exc)
            return {}

    async def _resolve_threshold(
        self, explicit: float | None, kb_id: int | None,
    ) -> float:
        if explicit is not None:
            return max(0.0, min(1.0, float(explicit)))
        if kb_id:
            try:
                kb = await asyncio.to_thread(KnowledgeBaseDAO.get_by_id, kb_id)
            except Exception as exc:
                logger.debug("Resolve threshold: KB query failed: %s", exc)
                kb = None
            if kb and kb.min_score is not None and kb.min_score > 0:
                return max(0.0, min(1.0, float(kb.min_score)))
        return self._DEFAULT_THRESHOLD

    # ══════════════════════════════════════════════════════
    # Query Rewrite / Self-Querying / Embedding
    # ══════════════════════════════════════════════════════

    async def _rewrite_query(
        self, query: str, conversation_history: list | None,
    ) -> dict:
        """查询改写 + 关键词提取

        返回:
            {
                "rewritten_query": "改写后的查询",
                "keywords": ["关键词1", "关键词2"],
                "intent": "用户意图",
                "expansion_terms": ["扩展词1"]
            }
        """
        if not self._llm:
            return {"rewritten_query": query, "keywords": self._local_keywords(query)}

        # 构建对话历史文本
        history_text = "无对话历史"
        if conversation_history:
            parts = []
            for msg in conversation_history[-6:]:
                role = msg.get("role", "user")
                content = msg.get("content", "")[:200]
                parts.append(f"[{role}]: {content}")
            history_text = "\n".join(parts) if parts else "无对话历史"

        prompt = QUERY_REWRITE_PROMPT.format(
            conversation_history=history_text,
            query=query,
        )

        try:
            resp = await self._llm.ainvoke(prompt)
            text = getattr(resp, "content", None) or str(resp)
        except Exception as exc:
            logger.warning("Query rewrite LLM call failed: %s", exc)
            return {"rewritten_query": query, "keywords": self._local_keywords(query)}

        from .ingestion import _extract_json_object
        parsed = _extract_json_object(text)
        if parsed is None:
            logger.warning("Query rewrite response not valid JSON: %s", text[:200])
            return {"rewritten_query": query, "keywords": self._local_keywords(query)}

        result = {
            "rewritten_query": parsed.get("rewritten_query") or query,
            "keywords": parsed.get("keywords") or [],
            "intent": parsed.get("intent") or "",
            "expansion_terms": parsed.get("expansion_terms") or [],
        }
        # 确保 keywords 是列表
        if not isinstance(result["keywords"], list):
            result["keywords"] = [str(result["keywords"])]

        return result

    def _local_keywords(self, text: str) -> list[str]:
        """本地关键词提取（jieba TF-IDF，不依赖 LLM）"""
        if not text:
            return []
        try:
            import jieba.analyse
            keywords = jieba.analyse.extract_tags(text, topK=8, withWeight=False)
            return keywords
        except Exception:
            # jieba 不可用时用简单分词
            return self._tokenize(text)[:8]

    async def _self_query(
        self, query: str, tenant_id: int, kb_id: int | None,
    ) -> dict:
        schema_row = None
        if kb_id:
            schema_row = await asyncio.to_thread(
                KnowledgeSchemaDAO.get_for_kb, tenant_id, kb_id,
            )
        if not schema_row or not schema_row.fields:
            return {"semantic_query": query, "filters": {}}

        try:
            fields_def = json.loads(schema_row.fields)
        except json.JSONDecodeError:
            return {"semantic_query": query, "filters": {}}

        prompt = SELF_QUERY_PROMPT.format(
            schema_fields=json.dumps(fields_def, ensure_ascii=False, indent=2),
            query=query,
        )
        try:
            resp = await self._llm.ainvoke(prompt)
            text = getattr(resp, "content", None) or str(resp)
        except Exception as exc:
            logger.warning("Self-query LLM call failed: %s", exc)
            return {"semantic_query": query, "filters": {}}

        from .ingestion import _extract_json_object
        parsed = _extract_json_object(text)
        if parsed is None:
            logger.warning("Self-query response not valid JSON: %s", text[:200])
            return {"semantic_query": query, "filters": {}}

        return {
            "semantic_query": parsed.get("semantic_query") or query,
            "filters": parsed.get("filters") or {},
        }

    async def _embed(self, text: str) -> list[float]:
        if self._embedding_fn is None:
            if self._lkeap is None:
                raise RuntimeError("embedding_fn and lkeap both None")
            vecs = await asyncio.to_thread(self._lkeap.get_embedding, [text])
            return vecs[0] if vecs else []
        if asyncio.iscoroutinefunction(self._embedding_fn):
            return await self._embedding_fn(text)
        return await asyncio.to_thread(self._embedding_fn, text)

    # ══════════════════════════════════════════════════════
    # Filter 构造
    # ══════════════════════════════════════════════════════

    def _build_chunk_filter(
        self, knowledge_base_id: int | None, filters: dict,
    ) -> str:
        """切片集合的 filter 表达式（kb_chunks）"""
        parts: list[str] = []
        if knowledge_base_id:
            parts.append(f'knowledge_base_id = "{knowledge_base_id}"')
        parts.append('status = "active"')

        allowed = {
            "dataset_id": "dataset_id",
            "doc_id": "doc_id",
            "chunk_type": "chunk_type",
            "docCategory": "doc_category",
            "industryVertical": "industry",
            "businessStage": "business_stage",
            "targetAudience": "target_audience",
            "productService": "product_service",
            "doc_category": "doc_category",
            "industry": "industry",
            "business_stage": "business_stage",
            "target_audience": "target_audience",
            "product_service": "product_service",
        }
        for key, val in filters.items():
            col = allowed.get(key)
            if not col or val is None or val == "":
                continue
            if isinstance(val, (list, tuple)):
                if not val:
                    continue
                ors = " or ".join(f'{col} = "{self._escape(v)}"' for v in val)
                parts.append(f"({ors})")
            else:
                parts.append(f'{col} = "{self._escape(val)}"')
        return " and ".join(parts)

    def _build_doc_filter(
        self, knowledge_base_id: int | None, filters: dict,
    ) -> str:
        """文档元数据集合的 filter 表达式（kb_doc_metadata）"""
        parts: list[str] = []
        if knowledge_base_id:
            parts.append(f'knowledge_base_id = "{knowledge_base_id}"')
        parts.append('status = "active"')

        allowed = {
            "dataset_id": "dataset_id",
            "docCategory": "doc_category",
            "industryVertical": "industry",
            "businessStage": "business_stage",
            "targetAudience": "target_audience",
            "productService": "product_service",
            "doc_category": "doc_category",
            "industry": "industry",
            "business_stage": "business_stage",
            "target_audience": "target_audience",
            "product_service": "product_service",
        }
        for key, val in filters.items():
            col = allowed.get(key)
            if not col or val is None or val == "":
                continue
            if isinstance(val, (list, tuple)):
                if not val:
                    continue
                ors = " or ".join(f'{col} = "{self._escape(v)}"' for v in val)
                parts.append(f"({ors})")
            else:
                parts.append(f'{col} = "{self._escape(val)}"')
        return " and ".join(parts)

    def _build_chunk_filter_with_doc_ids(
        self, knowledge_base_id: int | None, doc_ids: list[str],
    ) -> str:
        """构建定向召回的 filter：限定在指定文档 ID 范围内（对齐 data-process Phase 2）

        不带元数据 filter（因为已经通过 doc_ids 间接过滤了），
        只限定 kb_id + status + doc_id in [...]。
        """
        parts: list[str] = []
        if knowledge_base_id:
            parts.append(f'knowledge_base_id = "{knowledge_base_id}"')
        parts.append('status = "active"')
        if doc_ids:
            ors = " or ".join(f'doc_id = "{self._escape(did)}"' for did in doc_ids)
            parts.append(f"({ors})")
        return " and ".join(parts)

    @staticmethod
    def _merge_chunk_results(
        global_results: list[dict], targeted_results: list[dict],
    ) -> list[dict]:
        """合并去重全局召回和定向召回的切片结果（对齐 data-process mergeSegments）

        去重策略：同一 chunk_id 保留 score 更高的那条。
        合并后按 score 降序排列。
        """
        if not targeted_results:
            return global_results
        if not global_results:
            return targeted_results

        merged: dict[str, dict] = {}
        for r in global_results:
            cid = r.get("id", "")
            if cid:
                merged[cid] = r

        for r in targeted_results:
            cid = r.get("id", "")
            if not cid:
                continue
            existing = merged.get(cid)
            if existing is None or float(r.get("score", 0)) > float(existing.get("score", 0)):
                merged[cid] = r

        result = list(merged.values())
        result.sort(key=lambda x: float(x.get("score", 0)), reverse=True)
        return result

    @staticmethod
    def _escape(val) -> str:
        return str(val).replace('"', '\\"')

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """jieba 分词（保留接口，某些单测会用）"""
        if not text:
            return []
        try:
            import jieba
            tokens = jieba.lcut(text.strip())
        except Exception:
            tokens = re.split(r"[^\w\u4e00-\u9fff]+", text)
        cleaned: list[str] = []
        seen: set[str] = set()
        for t in tokens:
            t = t.strip()
            if not t or t in seen:
                continue
            if len(t) >= 2 or (len(t) == 1 and "\u4e00" <= t <= "\u9fff"):
                cleaned.append(t)
                seen.add(t)
        return cleaned[:20]

    # ══════════════════════════════════════════════════════
    # Hydrate
    # ══════════════════════════════════════════════════════

    async def _hydrate_and_expand(
        self, vdb_results: list[dict], tenant_id: int,
    ) -> list[KnowledgeChunk]:
        """把 VDB 切片结果包装成 KnowledgeChunk。

        VDB 直接返回 content / section_title / doc_id / chunk_index / 业务字段，
        **不再回 PG 拉全文**（除 document_title 外）。
        Parent-Child 扩展改走 VDB 的 chunk_index 范围查询。
        """
        if not vdb_results:
            return []

        # 预加载每个 doc 的 title（从 VDB kb_doc_metadata 读一次即可）
        doc_ids = list({r.get("doc_id", "") for r in vdb_results if r.get("doc_id")})
        doc_titles: dict[str, str] = {}
        if doc_ids:
            try:
                metas = await asyncio.to_thread(
                    self._vdb.get_doc_metadata,
                    tenant_id=str(tenant_id),
                    doc_ids=doc_ids,
                    output_fields=["id", "title"],
                )
                doc_titles = {did: (m.get("title") or "") for did, m in metas.items()}
            except Exception as exc:
                logger.debug("Load doc titles failed: %s", exc)

        result: list[KnowledgeChunk] = []
        for r in vdb_results:
            cid = r.get("id", "")
            if not cid:
                continue
            doc_id = r.get("doc_id", "")
            content = r.get("content") or ""
            score = float(r.get("score", 0.0))

            chunk = KnowledgeChunk(
                content=content,
                score=score,
                metadata=self._vdb_metadata(r),
                document_id=doc_id,
                document_title=doc_titles.get(doc_id, ""),
                chunk_id=cid,
                chunk_index=int(r.get("chunk_index") or 0),
                section_title=r.get("section_title", "") or "",
                section_path="",  # 切片未携带 section_path（如需，可在 VDB 加字段）
                chunk_type=r.get("chunk_type", "") or "",
            )
            # Parent-Child 扩展
            if self._expand_n > 0 and doc_id:
                chunk.expanded_context = await self._expand_context_vdb(
                    tenant_id=tenant_id,
                    doc_id=doc_id,
                    chunk_index=chunk.chunk_index,
                    exclude_chunk_id=cid,
                    expand_n=self._expand_n,
                )
            result.append(chunk)

        return result

    async def _expand_context_vdb(
        self, tenant_id: int, doc_id: str, chunk_index: int,
        exclude_chunk_id: str, expand_n: int,
    ) -> str:
        """从 VDB kb_chunks 按 chunk_index 范围拉前后 N 个切片"""
        if expand_n <= 0 or not doc_id:
            return ""
        start = max(0, chunk_index - expand_n)
        end = chunk_index + expand_n
        try:
            rows = await asyncio.to_thread(
                self._vdb.list_chunks_by_doc_range,
                tenant_id=str(tenant_id),
                doc_id=doc_id,
                start_index=start,
                end_index=end,
                output_fields=["id", "content", "chunk_index"],
            )
        except Exception as exc:
            logger.debug("Expand context VDB failed: %s", exc)
            return ""

        parts: list[str] = []
        for row in rows:
            if row.get("id") == exclude_chunk_id:
                continue
            ct = row.get("content") or ""
            if ct:
                parts.append(ct)
        return "\n\n".join(parts)

    @staticmethod
    def _vdb_metadata(r: dict) -> dict:
        return {
            "doc_id": r.get("doc_id", ""),
            "chunk_id": r.get("id", ""),
            "chunk_type": r.get("chunk_type", ""),
            "section_title": r.get("section_title", ""),
            "docCategory": r.get("doc_category", ""),
            "industryVertical": r.get("industry", ""),
            "businessStage": r.get("business_stage", ""),
            "targetAudience": r.get("target_audience", ""),
            "productService": r.get("product_service", ""),
            "datePublished": r.get("date_published", 0),
        }

    # ══════════════════════════════════════════════════════
    # 异步后处理
    # ══════════════════════════════════════════════════════

    async def _record_hits(self, chunks: list[KnowledgeChunk]) -> None:
        """命中热度 +1（仅写 PG；VDB 的 search_hit_count 由调度任务批量同步）"""
        try:
            doc_ids = list({c.document_id for c in chunks if c.document_id})
            for did in doc_ids:
                await asyncio.to_thread(KnowledgeDocumentDAO.increment_hit, did)
        except Exception as exc:
            logger.debug("Record hits failed (non-fatal): %s", exc)

    async def _log_search(
        self,
        tenant_id: int,
        knowledge_base_id: int | None,
        user_id: str,
        thread_id: str,
        trace_id: str,
        raw_query: str,
        rewritten_query: str,
        semantic_query: str,
        filters: dict,
        chunks: list[KnowledgeChunk],
        vector_hit: int,
        bm25_hit: int,
        timings: dict,
        total_ms: int,
    ) -> None:
        try:
            log = KnowledgeSearchLogRow(
                tenant_id=tenant_id,
                knowledge_base_id=knowledge_base_id or 0,
                user_id=user_id,
                thread_id=thread_id,
                trace_id=trace_id,
                raw_query=raw_query[:2000],
                rewritten_query=rewritten_query[:2000],
                semantic_query=semantic_query[:2000],
                filters=json.dumps(filters, ensure_ascii=False)[:2000],
                hit_chunk_ids=json.dumps(
                    [c.chunk_id for c in chunks], ensure_ascii=False,
                )[:2000],
                hit_count=len(chunks),
                top_score=chunks[0].score if chunks else 0.0,
                vector_hit_count=vector_hit,
                bm25_hit_count=bm25_hit,
                rewrite_ms=timings.get("rewrite_ms", 0),
                self_query_ms=timings.get("self_query_ms", 0),
                vector_search_ms=timings.get("vector_search_ms", 0),
                bm25_search_ms=timings.get("bm25_search_ms", 0),
                rerank_ms=timings.get("rerank_ms", 0),
                total_ms=total_ms,
            )
            await asyncio.to_thread(KnowledgeSearchLogDAO.insert, log)
        except Exception as exc:
            logger.debug("Log search failed (non-fatal): %s", exc)
