"""清理知识库所有测试残留数据 — 回到干净状态。

⚠️ 这是 **不可逆** 操作。默认 dry-run，加 --commit 才实际执行。

动作：
  1. PG 硬删除所有知识库表里的行（document / chunk / base / dataset / schema /
     ingest_log / ingest_queue / search_log）
  2. VDB truncate kb_chunks 和 kb_doc_metadata 两个集合
  3. 保留 ai_knowledge_schedule（调度配置是平台级，不是数据）
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.models import KnowledgeSettings
from src.knowledge.vdb_writer import KnowledgeVectorStore
from src.store.pg_pool import get_conn


PG_TABLES = [
    "ai_knowledge_ingest_log",
    "ai_knowledge_ingest_queue",
    "ai_knowledge_search_log",
    "ai_knowledge_chunk",
    "ai_knowledge_document",
    "ai_knowledge_dataset",
    "ai_knowledge_schema",
    "ai_knowledge_base",
]


def count_pg() -> dict[str, int]:
    counts: dict[str, int] = {}
    with get_conn() as conn:
        cur = conn.cursor()
        for tbl in PG_TABLES:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                counts[tbl] = int(cur.fetchone()[0])
            except Exception as exc:
                counts[tbl] = -1
                print(f"[!] count {tbl}: {exc}")
    return counts


def truncate_pg() -> None:
    with get_conn() as conn:
        cur = conn.cursor()
        # CASCADE 一把梭，无外键约束也没事
        tables = ", ".join(PG_TABLES)
        cur.execute(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE")


def truncate_vdb(settings: KnowledgeSettings) -> None:
    import tcvectordb
    client = tcvectordb.VectorDBClient(
        url=settings.vdb_url, username=settings.vdb_username, key=settings.vdb_key, timeout=30,
    )
    db = client.database(settings.vdb_database)
    for coll_name in [settings.vdb_chunk_collection, settings.vdb_doc_metadata_collection]:
        try:
            db.truncate_collection(collection_name=coll_name)
            print(f"  VDB truncated: {coll_name}")
        except Exception as exc:
            print(f"[!] VDB truncate {coll_name} failed: {exc}")


def main(commit: bool) -> int:
    print("=== PG 当前数据量 ===")
    before = count_pg()
    for tbl, n in before.items():
        print(f"  {tbl}: {n}")

    if not commit:
        print("\n[dry-run] 加 --commit 才实际执行清理。")
        return 0

    print("\n=== 执行 PG TRUNCATE ===")
    truncate_pg()
    print("  done")

    print("\n=== 执行 VDB TRUNCATE ===")
    settings = KnowledgeSettings()
    truncate_vdb(settings)

    print("\n=== 清理后 ===")
    after = count_pg()
    for tbl, n in after.items():
        print(f"  {tbl}: {n}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true",
                        help="actually delete (default: dry-run)")
    args = parser.parse_args()
    sys.exit(main(args.commit))
