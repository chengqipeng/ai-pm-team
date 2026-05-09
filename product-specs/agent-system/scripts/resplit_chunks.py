"""按新切分策略（句子级）重切已有文档

用法：
    .venv/bin/python scripts/resplit_chunks.py           # 试跑（不写）
    .venv/bin/python scripts/resplit_chunks.py --commit  # 实际执行

步骤：
  1. 从 PG 拉一份文档的所有 chunks 拼成完整 content
  2. 用 DocumentIngestionPipeline._split_segments + _local_split_chunks 重切
  3. 软删老 chunks，批量写入新 chunks（带新 chunk_id）
  4. 删除 VDB 旧的 kb_chunks 记录，重新 upsert 新 chunk（embedding 重算）
"""
import argparse
import asyncio
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.models import KnowledgeSettings
from src.knowledge.cleaning import CleaningResult, CleaningSignals
from src.knowledge.ingestion import DocumentIngestionPipeline
from src.knowledge.lkeap_client import TencentLKEAPClient
from src.knowledge.queue import IngestTask
from src.knowledge.vdb_writer import KnowledgeVectorStore
from src.store.knowledge_dao import KnowledgeChunkDAO, KnowledgeDocumentDAO
from src.store.knowledge_models import KnowledgeChunkRow
from src.store.pg_pool import get_conn


def fetch_doc_content(doc_id: str) -> tuple[str, list[str]]:
    """把一个文档的所有老切片拼回完整 content，同时返回老 chunk_id 列表。"""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT chunk_id, content
            FROM ai_knowledge_chunk
            WHERE doc_id=%s AND delete_flg=0
            ORDER BY chunk_index
        """, (doc_id,))
        rows = cur.fetchall()
    old_ids = [r[0] for r in rows]
    # 拼接（老切片之间有 overlap，为了避免重复内容，用段落集合去重）
    # 简化：直接顺序拼（有点冗余但对重切无妨）
    full = "\n".join(r[1] for r in rows if r[1])
    return full, old_ids


async def resplit_one(
    doc_id: str,
    commit: bool,
    pipeline: DocumentIngestionPipeline,
    lkeap: TencentLKEAPClient,
    vdb: KnowledgeVectorStore,
) -> dict:
    doc = KnowledgeDocumentDAO.get_by_doc_id(doc_id)
    if not doc:
        return {"doc_id": doc_id, "skipped": "not found"}

    content, old_chunk_ids = fetch_doc_content(doc_id)
    if not content.strip():
        return {"doc_id": doc_id, "skipped": "empty"}

    task = IngestTask.new(
        tenant_id=doc.tenant_id,
        knowledge_base_id=doc.knowledge_base_id,
        dataset_id=doc.dataset_id,
        payload={"doc_id": doc_id, "file_name": doc.file_name},
    )

    # 重新切分
    segments = pipeline._split_segments(doc_id=doc_id, task=task, content=content)
    cleaning = CleaningResult(
        display_content=content,
        content=content,
        signals=CleaningSignals(),
    )
    # 补 Schema 冗余字段
    try:
        import json as _j
        metadata = _j.loads(doc.metadata or "{}")
    except Exception:
        metadata = {}

    new_chunks = pipeline._local_split_chunks(
        doc_id=doc_id, task=task, segments=segments, cleaning=cleaning,
    )
    pipeline._apply_metadata_to_chunks(new_chunks, metadata, task)

    result = {
        "doc_id": doc_id,
        "tenant_id": doc.tenant_id,
        "old_chunks": len(old_chunk_ids),
        "new_segments": len(segments),
        "new_chunks": len(new_chunks),
        "avg_new_chunk_chars": (
            sum(len(c.content) for c in new_chunks) // max(1, len(new_chunks))
        ),
    }

    if not commit:
        return result

    # 执行：软删老切片（PG）→ 插入新切片（PG）→ 删除 VDB 老向量 → 新向量 upsert
    # 1. PG 软删老切片
    KnowledgeChunkDAO.delete_by_doc(doc_id)

    # 2. PG 批量插入新切片
    KnowledgeChunkDAO.batch_insert(new_chunks)

    # 3. 更新 doc chunk_count
    KnowledgeDocumentDAO.update_chunk_status(
        doc_id, "indexed", chunk_count=len(new_chunks), segment_count=len(segments),
    )

    # 4. 更新 toc
    toc = pipeline._build_toc(new_chunks, task, task_payload_file_name=doc.file_name)
    if toc:
        KnowledgeDocumentDAO.update_toc(doc_id, toc)

    # 5. VDB：删除老 chunk 向量
    vdb.delete_by_doc(str(doc.tenant_id), doc_id)

    # 6. VDB：新 chunk embedding + upsert
    texts = [c.content[:2000] for c in new_chunks]
    vectors: list[list[float]] = []
    for t in texts:
        try:
            vec = await asyncio.to_thread(lkeap.get_embedding, [t])
            vectors.append(vec[0] if vec else [])
        except Exception as exc:
            print(f"  [embed 失败] doc={doc_id}: {exc}")
            vectors.append([])

    records: list[dict] = []
    for c, vec in zip(new_chunks, vectors):
        if not vec:
            continue
        records.append({
            "id": c.chunk_id,
            "vector": vec,
            "tenant_id": str(c.tenant_id),
            "knowledge_base_id": str(c.knowledge_base_id),
            "dataset_id": str(c.dataset_id),
            "doc_id": c.doc_id,
            "chunk_type": c.chunk_type,
            "doc_category": c.doc_category,
            "industry": c.industry,
            "business_stage": c.business_stage,
            "target_audience": c.target_audience,
            "product_service": c.product_service,
            "status": "active",
            "date_published": int(c.date_published or 0),
            "content": c.content[:8000],
            "section_title": c.section_title,
            "chunk_index": int(c.chunk_index or 0),
        })
    if records:
        vdb.upsert_chunks(records)
        result["vdb_upserted"] = len(records)

    # 7. 重新生成 doc_metadata record（toc 变了）
    if doc.summary:
        try:
            sv = await asyncio.to_thread(lkeap.get_embedding, [doc.summary])
            summary_vec = sv[0] if sv else None
        except Exception:
            summary_vec = None
        if summary_vec:
            fresh_doc = KnowledgeDocumentDAO.get_by_doc_id(doc_id)
            rec = DocumentIngestionPipeline._build_doc_metadata_record(
                doc_row=fresh_doc,
                summary_vector=summary_vec,
                chunks=new_chunks[:1] if new_chunks else [],
            )
            vdb.upsert_doc_metadata([rec])
            result["doc_metadata_updated"] = True

    return result


async def main(commit: bool) -> int:
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
    # 临时 pipeline 实例（只用来调切分函数，依赖注入可用 None）
    pipeline = DocumentIngestionPipeline(
        lkeap=None,  # type: ignore[arg-type]
        vector_store=None,  # type: ignore[arg-type]
        cleaning_service=None,  # type: ignore[arg-type]
        quality_scorer=None,  # type: ignore[arg-type]
    )

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT doc_id FROM ai_knowledge_document
            WHERE delete_flg=0 AND chunk_status='indexed'
            ORDER BY created_at
        """)
        doc_ids = [r[0] for r in cur.fetchall()]

    print(f"待处理文档数：{len(doc_ids)} (commit={commit})\n")

    for doc_id in doc_ids:
        r = await resplit_one(doc_id, commit, pipeline, lkeap, vdb)
        print(r)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true", help="actually write changes")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.commit)))
