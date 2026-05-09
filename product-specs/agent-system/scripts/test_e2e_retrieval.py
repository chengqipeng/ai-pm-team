"""E2E 检索集成测试 — 真实调用 VDB + LKEAP

前提：VDB kb_chunks / kb_doc_metadata 已有数据（可通过 migrate_to_full_vdb.py 导入）
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.config.models import KnowledgeSettings
from src.knowledge.lkeap_client import TencentLKEAPClient
from src.knowledge.retriever import KnowledgeRetriever
from src.knowledge.vdb_writer import KnowledgeVectorStore


async def test(tenant_id: int, query: str, kb_id: int | None = None,
               threshold: float = 0.0, top_k: int = 5) -> None:
    settings = KnowledgeSettings()
    lkeap = TencentLKEAPClient(
        secret_id=settings.lkeap_secret_id,
        secret_key=settings.lkeap_secret_key,
        region=settings.lkeap_region,
    )
    vdb = KnowledgeVectorStore(
        url=settings.vdb_url, key=settings.vdb_key, username=settings.vdb_username,
        database_name=settings.vdb_database, chunk_collection=settings.vdb_chunk_collection,
        doc_metadata_collection=settings.vdb_doc_metadata_collection,
        dimension=settings.embedding_dim,
    )
    retriever = KnowledgeRetriever(
        vector_store=vdb,
        lkeap=lkeap,
        llm=None,      # 跳过 Self-Querying
        embedding_fn=None,
        expand_context_n=1,
    )

    print(f"\n===== 检索 [tenant={tenant_id}] threshold={threshold} Query: {query} =====")
    chunks = await retriever.search(
        tenant_id=tenant_id,
        query=query,
        knowledge_base_id=kb_id,
        top_k=top_k,
        threshold=threshold,
        enable_self_query=False,
    )
    print(f"命中 {len(chunks)} 条切片")
    for i, c in enumerate(chunks, 1):
        print(f"  [{i}] score={c.score:.4f} doc={c.document_id} chunk_idx={c.chunk_index}")


async def main():
    # 相关 query — 使用默认阈值 0.3
    await test(tenant_id=1, query="罗斯蒙特3051DG压力变送器的技术规格",
               threshold=0.3, top_k=3)
    # 无关 query — 严格阈值 0.5，验证是否会被过滤
    await test(tenant_id=1, query="今天北京天气怎么样",
               threshold=0.5, top_k=5)
    # 另一个租户
    await test(tenant_id=292193, query="产品规格",
               threshold=0.3, top_k=3)
    # 测试 quality_score 读回正确（不 ×10000 直接存 Uint64 → x10k）
    print("\n===== γ 维度数据验证 =====")
    settings = KnowledgeSettings()
    vdb = KnowledgeVectorStore(
        url=settings.vdb_url, key=settings.vdb_key, username=settings.vdb_username,
        database_name=settings.vdb_database, chunk_collection=settings.vdb_chunk_collection,
        doc_metadata_collection=settings.vdb_doc_metadata_collection,
        dimension=settings.embedding_dim,
    )
    for tid, did in [("1", "doc_110fde6e367941fba80c"),
                      ("292193", "doc_d24ad9e8de1c402b9fff")]:
        meta = vdb.get_doc_metadata(tid, [did], output_fields=[
            "id", "tenant_id", "quality_score_x10k", "search_hit_count", "date_published",
        ])
        r = meta.get(did, {})
        qs = (r.get("quality_score_x10k") or 0) / 10000.0
        print(f"  tenant={tid} doc={did[:30]}... quality={qs:.4f} hit={r.get('search_hit_count')}")


if __name__ == "__main__":
    asyncio.run(main())
