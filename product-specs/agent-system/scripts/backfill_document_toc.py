"""回填 ai_knowledge_document.toc — 对齐 ingestion._build_toc

Toc 内容（对齐 data-process directoryPath 外部路径 + 新方案独有章节增强）：
    第 1 行：knowledge_base_name/dataset_name/file_name    （文件位置）
    后续行：去重后的 section_path                          （章节大纲）

用法：
    .venv/bin/python scripts/backfill_document_toc.py          # 只回填 toc 为空的文档
    .venv/bin/python scripts/backfill_document_toc.py --all    # 强制全量重算
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.store.pg_pool import get_conn


MAX_TOC_CHARS = 8000


def build_toc(
    kb_name: str,
    dataset_name: str,
    file_name: str,
    section_paths: list[str],
    max_chars: int = MAX_TOC_CHARS,
) -> str:
    """与 ingestion._build_toc 行为一致"""
    parts: list[str] = []
    seen: set[str] = set()
    total = 0

    # 1. 外部路径
    ext: list[str] = []
    if kb_name:
        ext.append(kb_name.strip())
    if dataset_name:
        ext.append(dataset_name.strip())
    if file_name:
        ext.append(file_name.strip())
    if ext:
        ext_path = "/".join(ext)
        parts.append(ext_path)
        total += len(ext_path) + 1

    # 2. 章节路径
    for p in section_paths:
        path = (p or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        parts.append(path)
        total += len(path) + 1
        if total >= max_chars:
            break
    return "\n".join(parts)


def main(force_all: bool = False) -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        if force_all:
            cur.execute("""
                SELECT doc_id, knowledge_base_id, dataset_id, file_name
                FROM ai_knowledge_document
                WHERE delete_flg = 0 AND chunk_status = 'indexed'
                ORDER BY created_at
            """)
        else:
            cur.execute("""
                SELECT doc_id, knowledge_base_id, dataset_id, file_name
                FROM ai_knowledge_document
                WHERE delete_flg = 0
                  AND chunk_status = 'indexed'
                  AND (toc IS NULL OR toc = '')
                ORDER BY created_at
            """)
        rows = cur.fetchall()
        total = len(rows)
        print(f"待处理文档数：{total}")

    if not total:
        print("没有需要回填的文档。")
        return 0

    # 预热 kb / dataset 名称缓存，避免重复查
    kb_name_cache: dict[int, str] = {}
    ds_name_cache: dict[int, str] = {}

    def get_kb_name(kb_id: int) -> str:
        if kb_id in kb_name_cache:
            return kb_name_cache[kb_id]
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM ai_knowledge_base WHERE id = %s AND delete_flg = 0",
                        (kb_id,))
            row = cur.fetchone()
        kb_name_cache[kb_id] = (row[0] or "") if row else ""
        return kb_name_cache[kb_id]

    def get_ds_name(ds_id: int) -> str:
        if not ds_id:
            return ""
        if ds_id in ds_name_cache:
            return ds_name_cache[ds_id]
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM ai_knowledge_dataset WHERE id = %s AND delete_flg = 0",
                        (ds_id,))
            row = cur.fetchone()
        ds_name_cache[ds_id] = (row[0] or "") if row else ""
        return ds_name_cache[ds_id]

    done = 0
    empty = 0
    failed = 0
    for doc_id, kb_id, dataset_id, file_name in rows:
        try:
            kb_name = get_kb_name(kb_id)
            ds_name = get_ds_name(dataset_id)

            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT section_path FROM ai_knowledge_chunk
                    WHERE doc_id = %s AND delete_flg = 0
                    ORDER BY chunk_index
                """, (doc_id,))
                paths = [r[0] for r in cur.fetchall()]
                toc = build_toc(kb_name, ds_name, file_name, paths)
                cur.execute("""
                    UPDATE ai_knowledge_document
                    SET toc = %s,
                        updated_at = (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT
                    WHERE doc_id = %s
                """, (toc, doc_id))
                done += 1
                if not toc:
                    empty += 1
        except Exception as exc:
            failed += 1
            print(f"[失败] {doc_id}: {exc}")

        if done % 50 == 0 and done:
            print(f"进度 {done}/{total}")

    print(f"\n=== 完成 ===")
    print(f"  成功: {done}")
    print(f"  空 toc: {empty}")
    print(f"  失败: {failed}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill toc for existing documents")
    parser.add_argument("--all", action="store_true",
                        help="force recompute for all indexed documents")
    args = parser.parse_args()
    sys.exit(main(force_all=args.all))
