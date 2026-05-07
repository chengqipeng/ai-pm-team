"""知识检索引擎 — Self-Querying + 混合检索 + RRF + Rerank + Parent-Child

对应 doc/知识库体系设计方案.md §五。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict
from typing import Any

from src.store.knowledge_dao import (
    KnowledgeBaseDAO, KnowledgeChunkDAO, KnowledgeDocumentDAO,
    KnowledgeSchemaDAO, KnowledgeSearchLogDAO,
)
from src.store.knowledge_models import KnowledgeChunkRow, KnowledgeSearchLogRow

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
    """知识检索引擎"""

    def __init__(
        self,
        vector_store: KnowledgeVectorStore,
        lkeap: TencentLKEAPClient | None = None,
        llm: Any = None,
        embedding_fn: Any = None,             # callable(text: str) -> list[float]
        rrf_k: int = 60,
        rerank_top_k: int = 10,
        expand_context_n: int = 1,
    ) -> None:
        self._vdb = vector_store
        self._lkeap = lkeap
        self._llm = llm
        self._embedding_fn = embedding_fn
        self._rrf_k = rrf_k
        self._rerank_top_k = rerank_top_k
        self._expand_n = expand_context_n

    # ── 对外入口 ──

    async def search(
        self,
        tenant_id: int,
        query: str,
        knowledge_base_id: int | None = None,
        filters: dict | None = None,
        top_k: int = 5,
        enable_rerank: bool = True,
        enable_self_query: bool = True,
        conversation_history: list | None = None,
        user_id: str = "",
        thread_id: str = "",
        trace_id: str = "",
    ) -> list[KnowledgeChunk]:
        """完整检索流水线"""
        t0 = time.time()
        timings: dict[str, int] = {}

        # Step 1: 查询改写（多轮对话）— 可选
        rewritten_query = query
        if conversation_history and self._lkeap:
            ts = time.time()
            try:
                rewritten_query = await self._rewrite_query(query, conversation_history)
            except Exception as exc:
                logger.warning("Query rewrite failed: %s", exc)
            timings["rewrite_ms"] = int((time.time() - ts) * 1000)

        # Step 2: Self-Querying — 从查询中提取过滤条件
        semantic_query = rewritten_query
        effective_filters = filters or {}
        if enable_self_query and self._llm and not filters:
            ts = time.time()
            try:
                sq = await self._self_query(
                    rewritten_query, tenant_id, knowledge_base_id,
                )
                semantic_query = sq.get("semantic_query", rewritten_query)
                effective_filters = sq.get("filters") or {}
            except Exception as exc:
                logger.warning("Self-query failed: %s", exc)
            timings["self_query_ms"] = int((time.time() - ts) * 1000)

        # Step 3: 向量 + BM25 混合检索（KnowledgeVectorStore 内部做 WeightedRerank）
        ts = time.time()
        filter_expr = self._build_filter_expr(knowledge_base_id, effective_filters)
        vector_results: list[dict] = []
        try:
            query_vec = await self._embed(semantic_query)
            vector_results = await asyncio.to_thread(
                self._vdb.search_chunks,
                tenant_id=str(tenant_id),
                vector=query_vec,
                query_text=semantic_query,       # 同时启用 BM25 稀疏检索
                extra_filter=filter_expr,
                top_k=max(top_k * 3, self._rerank_top_k),
            )
        except Exception as exc:
            logger.warning("Vector search failed: %s", exc)
        timings["vector_search_ms"] = int((time.time() - ts) * 1000)

        # 目前 BM25 已在 VDB 的 hybrid_search 中融合完成；
        # 如果后续接入独立的 FTS5/ES BM25 通路，可在此处调用并用 _rrf_fusion 合并。
        timings["bm25_search_ms"] = 0
        fused = vector_results

        # Step 4: Rerank（LKEAP Cross-Encoder）
        if enable_rerank and self._lkeap and len(fused) > top_k:
            ts = time.time()
            try:
                fused = await self._rerank(rewritten_query, fused, top_k)
            except Exception as exc:
                logger.warning("Rerank failed: %s", exc)
                fused = fused[:top_k]
            timings["rerank_ms"] = int((time.time() - ts) * 1000)
        else:
            fused = fused[:top_k]

        # Step 5: 回 PG 拉全文 + Parent-Child 扩展
        chunks = await self._hydrate_and_expand(fused)

        # 命中热度 +1（异步，不阻塞返回）
        if chunks:
            asyncio.create_task(self._record_hits(chunks))

        # 写检索审计日志（异步）
        total_ms = int((time.time() - t0) * 1000)
        asyncio.create_task(self._log_search(
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
            user_id=user_id,
            thread_id=thread_id,
            trace_id=trace_id,
            raw_query=query,
            rewritten_query=rewritten_query,
            semantic_query=semantic_query,
            filters=effective_filters,
            chunks=chunks,
            vector_hit=len(vector_results),
            bm25_hit=0,
            timings=timings,
            total_ms=total_ms,
        ))

        return chunks

    # ── 子步骤 ──

    async def _rewrite_query(
        self, query: str, history: list,
    ) -> str:
        """调 LKEAP QueryRewrite API 做指代消解 / 省略补全"""
        # TODO: 腾讯云 LKEAP 的 QueryRewrite 接口在 TencentLKEAPClient 未实现；
        # 此处预留扩展点，暂时返回原查询。未来可扩展 lkeap_client。
        return query

    async def _self_query(
        self, query: str, tenant_id: int, kb_id: int | None,
    ) -> dict:
        """用 LLM 解析 metadata 过滤条件"""
        # 获取 Schema 字段定义
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
        # 调用注入的 LLM（兼容 langchain 接口 ainvoke → AIMessage）
        try:
            resp = await self._llm.ainvoke(prompt)
            text = getattr(resp, "content", None) or str(resp)
        except Exception as exc:
            logger.warning("Self-query LLM call failed: %s", exc)
            return {"semantic_query": query, "filters": {}}

        # 用 ingestion 里同一套鲁棒 JSON 抽取器
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
        """调用 embedding 函数"""
        if self._embedding_fn is None:
            # 默认用 LKEAP 的 Embedding API
            if self._lkeap is None:
                raise RuntimeError("embedding_fn and lkeap both None — cannot embed")
            vecs = await asyncio.to_thread(self._lkeap.get_embedding, [text])
            return vecs[0] if vecs else []
        # 用户注入的 embedding 函数
        if asyncio.iscoroutinefunction(self._embedding_fn):
            return await self._embedding_fn(text)
        return await asyncio.to_thread(self._embedding_fn, text)

    def _build_filter_expr(
        self, knowledge_base_id: int | None, filters: dict,
    ) -> str:
        """构造 tcvectordb 过滤表达式"""
        parts: list[str] = []

        if knowledge_base_id:
            parts.append(f'knowledge_base_id = "{knowledge_base_id}"')
        parts.append('status = "active"')

        # 已知可过滤字段白名单 — 防止注入任意字段
        allowed_fields = {
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
            col = allowed_fields.get(key)
            if not col or val is None or val == "":
                continue
            if isinstance(val, (list, tuple)):
                if not val:
                    continue
                ors = " OR ".join(f'{col} = "{self._escape(v)}"' for v in val)
                parts.append(f'({ors})')
            else:
                parts.append(f'{col} = "{self._escape(val)}"')

        return " AND ".join(parts)

    @staticmethod
    def _escape(val) -> str:
        """转义过滤值中的双引号"""
        return str(val).replace('"', '\\"')

    async def _rerank(
        self, query: str, candidates: list[dict], top_k: int,
    ) -> list[dict]:
        """LKEAP Rerank 精排"""
        if not candidates:
            return []
        # 构造 docs：优先使用 abstract 字段（VDB 冗余），降级到 content_preview
        docs: list[str] = []
        for c in candidates:
            text = c.get("abstract") or c.get("content_preview") or c.get("section_title") or ""
            docs.append(text[:2000] if text else "")

        results = await asyncio.to_thread(
            self._lkeap.rerank, query, docs, top_k,
        )
        reranked = []
        for r in results:
            if 0 <= r.index < len(candidates):
                c = candidates[r.index]
                c["score"] = float(r.score)
                reranked.append(c)
        return reranked

    async def _hydrate_and_expand(
        self, vdb_results: list[dict],
    ) -> list[KnowledgeChunk]:
        """从 VDB 结果回 PG 拉全文 + Parent-Child 扩展"""
        if not vdb_results:
            return []

        chunk_ids = [r["id"] for r in vdb_results if r.get("id")]
        if not chunk_ids:
            return []

        # 批量拉 chunk
        chunk_rows = await asyncio.to_thread(
            KnowledgeChunkDAO.get_by_chunk_ids, chunk_ids,
        )
        rows_by_id = {c.chunk_id: c for c in chunk_rows}

        # 批量拉 doc 标题（去重后查）
        doc_ids = list({c.doc_id for c in chunk_rows if c.doc_id})
        doc_titles: dict[str, str] = {}
        for did in doc_ids:
            doc = await asyncio.to_thread(KnowledgeDocumentDAO.get_by_doc_id, did)
            if doc:
                doc_titles[did] = doc.title or doc.file_name

        # 按 VDB 返回顺序组装，保留分数
        result: list[KnowledgeChunk] = []
        for r in vdb_results:
            cid = r.get("id", "")
            row = rows_by_id.get(cid)
            if row is None:
                continue
            score = float(r.get("score", 0.0))
            chunk = KnowledgeChunk(
                content=row.content,
                score=score,
                metadata=self._row_metadata(row),
                document_id=row.doc_id,
                document_title=doc_titles.get(row.doc_id, ""),
                chunk_id=row.chunk_id,
                chunk_index=row.chunk_index,
                section_title=row.section_title,
                section_path=row.section_path,
                chunk_type=row.chunk_type,
            )
            # Parent-Child 扩展：取前后 expand_n 个切片
            if self._expand_n > 0:
                chunk.expanded_context = await self._expand_context(
                    row, expand_n=self._expand_n,
                )
            result.append(chunk)

        return result

    async def _expand_context(
        self, row: KnowledgeChunkRow, expand_n: int,
    ) -> str:
        """拉取前后 N 个切片拼接作为扩展上下文"""
        if expand_n <= 0 or not row.doc_id:
            return ""
        start = max(0, row.chunk_index - expand_n)
        end = row.chunk_index + expand_n
        neighbors = await asyncio.to_thread(
            KnowledgeChunkDAO.list_by_doc, row.doc_id, start, end,
        )
        parts = [n.content for n in neighbors if n.chunk_id != row.chunk_id]
        return "\n\n".join(parts)

    @staticmethod
    def _row_metadata(row: KnowledgeChunkRow) -> dict:
        """从 chunk 行抽取元数据字段"""
        return {
            "doc_id": row.doc_id,
            "chunk_id": row.chunk_id,
            "chunk_type": row.chunk_type,
            "section_title": row.section_title,
            "section_path": row.section_path,
            "docCategory": row.doc_category,
            "industryVertical": row.industry,
            "businessStage": row.business_stage,
            "targetAudience": row.target_audience,
            "productService": row.product_service,
            "datePublished": row.date_published,
        }

    # ── 异步后处理 ──

    async def _record_hits(self, chunks: list[KnowledgeChunk]) -> None:
        try:
            chunk_ids = [c.chunk_id for c in chunks if c.chunk_id]
            if chunk_ids:
                await asyncio.to_thread(KnowledgeChunkDAO.increment_hit, chunk_ids)
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
