"""全 VDB 架构迁移脚本

从 PG 读所有已索引文档 + 切片，重新 upsert 到 VDB 新 schema（kb_chunks + kb_doc_metadata）。

用法：
  .venv/bin/python scripts/migrate_to_full_vdb.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.config.models import KnowledgeSettings
from src.knowledge.ingestion import DocumentIngestionPipeline
from src.knowledge.lkeap_client import TencentLKEAPClient
from src.knowledge.vdb_writer import KnowledgeVectorStore
from src.store.knowledge_dao import KnowledgeDocumentDAO
from src.store.knowledge_models import KnowledgeChunkRow as _ChunkRow
from src.store.pg_pool import get_conn


async def migrate() -> int:
    settings = KnowledgeSettings()
    lkeap = TencentLKEAPClient(
        secret_id=settings.lkeap_secret_id,
        secret_key=settings.lkeap_secret_key,
        region=settings.lkeap_region,
    )
    vdb = KnowledgeVectorStore(
        url=settings.vdb_url,
        key=settings.vdb_key,
        username=settings.vdb_username,
        database_name=settings.vdb_database,
        chunk_collection=settings.vdb_chunk_collection,
        doc_metadata_collection=settings.vdb_doc_metadata_collection,
        dimension=settings.embedding_dim,
    )

    # 列举所有已索引文档
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT doc_id FROM ai_knowledge_document
            WHERE delete_flg=0 AND chunk_status='indexed'
            ORDER BY created_at
        """)
        doc_ids = [r[0] for r in cur.fetchall()]

    print(f"发现 {len(doc_ids)} 份已索引文档")

    success_docs = 0
    success_chunks = 0
    for doc_id in doc_ids:
        doc_row = KnowledgeDocumentDAO.get_by_doc_id(doc_id)
        if not doc_row:
            continue

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM ai_knowledge_chunk
                WHERE doc_id=%s AND delete_flg=0
                ORDER BY chunk_index
            """, (doc_id,))
            colnames = [d[0] for d in cur.description]
            chunk_dicts = [dict(zip(colnames, row)) for row in cur.fetchall()]
        if not chunk_dicts:
            print(f"[跳过] doc={doc_id} 无切片")
            continue

        print(f"\n处理 doc={doc_id} title={doc_row.title} chunks={len(chunk_dicts)}")

        # 嵌入切片（LKEAP 单条 1 个 input）
        texts = [(c["content"] or "")[:2000] for c in chunk_dicts]
        vectors = []
        for t in texts:
            try:
                vec = await asyncio.to_thread(lkeap.get_embedding, [t])
                vectors.append(vec[0] if vec else [])
            except Exception as exc:
                print(f"  [embed 失败] {exc}")
                vectors.append([])

        chunk_records = []
        for c, vec in zip(chunk_dicts, vectors):
            if not vec:
                continue
            chunk_records.append({
                "id": c["chunk_id"],
                "vector": vec,
                "tenant_id": str(c["tenant_id"]),
                "knowledge_base_id": str(c["knowledge_base_id"]),
                "dataset_id": str(c["dataset_id"]),
                "doc_id": c["doc_id"],
                "chunk_type": c.get("chunk_type") or "",
                "doc_category": c.get("doc_category") or "",
                "industry": c.get("industry") or "",
                "business_stage": c.get("business_stage") or "",
                "target_audience": c.get("target_audience") or "",
                "product_service": c.get("product_service") or "",
                "status": "active",
                "date_published": int(c.get("date_published") or 0),
                "content": (c.get("content") or "")[:8000],
                "section_title": c.get("section_title") or "",
                "chunk_index": int(c.get("chunk_index") or 0),
            })

        if chunk_records:
            try:
                vdb.upsert_chunks(chunk_records)
                success_chunks += len(chunk_records)
                print(f"  ✅ chunks upsert: {len(chunk_records)}")
            except Exception as exc:
                print(f"  ❌ chunks upsert: {exc}")
                continue

        # 文档级元数据
        summary_vec = None
        if doc_row.summary:
            try:
                sv = await asyncio.to_thread(lkeap.get_embedding, [doc_row.summary])
                summary_vec = sv[0] if sv else None
            except Exception as exc:
                print(f"  [summary embed 失败] {exc}")

        if summary_vec:
            sample = _ChunkRow(
                doc_category=(chunk_dicts[0].get("doc_category") or ""),
                industry=(chunk_dicts[0].get("industry") or ""),
                business_stage=(chunk_dicts[0].get("business_stage") or ""),
                target_audience=(chunk_dicts[0].get("target_audience") or ""),
                product_service=(chunk_dicts[0].get("product_service") or ""),
            )
            rec = DocumentIngestionPipeline._build_doc_metadata_record(  # noqa: SLF001
                doc_row=doc_row,
                summary_vector=summary_vec,
                chunks=[sample],
            )
            try:
                vdb.upsert_doc_metadata([rec])
                success_docs += 1
                print(f"  ✅ doc_metadata upsert")
            except Exception as exc:
                print(f"  ❌ doc_metadata upsert: {exc}")
        else:
            print(f"  [跳过 doc_metadata] summary empty")

    print(f"\n=== 完成 ===")
    print(f"  文档: {success_docs}/{len(doc_ids)}")
    print(f"  切片: {success_chunks}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(migrate()))
