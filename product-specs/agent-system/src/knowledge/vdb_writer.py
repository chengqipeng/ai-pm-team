"""知识库向量库封装 — 单库共享 + tenant_id 字段隔离

对应 doc/知识库体系设计方案.md §4.补.4。
复用 VikingFS._VectorDB 的 HNSW + BM25 SparseIndex 模式。

安全约束：所有查询/删除/更新必须携带 tenant_id，由本类强制注入到 filter。
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 集合索引定义（与 DDL 保持一致）
# ═══════════════════════════════════════════════════════════

def _build_chunk_index(dimension: int):
    """kb_chunks 集合索引 — HNSW + BM25 + 多个 FilterIndex"""
    from tcvectordb.model.index import (
        Index, VectorIndex, FilterIndex, HNSWParams, SparseIndex,
    )
    from tcvectordb.model.enum import FieldType, IndexType, MetricType

    return Index(
        FilterIndex(name="id", field_type=FieldType.String, index_type=IndexType.PRIMARY_KEY),
        VectorIndex(
            name="vector",
            dimension=dimension,
            index_type=IndexType.HNSW,
            metric_type=MetricType.COSINE,
            params=HNSWParams(m=16, efconstruction=200),
        ),
        SparseIndex(name="sparse_vector"),
        # 租户隔离字段（🔑 所有查询必须携带）
        FilterIndex(name="tenant_id",         field_type=FieldType.String, index_type=IndexType.FILTER),
        # 业务过滤字段
        FilterIndex(name="knowledge_base_id", field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="dataset_id",        field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="doc_id",            field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="chunk_type",        field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="doc_category",      field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="industry",          field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="business_stage",    field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="target_audience",   field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="product_service",   field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="status",            field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="date_published",    field_type=FieldType.Uint64, index_type=IndexType.FILTER),
    )


def _build_summary_index(dimension: int):
    """kb_doc_summary 集合索引 — 只做向量检索，字段更精简"""
    from tcvectordb.model.index import (
        Index, VectorIndex, FilterIndex, HNSWParams,
    )
    from tcvectordb.model.enum import FieldType, IndexType, MetricType

    return Index(
        FilterIndex(name="id", field_type=FieldType.String, index_type=IndexType.PRIMARY_KEY),
        VectorIndex(
            name="vector",
            dimension=dimension,
            index_type=IndexType.HNSW,
            metric_type=MetricType.COSINE,
            params=HNSWParams(m=16, efconstruction=200),
        ),
        FilterIndex(name="tenant_id",         field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="knowledge_base_id", field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="doc_id",            field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="doc_category",      field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="industry",          field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="status",            field_type=FieldType.String, index_type=IndexType.FILTER),
    )


# ═══════════════════════════════════════════════════════════
# KnowledgeVectorStore
# ═══════════════════════════════════════════════════════════

class KnowledgeVectorStore:
    """知识库向量库封装 — 单 Database 多租户共享，tenant_id FilterIndex 强制隔离

    用法：
        vdb = KnowledgeVectorStore(url="...", key="...", dimension=1024)
        vdb.upsert_chunks([{
            "id": "chunk_xxx",
            "vector": [...],
            "tenant_id": "1001",
            "knowledge_base_id": "2001",
            "doc_id": "doc_yyy",
            ...
        }])
        results = vdb.search_chunks(
            tenant_id="1001",
            vector=[...],
            query_text="审批流程",
            extra_filter='doc_category = "产品手册"',
            top_k=10,
        )
    """

    def __init__(
        self,
        url: str,
        key: str,
        username: str = "root",
        database_name: str = "knowledge",
        chunk_collection: str = "kb_chunks",
        summary_collection: str = "kb_doc_summary",
        dimension: int = 1024,
        timeout: int = 30,
    ) -> None:
        self._url = url
        self._key = key
        self._username = username
        self._timeout = timeout
        self._db_name = database_name
        self._chunk_coll_name = chunk_collection
        self._summary_coll_name = summary_collection
        self._dim = dimension
        self._client = None
        self._db = None
        self._chunk_coll = None
        self._summary_coll = None
        self._bm25 = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        import tcvectordb
        self._client = tcvectordb.VectorDBClient(
            url=self._url, username=self._username, key=self._key, timeout=self._timeout,
        )
        return self._client

    # ── 初始化 ──

    def _ensure_collections(self):
        if self._chunk_coll is not None and self._summary_coll is not None:
            return

        client = self._ensure_client()
        try:
            self._db = client.create_database(self._db_name)
        except Exception:
            self._db = client.database(self._db_name)

        # 切片集合
        try:
            self._chunk_coll = self._db.describe_collection(self._chunk_coll_name)
        except Exception:
            try:
                self._chunk_coll = self._db.create_collection(
                    name=self._chunk_coll_name, shard=3, replicas=1,
                    description="Knowledge base chunks (HNSW + BM25, multi-tenant)",
                    index=_build_chunk_index(self._dim),
                )
                logger.info("Created collection: %s/%s", self._db_name, self._chunk_coll_name)
            except Exception as exc:
                logger.warning("Create chunk collection failed (%s), getting existing", exc)
                self._chunk_coll = self._db.collection(self._chunk_coll_name)

        # 文档摘要集合
        try:
            self._summary_coll = self._db.describe_collection(self._summary_coll_name)
        except Exception:
            try:
                self._summary_coll = self._db.create_collection(
                    name=self._summary_coll_name, shard=1, replicas=1,
                    description="Knowledge base document-level summaries (multi-tenant)",
                    index=_build_summary_index(self._dim),
                )
                logger.info("Created collection: %s/%s", self._db_name, self._summary_coll_name)
            except Exception as exc:
                logger.warning("Create summary collection failed (%s), getting existing", exc)
                self._summary_coll = self._db.collection(self._summary_coll_name)

    def _get_bm25(self):
        """延迟初始化 BM25 编码器"""
        if self._bm25 is None:
            try:
                from tcvdb_text.encoder import BM25Encoder
                self._bm25 = BM25Encoder.default()
            except Exception as exc:
                logger.warning("BM25Encoder init failed: %s", exc)
        return self._bm25

    # ── 写入（强制 tenant_id 校验） ──

    def upsert_chunks(self, records: list[dict]) -> int:
        """批量写入切片向量。

        records 中每条必须包含 id / vector / tenant_id / knowledge_base_id / doc_id。
        若 SparseIndex 可用，自动为 abstract 字段生成 sparse_vector。
        """
        if not records:
            return 0
        for r in records:
            if not r.get("tenant_id"):
                raise ValueError("tenant_id is required for every chunk record")
            if not r.get("id") or not r.get("vector"):
                raise ValueError("id and vector are required")

        self._ensure_collections()

        # 为每条记录生成 BM25 稀疏向量
        bm25 = self._get_bm25()
        if bm25:
            for rec in records:
                text = rec.get("abstract") or rec.get("content_preview") or ""
                if text and "sparse_vector" not in rec:
                    try:
                        sparse = bm25.encode_texts([text])
                        if sparse and sparse[0]:
                            rec["sparse_vector"] = sparse[0]
                    except Exception:
                        pass

        # 尝试写入；若 sparse_vector 不被支持则去掉重试
        try:
            self._chunk_coll.upsert(records)
        except Exception as exc:
            if "sparse_vector" in str(exc) or "fieldName" in str(exc):
                for rec in records:
                    rec.pop("sparse_vector", None)
                self._chunk_coll.upsert(records)
            else:
                raise
        logger.debug("Upserted %d chunks to VDB", len(records))
        return len(records)

    def upsert_summaries(self, records: list[dict]) -> int:
        """批量写入文档级摘要向量"""
        if not records:
            return 0
        for r in records:
            if not r.get("tenant_id"):
                raise ValueError("tenant_id is required for every summary record")
            if not r.get("id") or not r.get("vector"):
                raise ValueError("id and vector are required")

        self._ensure_collections()
        self._summary_coll.upsert(records)
        logger.debug("Upserted %d summaries to VDB", len(records))
        return len(records)

    # ── 检索（tenant_id 强制注入） ──

    def search_chunks(
        self,
        tenant_id: str,
        vector: list[float],
        query_text: str = "",
        extra_filter: str = "",
        top_k: int = 20,
        dense_weight: float = 0.3,
        sparse_weight: float = 0.7,
    ) -> list[dict]:
        """切片混合检索：dense + sparse → WeightedRerank → tenant_id + 业务 filter

        Args:
            tenant_id: 租户 ID（必填，强制隔离）
            vector: 查询向量
            query_text: 查询文本（用于 BM25 稀疏向量）；为空时降级为纯向量检索
            extra_filter: 业务过滤条件（如 'doc_category = "成功案例"'）
            top_k: 返回数量
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self._ensure_collections()
        tenant_filter = self._tenant_filter(tenant_id)
        filter_expr = f'{tenant_filter} AND ({extra_filter})' if extra_filter else tenant_filter

        # 有 BM25 且有查询文本 → 混合检索
        bm25 = self._get_bm25() if query_text else None
        if bm25:
            try:
                return self._hybrid_search(
                    vector, query_text, filter_expr, top_k,
                    dense_weight, sparse_weight,
                )
            except Exception as exc:
                logger.warning("Hybrid search failed: %s, fallback to vector", exc)

        return self._vector_search(vector, filter_expr, top_k)

    def search_summaries(
        self,
        tenant_id: str,
        vector: list[float],
        extra_filter: str = "",
        top_k: int = 10,
    ) -> list[dict]:
        """文档摘要检索 — 纯向量检索（宏观问题用）"""
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self._ensure_collections()
        tenant_filter = self._tenant_filter(tenant_id)
        filter_expr = f'{tenant_filter} AND ({extra_filter})' if extra_filter else tenant_filter

        from tcvectordb.model.document import Filter
        results = self._summary_coll.search(
            vectors=[vector], limit=top_k, filter=Filter(filter_expr),
        )
        return self._parse_results(results)

    def _vector_search(
        self, vector: list[float], filter_expr: str, top_k: int,
    ) -> list[dict]:
        from tcvectordb.model.document import Filter
        results = self._chunk_coll.search(
            vectors=[vector], limit=top_k, filter=Filter(filter_expr),
        )
        return self._parse_results(results)

    def _hybrid_search(
        self,
        vector: list[float],
        query_text: str,
        filter_expr: str,
        top_k: int,
        dense_weight: float,
        sparse_weight: float,
    ) -> list[dict]:
        from tcvectordb.model.document import (
            AnnSearch, KeywordSearch, WeightedRerank, Filter,
        )

        sparse_vec = self._bm25.encode_queries([query_text])
        if not sparse_vec or not sparse_vec[0]:
            return self._vector_search(vector, filter_expr, top_k)

        ann = AnnSearch(field_name="vector", data=vector)
        kw = KeywordSearch(field_name="sparse_vector", data=sparse_vec[0])
        rerank = WeightedRerank(
            field_list=["vector", "sparse_vector"],
            weight=[dense_weight, sparse_weight],
        )
        results = self._chunk_coll.hybrid_search(
            ann=[ann], match=[kw], rerank=rerank,
            limit=top_k, filter=Filter(filter_expr),
        )
        return self._parse_results(results)

    # ── 删除（tenant_id 双重校验） ──

    def delete_by_doc(self, tenant_id: str, doc_id: str) -> None:
        """删除文档对应的所有切片和摘要向量"""
        if not tenant_id or not doc_id:
            raise ValueError("tenant_id and doc_id are required")

        self._ensure_collections()
        from tcvectordb.model.document import Filter
        filter_expr = f'tenant_id = "{tenant_id}" AND doc_id = "{doc_id}"'
        try:
            self._chunk_coll.delete(filter=Filter(filter_expr))
            self._summary_coll.delete(filter=Filter(filter_expr))
            logger.info("Deleted VDB entries for tenant=%s doc=%s", tenant_id, doc_id)
        except Exception as exc:
            logger.warning("Delete failed for doc %s: %s", doc_id, exc)

    def delete_by_knowledge_base(self, tenant_id: str, knowledge_base_id: str) -> None:
        """清空某个知识库的所有向量"""
        if not tenant_id or not knowledge_base_id:
            raise ValueError("tenant_id and knowledge_base_id are required")

        self._ensure_collections()
        from tcvectordb.model.document import Filter
        filter_expr = (
            f'tenant_id = "{tenant_id}" AND knowledge_base_id = "{knowledge_base_id}"'
        )
        try:
            self._chunk_coll.delete(filter=Filter(filter_expr))
            self._summary_coll.delete(filter=Filter(filter_expr))
            logger.info(
                "Cleared VDB for tenant=%s kb=%s", tenant_id, knowledge_base_id,
            )
        except Exception as exc:
            logger.warning("Clear VDB failed for kb %s: %s", knowledge_base_id, exc)

    def delete_by_chunk_ids(self, tenant_id: str, chunk_ids: list[str]) -> None:
        """按 chunk_id 精确删除（tenant_id 作为二次校验）"""
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if not chunk_ids:
            return
        self._ensure_collections()
        from tcvectordb.model.document import Filter
        ids_expr = ", ".join(f'"{cid}"' for cid in chunk_ids)
        filter_expr = f'tenant_id = "{tenant_id}" AND id IN ({ids_expr})'
        try:
            self._chunk_coll.delete(filter=Filter(filter_expr))
        except Exception as exc:
            logger.warning("Delete chunks failed: %s", exc)

    # ── 工具方法 ──

    @staticmethod
    def _tenant_filter(tenant_id: str) -> str:
        # 防 filter 注入：tenant_id 必须是数字字符串
        tid = str(tenant_id).strip()
        if not tid.isdigit() and not all(c.isalnum() or c in "-_" for c in tid):
            raise ValueError(f"invalid tenant_id: {tenant_id!r}")
        return f'tenant_id = "{tid}"'

    @staticmethod
    def _parse_results(results) -> list[dict]:
        """解析 tcvectordb 的嵌套结果结构为扁平 list[dict]"""
        parsed = []
        if not results:
            return parsed
        for doc_list in results:
            for doc in doc_list:
                if isinstance(doc, dict):
                    parsed.append(doc)
                else:
                    d = {"id": getattr(doc, "id", ""), "score": getattr(doc, "score", 0.0)}
                    if hasattr(doc, "fields") and doc.fields:
                        d.update(doc.fields)
                    parsed.append(d)
        return parsed
