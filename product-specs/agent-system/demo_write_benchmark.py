"""写入性能对比 Demo — SQLite+HNSW+Qwen3 vs 腾讯VDB+doubao

验证两套方案在相同 30 轮对话数据下的写入性能差异。
分别测试单条写入（模拟实时对话存档）和批量写入（模拟初始化导入）。

运行：python demo_write_benchmark.py
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

# VDB
_VDB_URL = os.environ.get("TENCENT_VDB_URL", "http://10.60.2.17")
_VDB_KEY = os.environ.get("TENCENT_VDB_KEY", "bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck")
_VDB_USER = "root"
_VDB_DB = "viking_memory"
_VDB_COLLECTION = "write_bench_eval"

# 远程 Embedding
_REMOTE_EMBED_MODEL = os.environ.get("EMBEDDING_MODEL", "doubao-embedding-text-240715")
_REMOTE_EMBED_KEY = os.environ.get("EMBEDDING_API_KEY") or os.environ.get(
    "DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")
_REMOTE_EMBED_BASE = os.environ.get("EMBEDDING_API_BASE", "https://ark.cn-beijing.volces.com/api/v3/")

# HNSW
_HNSW_M, _HNSW_EF_C = 16, 200


# ═══════════════════════════════════════════════════════════
# 测试数据
# ═══════════════════════════════════════════════════════════

from src.eval.archive_recall_eval_runner import build_seed_conversation_data


def build_embed_text(turn: dict) -> str:
    """统一的 embedding 输入文本构造（两个方案完全一致）"""
    return (
        f"{turn['user_query']} {turn['answer_preview']} "
        f"{turn['entities_text']} {turn['keywords']} "
        f"{turn.get('tool_names', '')} {turn.get('biz_object', '')}"
    )[:800]


# ═══════════════════════════════════════════════════════════
# 方案 A: SQLite + HNSW + Qwen3-Embedding-0.6B (本地)
# ═══════════════════════════════════════════════════════════

class LocalWriter:
    """本地写入器"""

    def __init__(self):
        from src.embedding import LocalEmbedding
        self._emb = LocalEmbedding()
        self._conn = None
        self._hnsw = None
        self._next_id = 0

    def _init_storage(self):
        """初始化 SQLite + HNSW（每次 benchmark 前重建）"""
        self._conn = sqlite3.connect(":memory:")
        self._conn.executescript("""
            CREATE TABLE turns (
                turn_id INTEGER PRIMARY KEY,
                embed_text TEXT,
                entities TEXT,
                tools TEXT,
                keywords TEXT,
                biz TEXT
            );
            CREATE VIRTUAL TABLE turns_fts USING fts5(
                embed_text, entities, tools, keywords, biz,
                content='turns', content_rowid='turn_id',
                tokenize='unicode61'
            );
            CREATE TRIGGER ti AFTER INSERT ON turns BEGIN
                INSERT INTO turns_fts(rowid, embed_text, entities, tools, keywords, biz)
                VALUES(new.turn_id, new.embed_text, new.entities, new.tools, new.keywords, new.biz);
            END;
        """)
        import hnswlib
        self._hnsw = hnswlib.Index(space="cosine", dim=self._emb.dimension)
        self._hnsw.init_index(max_elements=100, ef_construction=_HNSW_EF_C, M=_HNSW_M)
        self._next_id = 0

    def benchmark_single(self, turns: list[dict]) -> dict:
        """单条写入模式 — 逐条 embed + 逐条写入（模拟实时对话存档）"""
        self._init_storage()
        timings = []

        for turn in turns:
            tid = turn["turn_id"]
            text = build_embed_text(turn)

            # Embedding（单条）
            t0 = time.time()
            vec = self._emb.embed_query_np(text, task="retrieval")
            embed_ms = (time.time() - t0) * 1000

            # SQLite INSERT
            t0 = time.time()
            self._conn.execute(
                "INSERT INTO turns VALUES(?,?,?,?,?,?)",
                (tid, text, turn["entities_text"], turn.get("tool_names", ""),
                 turn["keywords"], turn.get("biz_object", ""))
            )
            self._conn.commit()
            sqlite_ms = (time.time() - t0) * 1000

            # HNSW add
            t0 = time.time()
            self._hnsw.add_items(np.array([vec], dtype=np.float32), [self._next_id])
            self._next_id += 1
            hnsw_ms = (time.time() - t0) * 1000

            timings.append({
                "turn_id": tid,
                "embed_ms": embed_ms,
                "sqlite_ms": sqlite_ms,
                "hnsw_ms": hnsw_ms,
                "total_ms": embed_ms + sqlite_ms + hnsw_ms,
            })

        return self._summarize(timings, "single")

    def benchmark_batch(self, turns: list[dict]) -> dict:
        """批量写入模式 — 批量 embed + 批量写入（模拟初始化导入）"""
        self._init_storage()

        texts = [build_embed_text(t) for t in turns]

        # 批量 Embedding
        t0 = time.time()
        vecs = self._emb.embed_documents_np(texts)
        embed_ms = (time.time() - t0) * 1000

        # 批量 SQLite INSERT
        t0 = time.time()
        for i, turn in enumerate(turns):
            self._conn.execute(
                "INSERT INTO turns VALUES(?,?,?,?,?,?)",
                (turn["turn_id"], texts[i], turn["entities_text"],
                 turn.get("tool_names", ""), turn["keywords"], turn.get("biz_object", ""))
            )
        self._conn.commit()
        sqlite_ms = (time.time() - t0) * 1000

        # 批量 HNSW add
        t0 = time.time()
        ids = list(range(len(turns)))
        self._hnsw.add_items(vecs, ids)
        hnsw_ms = (time.time() - t0) * 1000

        return {
            "mode": "batch",
            "count": len(turns),
            "embed_ms": round(embed_ms, 1),
            "embed_per_doc_ms": round(embed_ms / len(turns), 1),
            "sqlite_ms": round(sqlite_ms, 1),
            "sqlite_per_doc_ms": round(sqlite_ms / len(turns), 2),
            "hnsw_ms": round(hnsw_ms, 1),
            "hnsw_per_doc_ms": round(hnsw_ms / len(turns), 2),
            "storage_ms": round(sqlite_ms + hnsw_ms, 1),
            "storage_per_doc_ms": round((sqlite_ms + hnsw_ms) / len(turns), 2),
            "total_ms": round(embed_ms + sqlite_ms + hnsw_ms, 1),
            "total_per_doc_ms": round((embed_ms + sqlite_ms + hnsw_ms) / len(turns), 1),
            "throughput": round(len(turns) / ((embed_ms + sqlite_ms + hnsw_ms) / 1000), 1),
        }

    @staticmethod
    def _summarize(timings: list[dict], mode: str) -> dict:
        n = len(timings)
        embed_times = [t["embed_ms"] for t in timings]
        sqlite_times = [t["sqlite_ms"] for t in timings]
        hnsw_times = [t["hnsw_ms"] for t in timings]
        total_times = [t["total_ms"] for t in timings]

        return {
            "mode": mode,
            "count": n,
            "embed_avg_ms": round(sum(embed_times) / n, 1),
            "embed_p50_ms": round(sorted(embed_times)[n // 2], 1),
            "embed_p95_ms": round(sorted(embed_times)[int(n * 0.95)], 1),
            "sqlite_avg_ms": round(sum(sqlite_times) / n, 2),
            "hnsw_avg_ms": round(sum(hnsw_times) / n, 2),
            "storage_avg_ms": round((sum(sqlite_times) + sum(hnsw_times)) / n, 2),
            "total_avg_ms": round(sum(total_times) / n, 1),
            "total_p50_ms": round(sorted(total_times)[n // 2], 1),
            "total_p95_ms": round(sorted(total_times)[int(n * 0.95)], 1),
            "total_sum_ms": round(sum(total_times), 1),
            "throughput": round(n / (sum(total_times) / 1000), 1),
        }


# ═══════════════════════════════════════════════════════════
# 方案 B: 腾讯 VDB + doubao Embedding (远程)
# ═══════════════════════════════════════════════════════════

class VDBWriter:
    """腾讯 VDB 写入器"""

    def __init__(self):
        from langchain_openai import OpenAIEmbeddings
        from src.memory.viking_engine import VectorStore

        self._vdb = VectorStore(
            url=_VDB_URL, key=_VDB_KEY, username=_VDB_USER,
            database_name=_VDB_DB, collection_name=_VDB_COLLECTION,
        )
        self._embedding = OpenAIEmbeddings(
            model=_REMOTE_EMBED_MODEL, api_key=_REMOTE_EMBED_KEY,
            base_url=_REMOTE_EMBED_BASE, check_embedding_ctx_length=False,
        )
        # Warmup
        self._embedding.embed_query("warmup")

    def _build_record(self, turn: dict, vector: list[float]) -> dict:
        """构造 VDB 记录"""
        tid = turn["turn_id"]
        bm25_text = f"{turn['user_query']} {turn['answer_preview']}"[:800]
        return {
            "id": f"write_bench_turn_{tid}",
            "vector": vector,
            "tenant_id": "bench",
            "thread_id": "bench_session_001",
            "turn_id": str(tid),
            "has_decision": "1" if any(kw in turn.get("keywords", "") for kw in ["确认", "更新", "砍价", "签约"]) else "0",
            "user_query": turn["user_query"][:500],
            "answer_preview": turn["answer_preview"][:500],
            "entities_text": turn.get("entities_text", "")[:300],
            "tool_names_text": turn.get("tool_names", "")[:200],
            "biz_object": turn.get("biz_object", ""),
            "action_subtype": turn.get("action_subtype", ""),
            "abstract": bm25_text,
            "keywords_json": turn.get("keywords", ""),
        }

    def benchmark_single(self, turns: list[dict]) -> dict:
        """单条写入模式 — 逐条 embed + 逐条 upsert"""
        timings = []

        for turn in turns:
            text = build_embed_text(turn)

            # Embedding（远程 API）
            t0 = time.time()
            vec = self._embedding.embed_query(text)
            embed_ms = (time.time() - t0) * 1000

            # VDB Upsert（单条）
            record = self._build_record(turn, vec)
            t0 = time.time()
            self._vdb.upsert([record])
            upsert_ms = (time.time() - t0) * 1000

            timings.append({
                "turn_id": turn["turn_id"],
                "embed_ms": embed_ms,
                "upsert_ms": upsert_ms,
                "total_ms": embed_ms + upsert_ms,
            })

        return self._summarize(timings, "single")

    def benchmark_batch(self, turns: list[dict]) -> dict:
        """批量写入模式 — 逐条 embed + 批量 upsert"""
        texts = [build_embed_text(t) for t in turns]

        # Embedding（逐条远程调用，doubao 不支持批量）
        vectors = []
        t0 = time.time()
        for text in texts:
            vec = self._embedding.embed_query(text)
            vectors.append(vec)
        embed_ms = (time.time() - t0) * 1000

        # VDB 批量 Upsert
        records = [self._build_record(turn, vectors[i]) for i, turn in enumerate(turns)]
        t0 = time.time()
        self._vdb.upsert(records)
        upsert_ms = (time.time() - t0) * 1000

        return {
            "mode": "batch",
            "count": len(turns),
            "embed_ms": round(embed_ms, 1),
            "embed_per_doc_ms": round(embed_ms / len(turns), 1),
            "upsert_ms": round(upsert_ms, 1),
            "upsert_per_doc_ms": round(upsert_ms / len(turns), 1),
            "storage_ms": round(upsert_ms, 1),
            "storage_per_doc_ms": round(upsert_ms / len(turns), 1),
            "total_ms": round(embed_ms + upsert_ms, 1),
            "total_per_doc_ms": round((embed_ms + upsert_ms) / len(turns), 1),
            "throughput": round(len(turns) / ((embed_ms + upsert_ms) / 1000), 1),
        }

    @staticmethod
    def _summarize(timings: list[dict], mode: str) -> dict:
        n = len(timings)
        embed_times = [t["embed_ms"] for t in timings]
        upsert_times = [t["upsert_ms"] for t in timings]
        total_times = [t["total_ms"] for t in timings]

        return {
            "mode": mode,
            "count": n,
            "embed_avg_ms": round(sum(embed_times) / n, 1),
            "embed_p50_ms": round(sorted(embed_times)[n // 2], 1),
            "embed_p95_ms": round(sorted(embed_times)[int(n * 0.95)], 1),
            "storage_avg_ms": round(sum(upsert_times) / n, 1),
            "storage_p50_ms": round(sorted(upsert_times)[n // 2], 1),
            "storage_p95_ms": round(sorted(upsert_times)[int(n * 0.95)], 1),
            "total_avg_ms": round(sum(total_times) / n, 1),
            "total_p50_ms": round(sorted(total_times)[n // 2], 1),
            "total_p95_ms": round(sorted(total_times)[int(n * 0.95)], 1),
            "total_sum_ms": round(sum(total_times), 1),
            "throughput": round(n / (sum(total_times) / 1000), 1),
        }


# ═══════════════════════════════════════════════════════════
# 输出报告
# ═══════════════════════════════════════════════════════════

def print_report(local_single, local_batch, vdb_single, vdb_batch):
    print(f"\n{'═'*72}")
    print(f"  写入性能对比 — SQLite+HNSW+Qwen3 vs 腾讯VDB+doubao")
    print(f"  数据: 30 轮 CRM 对话存档 | 统一 embed 文本构造")
    print(f"{'═'*72}")

    # 单条写入
    print(f"\n{'─'*72}")
    print(f"  模式 1: 单条写入（模拟 Agent 对话实时存档）")
    print(f"{'─'*72}")
    print(f"\n  ┌────────────────────┬──────────────────┬──────────────────┐")
    print(f"  │ 指标               │ SQLite+HNSW      │ 腾讯 VDB         │")
    print(f"  ├────────────────────┼──────────────────┼──────────────────┤")
    print(f"  │ Embedding 均值     │ {local_single['embed_avg_ms']:>8.1f}ms       │ {vdb_single['embed_avg_ms']:>8.1f}ms       │")
    print(f"  │ Embedding P50      │ {local_single['embed_p50_ms']:>8.1f}ms       │ {vdb_single['embed_p50_ms']:>8.1f}ms       │")
    print(f"  │ Embedding P95      │ {local_single['embed_p95_ms']:>8.1f}ms       │ {vdb_single['embed_p95_ms']:>8.1f}ms       │")
    print(f"  │ 存储写入均值       │ {local_single['storage_avg_ms']:>8.2f}ms       │ {vdb_single['storage_avg_ms']:>8.1f}ms       │")
    print(f"  │ 端到端均值         │ {local_single['total_avg_ms']:>8.1f}ms       │ {vdb_single['total_avg_ms']:>8.1f}ms       │")
    print(f"  │ 端到端 P50         │ {local_single['total_p50_ms']:>8.1f}ms       │ {vdb_single['total_p50_ms']:>8.1f}ms       │")
    print(f"  │ 端到端 P95         │ {local_single['total_p95_ms']:>8.1f}ms       │ {vdb_single['total_p95_ms']:>8.1f}ms       │")
    print(f"  │ 吞吐量             │ {local_single['throughput']:>8.1f} 条/s    │ {vdb_single['throughput']:>8.1f} 条/s    │")
    ratio_s = vdb_single['total_avg_ms'] / max(local_single['total_avg_ms'], 0.1)
    print(f"  │ 倍数(VDB/Local)    │      1x          │    {ratio_s:>5.1f}x         │")
    print(f"  └────────────────────┴──────────────────┴──────────────────┘")

    # 批量写入
    print(f"\n{'─'*72}")
    print(f"  模式 2: 批量写入（模拟初始化导入 30 条）")
    print(f"{'─'*72}")
    print(f"\n  ┌────────────────────┬──────────────────┬──────────────────┐")
    print(f"  │ 指标               │ SQLite+HNSW      │ 腾讯 VDB         │")
    print(f"  ├────────────────────┼──────────────────┼──────────────────┤")
    print(f"  │ Embedding 总耗时   │ {local_batch['embed_ms']:>8.1f}ms       │ {vdb_batch['embed_ms']:>8.1f}ms       │")
    print(f"  │ Embedding 每条     │ {local_batch['embed_per_doc_ms']:>8.1f}ms       │ {vdb_batch['embed_per_doc_ms']:>8.1f}ms       │")
    print(f"  │ 存储写入总耗时     │ {local_batch['storage_ms']:>8.1f}ms       │ {vdb_batch['storage_ms']:>8.1f}ms       │")
    print(f"  │ 存储写入每条       │ {local_batch['storage_per_doc_ms']:>8.2f}ms       │ {vdb_batch['storage_per_doc_ms']:>8.1f}ms       │")
    print(f"  │ 端到端总耗时       │ {local_batch['total_ms']:>8.1f}ms       │ {vdb_batch['total_ms']:>8.1f}ms       │")
    print(f"  │ 端到端每条         │ {local_batch['total_per_doc_ms']:>8.1f}ms       │ {vdb_batch['total_per_doc_ms']:>8.1f}ms       │")
    print(f"  │ 吞吐量             │ {local_batch['throughput']:>8.1f} 条/s    │ {vdb_batch['throughput']:>8.1f} 条/s    │")
    ratio_b = vdb_batch['total_ms'] / max(local_batch['total_ms'], 0.1)
    print(f"  │ 倍数(VDB/Local)    │      1x          │    {ratio_b:>5.1f}x         │")
    print(f"  └────────────────────┴──────────────────┴──────────────────┘")

    # 分项拆解
    print(f"\n{'─'*72}")
    print(f"  分项延迟拆解（单条写入）")
    print(f"{'─'*72}")
    print(f"\n  SQLite+HNSW+Qwen3:")
    print(f"    Embedding (本地 MPS):  {local_single['embed_avg_ms']:.1f}ms")
    print(f"    SQLite INSERT + FTS5:  {local_single['storage_avg_ms']:.2f}ms")
    print(f"    → 存储几乎无开销，瓶颈在本地模型推理")
    print(f"\n  腾讯 VDB+doubao:")
    print(f"    Embedding (远程 API):  {vdb_single['embed_avg_ms']:.1f}ms")
    print(f"    VDB Upsert (网络):     {vdb_single['storage_avg_ms']:.1f}ms")
    print(f"    → 网络双重开销（embed API + VDB upsert）")

    print(f"\n{'═'*72}\n")


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

def main():
    seed_data = build_seed_conversation_data()
    logger.info("Test data: %d turns", len(seed_data))

    print(f"\n🚀 写入性能对比 Benchmark")
    print(f"   数据: {len(seed_data)} 轮 CRM 对话存档")
    print(f"   方案 A: SQLite + HNSW + Qwen3-Embedding-0.6B (本地 {_LOCAL_DEVICE})")
    print(f"   方案 B: 腾讯 VDB + doubao-embedding (远程 API)")
    print()

    # 方案 A
    logger.info("=== 方案 A: SQLite+HNSW (本地) ===")
    local_writer = LocalWriter()

    logger.info("[Local] 批量写入...")
    local_batch = local_writer.benchmark_batch(seed_data)
    logger.info("[Local] 批量完成: %.0fms", local_batch["total_ms"])

    logger.info("[Local] 单条写入...")
    local_single = local_writer.benchmark_single(seed_data)
    logger.info("[Local] 单条完成: avg=%.1fms/条", local_single["total_avg_ms"])

    # 方案 B
    logger.info("=== 方案 B: 腾讯 VDB (远程) ===")
    vdb_writer = VDBWriter()

    logger.info("[VDB] 批量写入...")
    vdb_batch = vdb_writer.benchmark_batch(seed_data)
    logger.info("[VDB] 批量完成: %.0fms", vdb_batch["total_ms"])

    logger.info("[VDB] 单条写入...")
    vdb_single = vdb_writer.benchmark_single(seed_data)
    logger.info("[VDB] 单条完成: avg=%.1fms/条", vdb_single["total_avg_ms"])

    # 输出报告
    print_report(local_single, local_batch, vdb_single, vdb_batch)

    # 保存 JSON
    output = {
        "test_data": {"count": len(seed_data), "source": "build_seed_conversation_data()"},
        "local": {"single": local_single, "batch": local_batch,
                  "model": "Qwen3-Embedding-0.6B", "device": _LOCAL_DEVICE},
        "vdb": {"single": vdb_single, "batch": vdb_batch,
                "model": "doubao-embedding-text-240715", "vdb_url": _VDB_URL},
    }
    out_path = "data/eval/runs/write_benchmark.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(output, fp, ensure_ascii=False, indent=2)
    print(f"  📊 详细数据: {out_path}\n")


# 检测设备（模块级变量）
import torch
_LOCAL_DEVICE = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")

if __name__ == "__main__":
    main()
