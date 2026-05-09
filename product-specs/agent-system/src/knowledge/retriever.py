"""知识检索引擎 — 多路召回 + RRF + 归一化多维度加权（全 VDB 版）

对应 doc/知识库体系设计方案.md §五。

检索链路：
    Query
      ├── [A] VDB kb_chunks.hybrid_search   → 切片级 dense+sparse (BM25)
      ├── [B1] VDB kb_doc_metadata ANN      → 文档级摘要向量召回（rank）
      └── [B2] VDB kb_doc_metadata 多路 BM25 → 文档级 5 路稀疏召回（rank）
      ▼
    切片 → 文档聚合（docScore = seg[0] + Σ seg[i] × 0.2^i）
      ▼
    三维度归一化加权（finalScore = α·normA + β·normB + γ·normC）
      α (0.7): 切片 RRF 聚合分 → [floor, 1]
      β (0.1): B1+B2 两路 RRF → [0, 1]
      γ (0.2): quality + recency + hit → [0, 1]（来自 VDB 文档属性）
      ▼
    threshold 过滤 + 排序 → top_k
      ▼
    Hydrate 扩展（VDB content 字段直接返回，不回 PG）
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

SELF_QUERY_PROMPT = """你是一个查询分析器。根据用户的自然语言查询，判断是否需要元数据过滤。

## 可用的过滤字段
{schema_fields}

## 用户查询
{query}

## 输出要求
以 JSON 格式输出（不要任何其他说明文字）：
{{
  "semantic_query": "用于语义检索的核心查询（去除过滤条件后的问题）",
  "filters": {{
    "字段名": "值"
  }}
}}

如果没有明确过滤意图，filters 返回空对象 {{}}。
字段值必须从 Schema 枚举值中选择，不要自创。

示例：
- "制造业的成功案例" → {{"semantic_query": "成功案例", "filters": {{"docCategory": "成功案例", "industryVertical": "制造业"}}}}
- "怎么配置审批流" → {{"semantic_query": "怎么配置审批流", "filters": {{}}}}
"""


# ═══════════════════════════════════════════════════════════
# KnowledgeRetriever
# ═══════════════════════════════════════════════════════════

class KnowledgeRetriever:
    """知识检索引擎 — 全 VDB 多路召回 + 归一化多维度加权"""

    # ── 融合参数（对齐 data-process DocumentSearchServiceImpl） ──
    _K_CHUNK = 60.0
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

    # 归一化下限（防 β/γ 喧宾夺主）
    _NORM_FLOOR = 0.3

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

        # Step 1: 查询改写（预留）
        rewritten_query = query

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

        # Step 3: 三路并行召回
        ts = time.time()
        filter_expr = self._build_chunk_filter(knowledge_base_id, effective_filters)
        doc_filter = self._build_doc_filter(knowledge_base_id, effective_filters)
        chunk_limit = max(top_k * 5, 30)
        doc_limit = max(top_k * 5, 50)

        query_vec: list[float] = []
        try:
            query_vec = await self._embed(semantic_query)
        except Exception as exc:
            logger.warning("Embedding failed: %s", exc)

        chunk_results, doc_meta_hybrid = await asyncio.gather(
            self._recall_chunks(
                tenant_id, query_vec, semantic_query, filter_expr, chunk_limit,
            ),
            self._recall_doc_metadata_hybrid(
                tenant_id, query_vec, semantic_query, doc_filter, doc_limit,
            ),
            return_exceptions=True,
        )

        if isinstance(chunk_results, Exception):
            logger.warning("Chunk recall failed: %s", chunk_results)
            chunk_results = []
        if isinstance(doc_meta_hybrid, Exception):
            logger.debug("Doc metadata hybrid recall failed: %s", doc_meta_hybrid)
            doc_meta_hybrid = []

        # B1+B2 合并后按融合分排序的 doc_id 列表（用于 β 维度单路 RRF）
        doc_meta_rank: list[str] = [r.get("id", "") for r in doc_meta_hybrid if r.get("id")]

        # 为保持 β 维度兼容（summary_rank + meta_text_rank），把同一个排名列表
        # 作为两路的替身：每个 doc 的 β 贡献仍是"在单一融合排名里的位置 × 2"
        # 这样 MAX_METADATA_BOOST 常量定义不变，行为与原版 RRF(summary + meta_text) 近似
        summary_doc_ids = doc_meta_rank
        meta_bm25_doc_ids = doc_meta_rank

        timings["vector_search_ms"] = int((time.time() - ts) * 1000)
        logger.debug(
            "Multi-path recall: chunks=%d doc_meta_hybrid=%d",
            len(chunk_results), len(doc_meta_rank),
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
        if not chunks:
            return chunks

        # ── 1. 切片 A 路 RRF 贡献 ──
        chunks_sorted = sorted(chunks, key=lambda c: c.score, reverse=True)
        chunk_rrf: dict[str, float] = {}
        for rank, c in enumerate(chunks_sorted):
            if c.chunk_id:
                chunk_rrf[c.chunk_id] = 1.0 / (self._K_CHUNK + rank + 1)

        # ── 2. 按 doc_id 分组聚合（几何衰减）──
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

        # ── 3. 维度 A 归一化到 [NORM_FLOOR, 1] ──
        floor = self._NORM_FLOOR
        if doc_rrf:
            max_rrf = max(doc_rrf.values())
            min_rrf = min(doc_rrf.values())
            rrf_range = max_rrf - min_rrf
        else:
            max_rrf = min_rrf = 0.0
            rrf_range = 0.0

        doc_norm_a: dict[str, float] = {}
        for did, score in doc_rrf.items():
            if rrf_range > 0:
                doc_norm_a[did] = (score - min_rrf) / rrf_range * (1.0 - floor) + floor
            else:
                # 单文档场景：min==max，用"该文档切片的平均原始分数"映射到 [floor, 1]
                # 这样 query 相关性差时（切片原始分接近 0）normA 接近 floor，
                # 避免完全无关的文档仍拿到接近 1 的 α 权重
                items = doc_chunks.get(did, [])
                if items:
                    avg_chunk_score = sum(
                        c.score for c, _ in items
                    ) / len(items)
                    # 切片 score 是 VDB 融合分，通常 [0, 1.5]，clip 到 [0, 1]
                    avg_chunk_score = max(0.0, min(1.0, avg_chunk_score))
                    doc_norm_a[did] = avg_chunk_score * (1.0 - floor) + floor
                else:
                    doc_norm_a[did] = (1.0 + floor) / 2.0

        # ── 4. 维度 B：B1+B2 两路 RRF ──
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

        # ── 5. 维度 C：文档属性（数据源：VDB kb_doc_metadata）──
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
            boost = (
                quality * self._QUALITY_WEIGHT
                + recency * self._RECENCY_WEIGHT
                + hit_score * self._HIT_WEIGHT
            )
            doc_norm_c[did] = min(boost / self._MAX_ATTR_BOOST, 1.0)

        # ── 6. 计算 finalScore ──
        for c in chunks:
            did = c.document_id or ""
            na = doc_norm_a.get(did, 0.0)
            nb = doc_norm_b.get(did, 0.0)
            nc = doc_norm_c.get(did, 0.0)
            c.score = round(
                self._ALPHA * na + self._BETA * nb + self._GAMMA * nc, 4,
            )

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
    # Self-Querying / Embedding
    # ══════════════════════════════════════════════════════

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
