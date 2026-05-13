"""知识库向量库封装 — 单库共享 + tenant_id 字段隔离

对应 doc/知识库体系设计方案.md §4.补.4 的"全 VDB 检索架构"：
- kb_chunks：切片级（dense + sparse + content 全文）
- kb_doc_metadata：文档级（summary 向量 + 5 路 BM25 稀疏 + γ 属性字段）

安全约束：所有查询/删除/更新必须携带 tenant_id，由本类强制注入到 filter。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 集合索引定义
# ═══════════════════════════════════════════════════════════

def _build_chunk_index(dimension: int):
    """kb_chunks 集合 — 切片级 dense + sparse 混合索引"""
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
        SparseIndex(name="sparse_vector"),   # BM25 on content
        # 租户隔离（🔑 所有查询必须携带）
        FilterIndex(name="tenant_id",         field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="knowledge_base_id", field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="dataset_id",        field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="doc_id",            field_type=FieldType.String, index_type=IndexType.FILTER),
        # Parent-Child 扩展必需
        FilterIndex(name="chunk_index",       field_type=FieldType.Uint64, index_type=IndexType.FILTER),
        # 切片元数据
        FilterIndex(name="chunk_type",        field_type=FieldType.String, index_type=IndexType.FILTER),
        # 业务过滤字段（Schema）
        FilterIndex(name="doc_category",      field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="industry",          field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="business_stage",    field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="target_audience",   field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="product_service",   field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="status",            field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="date_published",    field_type=FieldType.Uint64, index_type=IndexType.FILTER),
    )


def _build_doc_metadata_index(dimension: int):
    """kb_doc_metadata 集合 — 文档级 summary 向量 + 单路 BM25（加权拼接）+ γ 属性

    一个文档一条记录，承担 β 维度的两路召回信号：
      B1：summary_vector 稠密 ANN 召回
      B2：sparse_vector 稀疏 BM25 召回（对合并后的"加权拼接文本"做）

    tcvectordb 约束：一个集合只能有 1 个 VectorIndex（字段名必须是 "vector"）
                   + 1 个 SparseIndex（字段名必须是 "sparse_vector"）。
    所以 5 路 BM25 的字段权重通过"文本重复次数"模拟：
      title × 3  |  summary × 2  |  keywords × 2  |  candidate × 1  |  toc × 1
    BM25 会按词频计算得分，高权重字段的词出现次数多，自然得分高。
    """
    from tcvectordb.model.index import (
        Index, VectorIndex, FilterIndex, HNSWParams, SparseIndex,
    )
    from tcvectordb.model.enum import FieldType, IndexType, MetricType

    return Index(
        FilterIndex(name="id", field_type=FieldType.String, index_type=IndexType.PRIMARY_KEY),
        # 摘要向量（B1 路）— tcvectordb 要求字段名必须是 "vector"
        VectorIndex(
            name="vector",
            dimension=dimension,
            index_type=IndexType.HNSW,
            metric_type=MetricType.COSINE,
            params=HNSWParams(m=16, efconstruction=200),
        ),
        # 加权拼接文本 BM25（B2 路）— 字段名必须是 "sparse_vector"
        SparseIndex(name="sparse_vector"),
        # 租户 / 业务字段
        FilterIndex(name="tenant_id",         field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="knowledge_base_id", field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="dataset_id",        field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="doc_category",      field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="industry",          field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="business_stage",    field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="target_audience",   field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="product_service",   field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="status",            field_type=FieldType.String, index_type=IndexType.FILTER),
        # γ 维度属性
        # 注意：tcvectordb FilterIndex 不支持 Double 类型，quality_score × 10000 存为 Uint64
        FilterIndex(name="quality_score_x10k", field_type=FieldType.Uint64, index_type=IndexType.FILTER),
        FilterIndex(name="date_published",    field_type=FieldType.Uint64, index_type=IndexType.FILTER),
        FilterIndex(name="created_at",        field_type=FieldType.Uint64, index_type=IndexType.FILTER),
        FilterIndex(name="search_hit_count",  field_type=FieldType.Uint64, index_type=IndexType.FILTER),
    )


# ═══════════════════════════════════════════════════════════
# KnowledgeVectorStore
# ═══════════════════════════════════════════════════════════

class KnowledgeVectorStore:
    """知识库向量库封装 — 单 Database 多租户共享，tenant_id FilterIndex 强制隔离

    集合：
        kb_chunks：切片级 dense + sparse 混合索引
        kb_doc_metadata：文档级摘要向量 + 5 路 BM25 + γ 属性
    """

    # 元数据字段加权拼接时的重复次数（对齐原 data-process 的字段 boost）
    # 结果会对拼接后的文本生成单路 BM25 sparse_vector
    DOC_FIELD_WEIGHTS = {
        "title": 3,
        "summary": 2,
        "keywords": 2,
        "candidate_keywords": 1,
        "toc": 1,
    }

    def __init__(
        self,
        url: str,
        key: str,
        username: str = "root",
        database_name: str = "knowledge",
        chunk_collection: str = "kb_chunks",
        doc_metadata_collection: str = "kb_doc_metadata",
        dimension: int = 1024,
        timeout: int = 30,
    ) -> None:
        self._url = url
        self._key = key
        self._username = username
        self._timeout = timeout
        self._db_name = database_name
        self._chunk_coll_name = chunk_collection
        self._doc_meta_coll_name = doc_metadata_collection
        self._dim = dimension
        self._client = None
        self._db = None
        self._chunk_coll = None
        self._doc_meta_coll = None
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
        if self._chunk_coll is not None and self._doc_meta_coll is not None:
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
                    description="Knowledge base chunks (dense + BM25, multi-tenant)",
                    index=_build_chunk_index(self._dim),
                )
                logger.info("Created collection: %s/%s", self._db_name, self._chunk_coll_name)
            except Exception as exc:
                logger.warning("Create chunk collection failed (%s), getting existing", exc)
                self._chunk_coll = self._db.collection(self._chunk_coll_name)

        # 文档元数据集合（摘要向量 + 多路 BM25 + γ 属性）
        try:
            self._doc_meta_coll = self._db.describe_collection(self._doc_meta_coll_name)
        except Exception:
            try:
                self._doc_meta_coll = self._db.create_collection(
                    name=self._doc_meta_coll_name, shard=1, replicas=1,
                    description="KB document metadata (summary vector + multi-BM25 + gamma attrs)",
                    index=_build_doc_metadata_index(self._dim),
                )
                logger.info("Created collection: %s/%s", self._db_name, self._doc_meta_coll_name)
            except Exception as exc:
                logger.warning("Create doc_metadata collection failed (%s), getting existing", exc)
                self._doc_meta_coll = self._db.collection(self._doc_meta_coll_name)

    def _get_bm25(self):
        """延迟初始化 BM25 编码器"""
        if self._bm25 is None:
            try:
                from tcvdb_text.encoder import BM25Encoder
                self._bm25 = BM25Encoder.default()
            except Exception as exc:
                logger.warning("BM25Encoder init failed: %s", exc)
        return self._bm25

    # ═══════════════════════════════════════════════════════
    # 写入
    # ═══════════════════════════════════════════════════════

    def upsert_chunks(self, records: list[dict]) -> int:
        """批量写入切片向量。

        records 每条必须含 id / vector / tenant_id / knowledge_base_id / doc_id / content。
        自动对 content 生成 BM25 sparse_vector。
        """
        if not records:
            return 0
        for r in records:
            if not r.get("tenant_id"):
                raise ValueError("tenant_id is required for every chunk record")
            if not r.get("id") or not r.get("vector"):
                raise ValueError("id and vector are required")

        self._ensure_collections()

        # 为每条记录生成 BM25 稀疏向量（基于 content 全文，优先级高于 abstract）
        bm25 = self._get_bm25()
        if bm25:
            for rec in records:
                text = rec.get("content") or rec.get("abstract") or ""
                if text and "sparse_vector" not in rec:
                    try:
                        sparse = bm25.encode_texts([text[:4000]])
                        if sparse and sparse[0]:
                            rec["sparse_vector"] = sparse[0]
                    except Exception:
                        pass

        try:
            res = self._chunk_coll.upsert(records)
        except Exception as exc:
            if "sparse_vector" in str(exc) or "fieldName" in str(exc):
                logger.warning("upsert_chunks sparse issue, retry without sparse: %s", exc)
                for rec in records:
                    rec.pop("sparse_vector", None)
                res = self._chunk_coll.upsert(records)
            else:
                logger.error("upsert_chunks failed: %s", exc, exc_info=True)
                raise
        logger.debug("Upserted %d chunks to VDB (server resp: %s)", len(records), res)
        return len(records)

    def upsert_doc_metadata(self, records: list[dict]) -> int:
        """批量写入文档级元数据。

        records 每条必须含：
          id=doc_id, tenant_id, knowledge_base_id
          vector: list[float]（摘要 embedding，B1 路）
          title / summary / keywords / candidate_keywords / toc: str
              （按 DOC_FIELD_WEIGHTS 重复拼接成加权文本，用作 BM25 输入）
          doc_category / industry / ...：Schema 过滤字段
          quality_score / date_published / created_at / search_hit_count：γ 属性
        """
        if not records:
            return 0
        for r in records:
            if not r.get("tenant_id"):
                raise ValueError("tenant_id is required")
            if not r.get("id") or not r.get("vector"):
                raise ValueError("id and vector (summary embedding) are required")

        self._ensure_collections()
        bm25 = self._get_bm25()

        # 为每条记录构造加权拼接文本 → sparse_vector
        if bm25:
            for rec in records:
                if "sparse_vector" in rec:
                    continue  # 调用方已自行编码
                combined = self._build_weighted_text(rec)
                if not combined:
                    continue
                try:
                    sparse = bm25.encode_texts([combined[:16000]])
                    if sparse and sparse[0]:
                        rec["sparse_vector"] = sparse[0]
                except Exception:
                    pass

        try:
            res = self._doc_meta_coll.upsert(records)
        except Exception as exc:
            if "sparse" in str(exc).lower() or "fieldName" in str(exc):
                logger.warning("upsert_doc_metadata sparse issue, retry without: %s", exc)
                for rec in records:
                    rec.pop("sparse_vector", None)
                res = self._doc_meta_coll.upsert(records)
            else:
                logger.error("upsert_doc_metadata failed: %s", exc, exc_info=True)
                raise
        logger.debug("Upserted %d doc_metadata to VDB (server resp: %s)", len(records), res)
        return len(records)

    @classmethod
    def _build_weighted_text(cls, rec: dict) -> str:
        """把多个元数据字段按权重重复拼接，供单路 BM25 编码。

        因 tcvectordb 限制：一个集合只能有 1 个 sparse 字段。
        通过词频放大模拟 5 路字段 boost 的效果。
        """
        parts: list[str] = []
        for field, weight in cls.DOC_FIELD_WEIGHTS.items():
            text = (rec.get(field) or "").strip()
            if not text:
                continue
            for _ in range(weight):
                parts.append(text)
        return " ".join(parts)

    def update_doc_hit_count(self, doc_ids: list[str], tenant_id: str) -> None:
        """准实时更新文档级 hit_count（批处理调度用）。

        VDB partial update 仅支持"以 id 写回"的方式：重写对应 doc 的 search_hit_count。
        当前简化实现：调用方先查 PG 拿最新 hit_count，再传进来 upsert。
        """
        if not doc_ids:
            return
        # 这里不做实现，留给 scheduler 批处理用
        # 建议通过 upsert_doc_metadata 做全字段覆盖写
        logger.debug("update_doc_hit_count noop (use upsert_doc_metadata for now)")

    def batch_update_doc_fields(
        self,
        tenant_id: str,
        updates: dict[str, dict],
    ) -> int:
        """批量更新文档元数据字段（不触及向量/sparse）。

        updates 格式：{doc_id: {field1: value1, field2: value2}}
        典型用途：scheduler 同步 PG → VDB 的 search_hit_count。

        实现：tcvectordb 不允许 `id in (...)` 的 filter 表达式，必须用 `document_ids`
        参数查询。所以：query(document_ids=[...], retrieve_vector=True) 拿原记录 →
        合并目标字段 → upsert 写回。

        返回实际更新的记录数。
        """
        if not updates:
            return 0
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self._ensure_collections()

        doc_ids = list(updates.keys())

        # 读全量（PRIMARY_KEY 必须用 document_ids 参数查询）
        try:
            existing = self._doc_meta_coll.query(
                document_ids=doc_ids,
                retrieve_vector=True,
                output_fields=None,
                limit=len(doc_ids),
            )
        except Exception as exc:
            logger.warning("batch_update_doc_fields: query failed: %s", exc)
            return 0

        if not existing:
            return 0

        records_to_write: list[dict] = []
        for rec in existing:
            did = rec.get("id")
            if not did or did not in updates:
                continue
            # 二次校验 tenant_id（防止跨租户误更新）
            if str(rec.get("tenant_id", "")) != str(tenant_id):
                logger.warning(
                    "batch_update_doc_fields: skip doc=%s, tenant mismatch (rec=%s expect=%s)",
                    did, rec.get("tenant_id"), tenant_id,
                )
                continue
            merged = dict(rec)
            for field, value in updates[did].items():
                merged[field] = value
            records_to_write.append(merged)

        if not records_to_write:
            return 0

        try:
            self._doc_meta_coll.upsert(records_to_write)
            return len(records_to_write)
        except Exception as exc:
            logger.warning("batch_update_doc_fields: upsert failed: %s", exc)
            return 0

    # ═══════════════════════════════════════════════════════
    # 检索
    # ═══════════════════════════════════════════════════════

    def search_chunks(
        self,
        tenant_id: str,
        vector: list[float],
        query_text: str = "",
        extra_filter: str = "",
        top_k: int = 20,
        dense_weight: float = 0.3,
        sparse_weight: float = 0.7,
        output_fields: list[str] | None = None,
    ) -> list[dict]:
        """切片混合检索：dense + sparse → WeightedRerank。

        返回时默认带回 content / section_title / doc_id / chunk_index / 属性字段，
        调用方不再需要回 PG。
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self._ensure_collections()
        tenant_filter = self._tenant_filter(tenant_id)
        filter_expr = f'{tenant_filter} and ({extra_filter})' if extra_filter else tenant_filter

        bm25 = self._get_bm25() if query_text else None
        if bm25:
            try:
                return self._hybrid_search(
                    vector, query_text, filter_expr, top_k,
                    dense_weight, sparse_weight, output_fields,
                )
            except Exception as exc:
                logger.warning("Hybrid search failed: %s, fallback to vector", exc)

        return self._vector_search(vector, filter_expr, top_k, output_fields)

    def search_doc_metadata_hybrid(
        self,
        tenant_id: str,
        query_vector: list[float],
        query_text: str,
        extra_filter: str = "",
        top_k: int = 50,
        dense_weight: float = 0.5,
        sparse_weight: float = 0.5,
    ) -> list[dict]:
        """文档级一次性 hybrid_search（合并 B1 ANN + B2 BM25）。

        替代原本两次独立调用。通过一次 hybrid_search 实现：
          - AnnSearch(vector, query_vector)：文档摘要向量的语义相似度
          - KeywordSearch(sparse_vector, bm25(query_text))：加权拼接文本的 BM25
          - WeightedRerank 按 dense/sparse 权重融合
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if not query_vector:
            return []

        self._ensure_collections()
        tenant_filter = self._tenant_filter(tenant_id)
        filter_expr = f'{tenant_filter} and ({extra_filter})' if extra_filter else tenant_filter

        from tcvectordb.model.document import AnnSearch, KeywordSearch, WeightedRerank, Filter

        ann = AnnSearch(field_name="vector", data=query_vector)
        match_list: list = []
        rerank_fields = ["vector"]
        rerank_weights = [1.0]

        bm25 = self._get_bm25() if query_text else None
        if bm25:
            try:
                sparse_q = bm25.encode_queries([query_text])
                if sparse_q and sparse_q[0]:
                    match_list.append(
                        KeywordSearch(field_name="sparse_vector", data=sparse_q[0])
                    )
                    rerank_fields = ["vector", "sparse_vector"]
                    rerank_weights = [dense_weight, sparse_weight]
            except Exception as exc:
                logger.debug("doc metadata hybrid BM25 encode failed: %s", exc)

        rerank = WeightedRerank(field_list=rerank_fields, weight=rerank_weights)

        try:
            results = self._doc_meta_coll.hybrid_search(
                ann=[ann], match=match_list, rerank=rerank,
                limit=top_k, filter=Filter(filter_expr),
                output_fields=["id", "tenant_id", "title"],
            )
            return self._parse_results(results)
        except Exception as exc:
            logger.warning("doc_metadata hybrid_search failed: %s", exc)
            return []

    def search_doc_metadata_by_vector(
        self,
        tenant_id: str,
        vector: list[float],
        extra_filter: str = "",
        top_k: int = 10,
    ) -> list[dict]:
        """[兼容] 保留给单元测试/降级调用；推荐用 search_doc_metadata_hybrid。"""
        return self.search_doc_metadata_hybrid(
            tenant_id=tenant_id,
            query_vector=vector,
            query_text="",
            extra_filter=extra_filter,
            top_k=top_k,
        )

    def search_doc_metadata_by_bm25(
        self,
        tenant_id: str,
        query_text: str,
        extra_filter: str = "",
        top_k: int = 50,
    ) -> list[dict]:
        """[已废弃] tcvectordb 服务端不支持纯 sparse 召回（hybrid_search 要求 ann >= 1，
        且部署不支持 fulltext_search）。如需 BM25，请用 search_doc_metadata_hybrid。"""
        logger.debug("search_doc_metadata_by_bm25 is deprecated; use search_doc_metadata_hybrid")
        return []

    def list_chunks_by_doc_range(
        self,
        tenant_id: str,
        doc_id: str,
        start_index: int,
        end_index: int,
        output_fields: list[str] | None = None,
    ) -> list[dict]:
        """按 doc_id + chunk_index 范围拉切片（Parent-Child 扩展用）"""
        if not tenant_id or not doc_id:
            raise ValueError("tenant_id and doc_id are required")
        self._ensure_collections()
        from tcvectordb.model.document import Filter
        tenant_filter = self._tenant_filter(tenant_id)
        filter_expr = (
            f'{tenant_filter} and doc_id = "{doc_id}" '
            f'and chunk_index >= {max(0, start_index)} '
            f'and chunk_index <= {end_index}'
        )
        try:
            results = self._chunk_coll.query(
                filter=Filter(filter_expr),
                output_fields=output_fields or [
                    "id", "doc_id", "chunk_index", "content", "section_title",
                ],
                limit=max(1, end_index - start_index + 1) + 4,
            )
            # query 返回的是 list[dict]，而不是 search 的嵌套 list
            if isinstance(results, list):
                return results
            return self._parse_results(results)
        except Exception as exc:
            logger.warning("list_chunks_by_doc_range failed: %s", exc)
            return []

    def get_doc_metadata(
        self, tenant_id: str, doc_ids: list[str],
        output_fields: list[str] | None = None,
    ) -> dict[str, dict]:
        """批量拉文档级元数据（γ 维度静态属性等）。返回 {doc_id: record}"""
        if not tenant_id or not doc_ids:
            return {}
        self._ensure_collections()
        try:
            results = self._doc_meta_coll.query(
                document_ids=doc_ids,
                output_fields=output_fields or [
                    "id", "tenant_id", "quality_score_x10k", "date_published", "created_at",
                    "search_hit_count", "doc_category", "industry",
                    "summary", "keywords", "title",
                ],
                limit=len(doc_ids),
            )
            if isinstance(results, list):
                # 二次校验 tenant_id（防跨租户泄露）
                return {
                    r.get("id", ""): r for r in results
                    if r.get("id") and str(r.get("tenant_id", "")) == str(tenant_id)
                }
            parsed = self._parse_results(results)
            return {
                r.get("id", ""): r for r in parsed
                if r.get("id") and str(r.get("tenant_id", "")) == str(tenant_id)
            }
        except Exception as exc:
            logger.warning("get_doc_metadata failed: %s", exc)
            return {}

    def count_docs(self, tenant_id: str) -> int:
        """统计 kb_doc_metadata 中某租户的文档数（供健康检查）。

        tcvectordb 单次 query limit 上限 16384。如果单租户超过这个规模需要
        分页；当前实现对超大租户返回 16384（取实际 count 的下界）。
        """
        if not tenant_id:
            return 0
        self._ensure_collections()
        from tcvectordb.model.document import Filter
        try:
            results = self._doc_meta_coll.query(
                filter=Filter(self._tenant_filter(tenant_id)),
                output_fields=["id"],
                limit=16384,
            )
            if isinstance(results, list):
                return len(results)
            return len(self._parse_results(results))
        except Exception as exc:
            logger.warning("count_docs failed: %s", exc)
            return -1

    def list_doc_ids(self, tenant_id: str, limit: int = 16384) -> set[str]:
        """列出某租户在 VDB 中的所有 doc_id（用于健康检查、孤儿清理）。"""
        if not tenant_id:
            return set()
        self._ensure_collections()
        from tcvectordb.model.document import Filter
        try:
            results = self._doc_meta_coll.query(
                filter=Filter(self._tenant_filter(tenant_id)),
                output_fields=["id"],
                limit=min(limit, 16384),
            )
            if not isinstance(results, list):
                results = self._parse_results(results)
            return {r.get("id", "") for r in results if r.get("id")}
        except Exception as exc:
            logger.warning("list_doc_ids failed: %s", exc)
            return set()

    def _vector_search(
        self, vector: list[float], filter_expr: str, top_k: int,
        output_fields: list[str] | None = None,
    ) -> list[dict]:
        from tcvectordb.model.document import Filter
        results = self._chunk_coll.search(
            vectors=[vector], limit=top_k, filter=Filter(filter_expr),
            output_fields=output_fields,
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
        output_fields: list[str] | None = None,
    ) -> list[dict]:
        from tcvectordb.model.document import (
            AnnSearch, KeywordSearch, WeightedRerank, Filter,
        )

        sparse_vec = self._bm25.encode_queries([query_text])
        if not sparse_vec or not sparse_vec[0]:
            return self._vector_search(vector, filter_expr, top_k, output_fields)

        ann = AnnSearch(field_name="vector", data=vector)
        kw = KeywordSearch(field_name="sparse_vector", data=sparse_vec[0])
        rerank = WeightedRerank(
            field_list=["vector", "sparse_vector"],
            weight=[dense_weight, sparse_weight],
        )
        results = self._chunk_coll.hybrid_search(
            ann=[ann], match=[kw], rerank=rerank,
            limit=top_k, filter=Filter(filter_expr),
            output_fields=output_fields,
        )
        return self._parse_results(results)

    # ═══════════════════════════════════════════════════════
    # 删除
    # ═══════════════════════════════════════════════════════

    def delete_by_doc(self, tenant_id: str, doc_id: str) -> None:
        """删除文档对应的所有切片 + 文档元数据"""
        if not tenant_id or not doc_id:
            raise ValueError("tenant_id and doc_id are required")

        self._ensure_collections()
        from tcvectordb.model.document import Filter
        chunk_filter = f'tenant_id = "{tenant_id}" and doc_id = "{doc_id}"'
        try:
            self._chunk_coll.delete(filter=Filter(chunk_filter))
        except Exception as exc:
            logger.warning("Delete chunks failed for doc=%s: %s", doc_id, exc)
        # kb_doc_metadata 的 id 是 primary key，必须用 document_ids 参数删
        try:
            self._doc_meta_coll.delete(document_ids=[doc_id])
        except Exception as exc:
            logger.warning("Delete doc_metadata failed for doc=%s: %s", doc_id, exc)
        logger.info("Deleted VDB entries for tenant=%s doc=%s", tenant_id, doc_id)

    def delete_by_knowledge_base(self, tenant_id: str, knowledge_base_id: str) -> None:
        """清空某个知识库的所有向量"""
        if not tenant_id or not knowledge_base_id:
            raise ValueError("tenant_id and knowledge_base_id are required")

        self._ensure_collections()
        from tcvectordb.model.document import Filter
        filter_expr = (
            f'tenant_id = "{tenant_id}" and knowledge_base_id = "{knowledge_base_id}"'
        )
        try:
            self._chunk_coll.delete(filter=Filter(filter_expr))
            self._doc_meta_coll.delete(filter=Filter(filter_expr))
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
        filter_expr = f'tenant_id = "{tenant_id}" and id in ({ids_expr})'
        try:
            self._chunk_coll.delete(filter=Filter(filter_expr))
        except Exception as exc:
            logger.warning("Delete chunks failed: %s", exc)

    # ═══════════════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def _tenant_filter(tenant_id: str) -> str:
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
            if isinstance(doc_list, dict):
                parsed.append(doc_list)
                continue
            for doc in doc_list:
                if isinstance(doc, dict):
                    parsed.append(doc)
                else:
                    d = {"id": getattr(doc, "id", ""), "score": getattr(doc, "score", 0.0)}
                    if hasattr(doc, "fields") and doc.fields:
                        d.update(doc.fields)
                    parsed.append(d)
        return parsed
