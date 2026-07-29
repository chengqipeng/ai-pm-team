"""双方案对比评测 — 腾讯 VDB vs SQLite+HNSW

将 30 轮对话数据分别写入两套存储，记录写入性能。
写入后用 200 条用例分别检索，记录检索准确率和延迟。
输出端到端对比报告。

运行：python eval_dual_benchmark.py
"""
from __future__ import annotations

import json, logging, os, re, sqlite3, sys, time
from dataclasses import dataclass, field

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

# 本地模型
_LOCAL_MODEL_PATH = os.path.expanduser("~/models/Qwen3-Embedding-0.6B")
_DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"

# VDB（腾讯向量库）
_VDB_URL = os.environ.get("TENCENT_VDB_URL", "http://10.60.2.17")
_VDB_KEY = os.environ.get("TENCENT_VDB_KEY", "bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck")
_VDB_USER = "root"
_VDB_DB = "viking_memory"
_VDB_COLLECTION = "archive_recall_eval"

# 远程 embedding（VDB 方案用）
_REMOTE_EMBED_MODEL = os.environ.get("EMBEDDING_MODEL", "doubao-embedding-text-240715")
_REMOTE_EMBED_KEY = os.environ.get("EMBEDDING_API_KEY") or os.environ.get(
    "DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")
_REMOTE_EMBED_BASE = os.environ.get("EMBEDDING_API_BASE", "https://ark.cn-beijing.volces.com/api/v3/")

# HNSW
_HNSW_M, _HNSW_EF_C, _HNSW_EF_S = 16, 200, 100
_RRF_K = 60
_TOP_K = 5


# ═══════════════════════════════════════════════════════════
# 数据源
# ═══════════════════════════════════════════════════════════

from src.eval.archive_recall_eval_runner import build_seed_conversation_data


@dataclass
class Case:
    id: str
    category: str
    query: str
    expected_turns: list[int] = field(default_factory=list)
    expected_entity: str = ""
    expect_change: bool = False
    expect_no_hit: bool = False
    mode: str = "timeline"
    target_turn_id: int | None = None


def _load_cases():
    with open("tests/test_context_archive_200cases.py", "r") as f:
        content = f.read()
    start = content.index("def build_cases() -> list[Case]:")
    rest = content[start:]
    lines = rest.split("\n")
    func_lines = [lines[0]]
    for line in lines[1:]:
        if line and not line[0].isspace() and not line.startswith("#"):
            break
        func_lines.append(line)
    func_code = "\n".join(func_lines)
    ns = {"Case": Case, "field": field}
    exec(func_code, ns)
    return ns["build_cases"]()


# ═══════════════════════════════════════════════════════════
# 方案 A: 本地 SQLite + HNSW + Qwen3-Embedding-0.6B
# ═══════════════════════════════════════════════════════════

class LocalStore:
    def __init__(self):
        from sentence_transformers import SentenceTransformer
        logger.info("[Local] Loading Qwen3-Embedding-0.6B on %s...", _DEVICE)
        t0 = time.time()
        self._model = SentenceTransformer(_LOCAL_MODEL_PATH, device=_DEVICE, trust_remote_code=True)
        self._model.encode(["warmup"], normalize_embeddings=True)
        self._load_ms = (time.time() - t0) * 1000
        logger.info("[Local] Model ready: %.0fms", self._load_ms)

        self._conn = sqlite3.connect(":memory:")
        self._hnsw = None
        self._id_map = {}
        self._turns = {}
        self._conn.executescript("""
            CREATE TABLE turns(turn_id INT PRIMARY KEY, text TEXT, entities TEXT, tools TEXT, keywords TEXT, biz TEXT);
            CREATE VIRTUAL TABLE turns_fts USING fts5(text, entities, tools, keywords, biz, content='turns', content_rowid='turn_id', tokenize='unicode61');
            CREATE TRIGGER ti AFTER INSERT ON turns BEGIN
                INSERT INTO turns_fts(rowid, text, entities, tools, keywords, biz) VALUES(new.turn_id, new.text, new.entities, new.tools, new.keywords, new.biz);
            END;
        """)

    def write(self, turns: list[dict]) -> dict:
        """写入全部数据，返回各阶段耗时"""
        timing = {}

        # SQLite 写入
        t0 = time.time()
        texts, tids = [], []
        for t in turns:
            tid = t["turn_id"]
            full = f"{t['user_query']} {t['answer_preview']} {t['entities_text']} {t['keywords']} {t.get('tool_names','')} {t.get('biz_object','')}"
            self._conn.execute("INSERT INTO turns VALUES(?,?,?,?,?,?)",
                (tid, full, t["entities_text"], t.get("tool_names",""), t["keywords"], t.get("biz_object","")))
            self._turns[tid] = t
            texts.append(full)
            tids.append(tid)
        self._conn.commit()
        timing["sqlite_insert_ms"] = (time.time() - t0) * 1000

        # 本地 Embedding
        t0 = time.time()
        vecs = self._model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
        timing["embed_ms"] = (time.time() - t0) * 1000
        timing["embed_per_doc_ms"] = timing["embed_ms"] / len(texts)

        # HNSW 索引构建
        t0 = time.time()
        import hnswlib
        dim = vecs.shape[1]
        self._hnsw = hnswlib.Index(space="cosine", dim=dim)
        self._hnsw.init_index(max_elements=60, ef_construction=_HNSW_EF_C, M=_HNSW_M)
        self._hnsw.set_ef(_HNSW_EF_S)
        self._hnsw.add_items(vecs, list(range(len(tids))))
        for i, tid in enumerate(tids):
            self._id_map[i] = tid
        timing["hnsw_build_ms"] = (time.time() - t0) * 1000

        timing["total_write_ms"] = timing["sqlite_insert_ms"] + timing["embed_ms"] + timing["hnsw_build_ms"]
        timing["per_doc_write_ms"] = timing["total_write_ms"] / len(turns)
        return timing

    def search(self, query: str, top_k: int = _TOP_K) -> tuple[list[int], float]:
        t0 = time.time()
        # Dense
        qv = self._model.encode([f"Instruct: Retrieve relevant conversation context\nQuery: {query}"],
                                normalize_embeddings=True, show_progress_bar=False)[0]
        labels, dists = self._hnsw.knn_query(np.array([qv], dtype=np.float32), k=min(top_k*3, 30))
        dense = [(self._id_map[int(l)], 1.0-d) for l, d in zip(labels[0], dists[0])]
        # Sparse
        kws = self._keywords(query)
        sparse = []
        if kws:
            fts_q = " OR ".join(f'"{w}"' for w in kws)
            try:
                rows = self._conn.execute(
                    "SELECT t.turn_id, rank FROM turns_fts JOIN turns t ON turns_fts.rowid=t.turn_id WHERE turns_fts MATCH ? ORDER BY rank LIMIT ?",
                    (fts_q, top_k*3)).fetchall()
                sparse = [(r[0], abs(r[1])) for r in rows]
            except: pass
        # RRF
        scores = {}
        for rank, (tid, _) in enumerate(dense, 1):
            scores[tid] = scores.get(tid, 0) + 1.0/(_RRF_K+rank)
        for rank, (tid, _) in enumerate(sparse, 1):
            scores[tid] = scores.get(tid, 0) + 1.0/(_RRF_K+rank)
        result = sorted(scores, key=lambda t: -scores[t])[:top_k]
        ms = (time.time()-t0)*1000
        return result, ms

    @staticmethod
    def _keywords(text):
        cn = re.findall(r'[\u4e00-\u9fff]+', text)
        en = re.findall(r'[a-zA-Z0-9$¥_-]+', text)
        words = []
        for s in cn:
            if len(s)<=4: words.append(s)
            else:
                for i in range(len(s)-1): words.append(s[i:i+2])
                for i in range(len(s)-2): words.append(s[i:i+3])
        stops = {"什么","怎么","哪个","哪些","有没有","帮我","请问","一下","可以","能否",
                 "这个","那个","就是","不是","怎么样","多少","现在","上次","之前","所有","相关"}
        return list(set(w for w in words+en if w not in stops and len(w)>=2))


# ═══════════════════════════════════════════════════════════
# 方案 B: 腾讯 VDB + doubao embedding (远程 API)
# ═══════════════════════════════════════════════════════════

class VDBStore:
    def __init__(self):
        from langchain_openai import OpenAIEmbeddings
        from src.memory.viking_engine import VectorStore

        logger.info("[VDB] Connecting to %s...", _VDB_URL)
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
        logger.info("[VDB] Ready.")

    def write(self, turns: list[dict]) -> dict:
        """写入 VDB，返回各阶段耗时"""
        timing = {}
        records = []

        # Embedding（逐条，模拟真实写入场景）
        t0 = time.time()
        vectors = []
        for turn in turns:
            embed_text = (
                f"{turn['user_query']} {turn['answer_preview']} "
                f"{turn.get('entities_text', '')} {turn.get('tool_names', '')}"
            )[:800]
            vec = self._embedding.embed_query(embed_text)
            vectors.append(vec)
        timing["embed_ms"] = (time.time() - t0) * 1000
        timing["embed_per_doc_ms"] = timing["embed_ms"] / len(turns)

        # 构造记录
        for i, turn in enumerate(turns):
            tid = turn["turn_id"]
            bm25_text = f"{turn['user_query']} {turn['answer_preview']}"[:800]
            records.append({
                "id": f"eval_archive_turn_{tid}",
                "vector": vectors[i],
                "tenant_id": "eval",
                "thread_id": "eval_session_001",
                "turn_id": str(tid),
                "has_decision": "1" if any(kw in turn.get("keywords", "") for kw in ["确认", "更新", "砍价", "签约"]) else "0",
                "user_query": turn["user_query"][:500],
                "answer_preview": turn["answer_preview"][:500],
                "entities_text": turn.get("entities_text", "")[:300],
                "tool_names_text": turn.get("tool_names", "")[:200],
                "biz_object": turn.get("biz_object", ""),
                "action_subtype": turn.get("action_subtype", ""),
                "abstract": bm25_text,
                "content": json.dumps(turn, ensure_ascii=False),
                "keywords_json": turn.get("keywords", ""),
                "message_count": "4",
                "archived_at": str(int(time.time() * 1000)),
                "data_timestamp": str(int(time.time() * 1000)),
            })

        # VDB Upsert
        t0 = time.time()
        self._vdb.upsert(records)
        timing["vdb_upsert_ms"] = (time.time() - t0) * 1000
        timing["upsert_per_doc_ms"] = timing["vdb_upsert_ms"] / len(turns)

        timing["total_write_ms"] = timing["embed_ms"] + timing["vdb_upsert_ms"]
        timing["per_doc_write_ms"] = timing["total_write_ms"] / len(turns)
        return timing

    def search(self, query: str, top_k: int = _TOP_K) -> tuple[list[int], float]:
        """VDB hybrid_search"""
        t0 = time.time()
        # Embed query
        query_vec = self._embedding.embed_query(query)
        embed_ms = (time.time() - t0) * 1000

        # Hybrid search
        t1 = time.time()
        filter_expr = 'thread_id = "eval_session_001"'
        results = self._vdb.hybrid_search(
            vector=query_vec, query_text=query,
            top_k=top_k * 3, filter_expr=filter_expr,
            dense_weight=0.6, sparse_weight=0.4,
        )
        search_ms = (time.time() - t1) * 1000

        hit_turns = []
        for r in results[:top_k]:
            tid = r.get("turn_id", "0")
            try:
                hit_turns.append(int(tid))
            except:
                pass

        total_ms = (time.time() - t0) * 1000
        return hit_turns, total_ms


# ═══════════════════════════════════════════════════════════
# 评测引擎
# ═══════════════════════════════════════════════════════════

def evaluate_store(store, cases, label: str) -> dict:
    """对某个 store 跑所有 cases，返回统计"""
    results = []
    all_recall, all_ms = [], []

    for i, case in enumerate(cases):
        if i % 30 == 0:
            logger.info("[%s] Progress: %d/%d", label, i, len(cases))

        hits, ms = store.search(case.query, top_k=_TOP_K)
        all_ms.append(ms)

        if case.expect_no_hit:
            passed = not any(t in (case.expected_turns or []) for t in hits)
            recall = 1.0 if passed else 0.0
        elif not case.expected_turns:
            passed = len(hits) > 0
            recall = 1.0 if passed else 0.0
        else:
            exp = set(case.expected_turns)
            hit = set(hits)
            recall = len(exp & hit) / max(len(exp), 1)
            passed = recall >= 0.3

        all_recall.append(recall)
        results.append({"id": case.id, "cat": case.category, "passed": passed, "recall": recall, "ms": ms,
                        "expected": case.expected_turns, "hit": hits, "query": case.query})

    # 统计
    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    avg_recall = sum(all_recall) / total
    sorted_ms = sorted(all_ms)

    cats = {}
    for r in results:
        cats.setdefault(r["cat"], []).append(r)

    return {
        "total": total,
        "passed": passed_count,
        "pass_rate": passed_count / total,
        "avg_recall": avg_recall,
        "avg_ms": sum(all_ms) / total,
        "p50_ms": sorted_ms[total // 2],
        "p95_ms": sorted_ms[int(total * 0.95)],
        "p99_ms": sorted_ms[int(total * 0.99)],
        "min_ms": min(all_ms),
        "max_ms": max(all_ms),
        "by_category": {
            cat: {"total": len(rs), "passed": sum(1 for r in rs if r["passed"]),
                  "rate": sum(1 for r in rs if r["passed"]) / len(rs)}
            for cat, rs in cats.items()
        },
        "failures": [r for r in results if not r["passed"]][:20],
    }


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

def main():
    seed_data = build_seed_conversation_data()
    cases = [c for c in _load_cases() if c.mode != "full"]
    logger.info("Seed: %d turns | Cases: %d", len(seed_data), len(cases))

    print(f"\n{'═'*70}")
    print(f"  双方案对比评测：腾讯 VDB vs SQLite+HNSW")
    print(f"  数据: {len(seed_data)} 轮对话 | 用例: {len(cases)} 条")
    print(f"{'═'*70}")

    # ════════════════════════════════════════════════════════
    # Phase 1: 写入性能对比
    # ════════════════════════════════════════════════════════
    print(f"\n{'─'*70}")
    print(f"  Phase 1: 数据写入性能")
    print(f"{'─'*70}\n")

    # 方案 A: 本地
    local_store = LocalStore()
    local_write = local_store.write(seed_data)
    print(f"  [SQLite+HNSW] 写入 {len(seed_data)} 条:")
    print(f"    SQLite INSERT:   {local_write['sqlite_insert_ms']:>8.1f}ms")
    print(f"    本地 Embedding:  {local_write['embed_ms']:>8.1f}ms ({local_write['embed_per_doc_ms']:.1f}ms/条)")
    print(f"    HNSW 索引构建:   {local_write['hnsw_build_ms']:>8.1f}ms")
    print(f"    总计:            {local_write['total_write_ms']:>8.1f}ms ({local_write['per_doc_write_ms']:.1f}ms/条)")

    # 方案 B: VDB
    print()
    vdb_store = VDBStore()
    vdb_write = vdb_store.write(seed_data)
    print(f"  [腾讯 VDB] 写入 {len(seed_data)} 条:")
    print(f"    远程 Embedding:  {vdb_write['embed_ms']:>8.1f}ms ({vdb_write['embed_per_doc_ms']:.1f}ms/条)")
    print(f"    VDB Upsert:      {vdb_write['vdb_upsert_ms']:>8.1f}ms ({vdb_write['upsert_per_doc_ms']:.1f}ms/条)")
    print(f"    总计:            {vdb_write['total_write_ms']:>8.1f}ms ({vdb_write['per_doc_write_ms']:.1f}ms/条)")

    print(f"\n  写入性能对比:")
    print(f"  ┌────────────────┬──────────────┬──────────────┐")
    print(f"  │ 阶段           │ SQLite+HNSW  │ 腾讯 VDB     │")
    print(f"  ├────────────────┼──────────────┼──────────────┤")
    print(f"  │ Embedding      │ {local_write['embed_per_doc_ms']:>6.1f}ms/条  │ {vdb_write['embed_per_doc_ms']:>6.1f}ms/条  │")
    print(f"  │ 存储写入       │ {(local_write['sqlite_insert_ms']+local_write['hnsw_build_ms'])/len(seed_data):>6.1f}ms/条  │ {vdb_write['upsert_per_doc_ms']:>6.1f}ms/条  │")
    print(f"  │ 总计           │ {local_write['per_doc_write_ms']:>6.1f}ms/条  │ {vdb_write['per_doc_write_ms']:>6.1f}ms/条  │")
    ratio = vdb_write['per_doc_write_ms'] / max(local_write['per_doc_write_ms'], 0.1)
    print(f"  │ 倍数           │   1x         │   {ratio:.1f}x        │")
    print(f"  └────────────────┴──────────────┴──────────────┘")

    # ════════════════════════════════════════════════════════
    # Phase 2: 检索准确率 + 性能对比
    # ════════════════════════════════════════════════════════
    print(f"\n{'─'*70}")
    print(f"  Phase 2: 检索准确率 + 性能 ({len(cases)} 条用例)")
    print(f"{'─'*70}\n")

    # 方案 A
    logger.info("Running local eval...")
    local_eval = evaluate_store(local_store, cases, "Local")

    # 方案 B
    logger.info("Running VDB eval...")
    vdb_eval = evaluate_store(vdb_store, cases, "VDB")

    # 对比表
    print(f"\n  检索性能对比:")
    print(f"  ┌────────────────────┬──────────────┬──────────────┐")
    print(f"  │ 指标               │ SQLite+HNSW  │ 腾讯 VDB     │")
    print(f"  ├────────────────────┼──────────────┼──────────────┤")
    print(f"  │ 通过率             │ {local_eval['pass_rate']*100:>6.1f}%     │ {vdb_eval['pass_rate']*100:>6.1f}%     │")
    print(f"  │ 平均召回率         │ {local_eval['avg_recall']*100:>6.1f}%     │ {vdb_eval['avg_recall']*100:>6.1f}%     │")
    print(f"  │ P50 延迟           │ {local_eval['p50_ms']:>6.1f}ms     │ {vdb_eval['p50_ms']:>6.1f}ms     │")
    print(f"  │ P95 延迟           │ {local_eval['p95_ms']:>6.1f}ms     │ {vdb_eval['p95_ms']:>6.1f}ms     │")
    print(f"  │ 平均延迟           │ {local_eval['avg_ms']:>6.1f}ms     │ {vdb_eval['avg_ms']:>6.1f}ms     │")
    print(f"  └────────────────────┴──────────────┴──────────────┘")

    # 分类对比
    print(f"\n  按分类对比:")
    print(f"  {'分类':<8} {'Local':>8} {'VDB':>8} {'差异':>8}")
    print(f"  {'─'*40}")
    all_cats = sorted(set(list(local_eval["by_category"].keys()) + list(vdb_eval["by_category"].keys())))
    for cat in all_cats:
        l = local_eval["by_category"].get(cat, {})
        v = vdb_eval["by_category"].get(cat, {})
        lr = l.get("rate", 0) * 100
        vr = v.get("rate", 0) * 100
        diff = lr - vr
        icon = "✅" if diff >= 0 else "❌"
        print(f"  {icon} {cat:<7} {lr:>6.1f}% {vr:>6.1f}% {diff:>+6.1f}%")

    # 失败对比
    local_fails = set(r["id"] for r in local_eval["failures"])
    vdb_fails = set(r["id"] for r in vdb_eval["failures"])
    only_local_fail = local_fails - vdb_fails
    only_vdb_fail = vdb_fails - local_fails
    both_fail = local_fails & vdb_fails

    print(f"\n  失败分析:")
    print(f"    仅 Local 失败: {len(only_local_fail)} 条")
    print(f"    仅 VDB 失败:   {len(only_vdb_fail)} 条")
    print(f"    两者都失败:    {len(both_fail)} 条")

    if only_local_fail:
        print(f"\n    仅 Local 失败的用例:")
        for fid in list(only_local_fail)[:5]:
            r = next(r for r in local_eval["failures"] if r["id"] == fid)
            print(f"      {fid} [{r['cat']}] {r['query'][:35]}")
    if only_vdb_fail:
        print(f"\n    仅 VDB 失败的用例:")
        for fid in list(only_vdb_fail)[:5]:
            r = next(r for r in vdb_eval["failures"] if r["id"] == fid)
            print(f"      {fid} [{r['cat']}] {r['query'][:35]}")

    # 保存
    output = {
        "write_performance": {"local": local_write, "vdb": vdb_write},
        "search_performance": {
            "local": {k: v for k, v in local_eval.items() if k != "failures"},
            "vdb": {k: v for k, v in vdb_eval.items() if k != "failures"},
        },
        "failures": {"local_only": list(only_local_fail), "vdb_only": list(only_vdb_fail), "both": list(both_fail)},
    }
    out_path = "data/eval/runs/dual_benchmark.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(output, fp, ensure_ascii=False, indent=2, default=str)
    print(f"\n  📊 保存: {out_path}")
    print(f"{'═'*70}\n")


if __name__ == "__main__":
    main()
