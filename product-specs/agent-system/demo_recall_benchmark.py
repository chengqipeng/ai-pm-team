"""检索准确率对比 Demo — SQLite+HNSW+Qwen3 vs 腾讯VDB+doubao

相同数据 → 分别写入两套存储 → 相同 190 条用例 → 相同评判标准 → 输出对比报告。
不调 LLM，纯向量+关键词检索，对比 embedding 模型 + 存储引擎的准确率差异。

运行：python demo_recall_benchmark.py
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

_VDB_URL = os.environ.get("TENCENT_VDB_URL", "http://10.60.2.17")
_VDB_KEY = os.environ.get("TENCENT_VDB_KEY", "bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck")
_VDB_USER = "root"
_VDB_DB = "viking_memory"
_VDB_COLLECTION = "archive_recall_eval"

_REMOTE_EMBED_MODEL = os.environ.get("EMBEDDING_MODEL", "doubao-embedding-text-240715")
_REMOTE_EMBED_KEY = os.environ.get("EMBEDDING_API_KEY") or os.environ.get(
    "DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")
_REMOTE_EMBED_BASE = os.environ.get("EMBEDDING_API_BASE", "https://ark.cn-beijing.volces.com/api/v3/")

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


def _load_cases() -> list[Case]:
    """从 test file 加载 build_cases()"""
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
    ns = {"Case": Case, "field": field}
    exec("\n".join(func_lines), ns)
    return ns["build_cases"]()


def build_embed_text(turn: dict) -> str:
    """统一的 embedding 输入文本（两方案一致）"""
    return (
        f"{turn['user_query']} {turn['answer_preview']} "
        f"{turn['entities_text']} {turn['keywords']} "
        f"{turn.get('tool_names', '')} {turn.get('biz_object', '')}"
    )[:800]


# ═══════════════════════════════════════════════════════════
# 方案 A: SQLite + HNSW + Qwen3-Embedding-0.6B
# ═══════════════════════════════════════════════════════════

class LocalEngine:
    def __init__(self):
        from src.embedding import LocalEmbedding
        self._emb = LocalEmbedding()
        self._conn = sqlite3.connect(":memory:")
        self._hnsw = None
        self._id_map: dict[int, int] = {}
        self._conn.executescript("""
            CREATE TABLE turns(turn_id INT PRIMARY KEY, text TEXT, entities TEXT, tools TEXT, keywords TEXT, biz TEXT);
            CREATE VIRTUAL TABLE turns_fts USING fts5(text, entities, tools, keywords, biz,
                content='turns', content_rowid='turn_id', tokenize='unicode61');
            CREATE TRIGGER ti AFTER INSERT ON turns BEGIN
                INSERT INTO turns_fts(rowid, text, entities, tools, keywords, biz)
                VALUES(new.turn_id, new.text, new.entities, new.tools, new.keywords, new.biz);
            END;
        """)

    def write(self, turns: list[dict]):
        """写入全部数据"""
        texts = [build_embed_text(t) for t in turns]
        # Embedding
        vecs = self._emb.embed_documents_np(texts)
        # SQLite
        for i, turn in enumerate(turns):
            self._conn.execute("INSERT INTO turns VALUES(?,?,?,?,?,?)",
                (turn["turn_id"], texts[i], turn["entities_text"],
                 turn.get("tool_names", ""), turn["keywords"], turn.get("biz_object", "")))
        self._conn.commit()
        # HNSW
        import hnswlib
        dim = vecs.shape[1]
        self._hnsw = hnswlib.Index(space="cosine", dim=dim)
        self._hnsw.init_index(max_elements=60, ef_construction=_HNSW_EF_C, M=_HNSW_M)
        self._hnsw.set_ef(_HNSW_EF_S)
        self._hnsw.add_items(vecs, list(range(len(turns))))
        for i, turn in enumerate(turns):
            self._id_map[i] = turn["turn_id"]
        logger.info("[Local] Written %d turns, dim=%d", len(turns), dim)

    def search(self, query: str, top_k: int = _TOP_K) -> tuple[list[int], float]:
        t0 = time.time()
        # Dense
        qv = self._emb.embed_query_np(query)
        labels, dists = self._hnsw.knn_query(np.array([qv], dtype=np.float32), k=min(top_k * 3, 30))
        dense = [(self._id_map[int(l)], 1.0 - d) for l, d in zip(labels[0], dists[0])]
        # Sparse
        sparse = self._fts_search(query, top_k * 3)
        # RRF
        scores: dict[int, float] = {}
        for rank, (tid, _) in enumerate(dense, 1):
            scores[tid] = scores.get(tid, 0) + 1.0 / (_RRF_K + rank)
        for rank, (tid, _) in enumerate(sparse, 1):
            scores[tid] = scores.get(tid, 0) + 1.0 / (_RRF_K + rank)
        result = sorted(scores, key=lambda t: -scores[t])[:top_k]
        ms = (time.time() - t0) * 1000
        return result, ms

    def _fts_search(self, query: str, top_k: int) -> list[tuple[int, float]]:
        kws = self._keywords(query)
        if not kws:
            return []
        fts_q = " OR ".join(f'"{w}"' for w in kws)
        try:
            rows = self._conn.execute(
                "SELECT t.turn_id, rank FROM turns_fts "
                "JOIN turns t ON turns_fts.rowid=t.turn_id "
                "WHERE turns_fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_q, top_k)).fetchall()
            return [(r[0], abs(r[1])) for r in rows]
        except Exception:
            return []

    @staticmethod
    def _keywords(text: str) -> list[str]:
        cn = re.findall(r'[\u4e00-\u9fff]+', text)
        en = re.findall(r'[a-zA-Z0-9$¥_-]+', text)
        words = []
        for s in cn:
            if len(s) <= 4:
                words.append(s)
            else:
                for i in range(len(s) - 1): words.append(s[i:i+2])
                for i in range(len(s) - 2): words.append(s[i:i+3])
        stops = {"什么","怎么","哪个","哪些","有没有","帮我","请问","一下","可以","能否",
                 "这个","那个","就是","不是","怎么样","多少","现在","上次","之前","所有","相关","什么时"}
        return list(set(w for w in words + en if w not in stops and len(w) >= 2))


# ═══════════════════════════════════════════════════════════
# 方案 B: 腾讯 VDB + doubao Embedding
# ═══════════════════════════════════════════════════════════

class VDBEngine:
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
        self._embedding.embed_query("warmup")

    def write(self, turns: list[dict]):
        """写入 VDB"""
        records = []
        for turn in turns:
            tid = turn["turn_id"]
            text = build_embed_text(turn)
            vec = self._embedding.embed_query(text)
            bm25_text = f"{turn['user_query']} {turn['answer_preview']}"[:800]
            records.append({
                "id": f"eval_archive_turn_{tid}",
                "vector": vec,
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
                "keywords_json": turn.get("keywords", ""),
            })
        self._vdb.upsert(records)
        logger.info("[VDB] Written %d turns", len(turns))

    def search(self, query: str, top_k: int = _TOP_K) -> tuple[list[int], float]:
        t0 = time.time()
        query_vec = self._embedding.embed_query(query)
        filter_expr = 'thread_id = "eval_session_001"'
        results = self._vdb.hybrid_search(
            vector=query_vec, query_text=query,
            top_k=top_k * 3, filter_expr=filter_expr,
            dense_weight=0.6, sparse_weight=0.4,
        )
        hit_turns = []
        for r in results[:top_k]:
            try:
                hit_turns.append(int(r.get("turn_id", 0)))
            except (ValueError, TypeError):
                pass
        ms = (time.time() - t0) * 1000
        return hit_turns, ms


# ═══════════════════════════════════════════════════════════
# 评判逻辑（两方案统一）
# ═══════════════════════════════════════════════════════════

def evaluate(hits: list[int], case: Case) -> tuple[bool, float]:
    """统一评判，返回 (passed, recall)"""
    if case.expect_no_hit:
        passed = not any(t in (case.expected_turns or []) for t in hits)
        return passed, 1.0 if passed else 0.0

    if not case.expected_turns:
        passed = len(hits) > 0
        return passed, 1.0 if passed else 0.0

    exp = set(case.expected_turns)
    hit = set(hits)
    recall = len(exp & hit) / max(len(exp), 1)
    passed = recall >= 0.3
    return passed, recall


# ═══════════════════════════════════════════════════════════
# 评测执行
# ═══════════════════════════════════════════════════════════

def run_eval(engine, cases: list[Case], label: str) -> dict:
    results = []
    all_recall, all_ms = [], []

    for i, case in enumerate(cases):
        if i % 30 == 0:
            logger.info("[%s] Progress: %d/%d", label, i, len(cases))
        hits, ms = engine.search(case.query, top_k=_TOP_K)
        passed, recall = evaluate(hits, case)
        all_recall.append(recall)
        all_ms.append(ms)
        results.append({
            "id": case.id, "cat": case.category, "query": case.query,
            "passed": passed, "recall": recall, "ms": ms,
            "expected": case.expected_turns, "hit": hits,
        })

    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    sorted_ms = sorted(all_ms)
    cats = {}
    for r in results:
        cats.setdefault(r["cat"], []).append(r)

    return {
        "total": total,
        "passed": passed_count,
        "pass_rate": round(passed_count / total, 4),
        "avg_recall": round(sum(all_recall) / total, 4),
        "p50_ms": round(sorted_ms[total // 2], 1),
        "p95_ms": round(sorted_ms[int(total * 0.95)], 1),
        "avg_ms": round(sum(all_ms) / total, 1),
        "by_category": {
            cat: {"total": len(rs), "passed": sum(1 for r in rs if r["passed"]),
                  "rate": round(sum(1 for r in rs if r["passed"]) / len(rs), 4)}
            for cat, rs in cats.items()
        },
        "results": results,
    }


# ═══════════════════════════════════════════════════════════
# 报告输出
# ═══════════════════════════════════════════════════════════

def print_report(local_eval: dict, vdb_eval: dict):
    print(f"\n{'═'*72}")
    print(f"  检索准确率对比 — SQLite+HNSW+Qwen3 vs 腾讯VDB+doubao")
    print(f"  数据: 30 轮 CRM 对话 | 用例: {local_eval['total']} 条 | top_k=5 | 无 LLM")
    print(f"{'═'*72}")

    # 总体
    print(f"\n── 总体指标 ──────────────────────────────────────────")
    print(f"  ┌────────────────────┬──────────────┬──────────────┐")
    print(f"  │ 指标               │ SQLite+HNSW  │ 腾讯 VDB     │")
    print(f"  ├────────────────────┼──────────────┼──────────────┤")
    print(f"  │ 通过率             │ {local_eval['pass_rate']*100:>6.1f}%     │ {vdb_eval['pass_rate']*100:>6.1f}%     │")
    print(f"  │ 平均召回率         │ {local_eval['avg_recall']*100:>6.1f}%     │ {vdb_eval['avg_recall']*100:>6.1f}%     │")
    print(f"  │ 检索延迟 P50       │ {local_eval['p50_ms']:>6.1f}ms     │ {vdb_eval['p50_ms']:>6.1f}ms     │")
    print(f"  │ 检索延迟 P95       │ {local_eval['p95_ms']:>6.1f}ms     │ {vdb_eval['p95_ms']:>6.1f}ms     │")
    print(f"  │ 检索延迟 Avg       │ {local_eval['avg_ms']:>6.1f}ms     │ {vdb_eval['avg_ms']:>6.1f}ms     │")
    print(f"  └────────────────────┴──────────────┴──────────────┘")

    # 按分类
    print(f"\n── 按分类对比 ────────────────────────────────────────")
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

    # 失败分析
    local_fails = set(r["id"] for r in local_eval["results"] if not r["passed"])
    vdb_fails = set(r["id"] for r in vdb_eval["results"] if not r["passed"])
    only_local = local_fails - vdb_fails
    only_vdb = vdb_fails - local_fails
    both = local_fails & vdb_fails

    print(f"\n── 失败分析 ──────────────────────────────────────────")
    print(f"  仅 Local 失败: {len(only_local)} 条")
    print(f"  仅 VDB 失败:   {len(only_vdb)} 条")
    print(f"  两者都失败:    {len(both)} 条")

    if only_local:
        print(f"\n  仅 Local 失败:")
        for fid in sorted(only_local)[:8]:
            r = next(r for r in local_eval["results"] if r["id"] == fid)
            print(f"    {fid} [{r['cat']}] {r['query'][:35]}")
            print(f"      期望:{r['expected'][:5]} 命中:{r['hit']}")

    if only_vdb:
        print(f"\n  仅 VDB 失败:")
        for fid in sorted(only_vdb)[:8]:
            r = next(r for r in vdb_eval["results"] if r["id"] == fid)
            print(f"    {fid} [{r['cat']}] {r['query'][:35]}")
            print(f"      期望:{r['expected'][:5]} 命中:{r['hit']}")

    if both:
        print(f"\n  两者都失败:")
        for fid in sorted(both)[:5]:
            rl = next(r for r in local_eval["results"] if r["id"] == fid)
            rv = next(r for r in vdb_eval["results"] if r["id"] == fid)
            print(f"    {fid} [{rl['cat']}] {rl['query'][:35]}")
            print(f"      Local命中:{rl['hit']} | VDB命中:{rv['hit']}")

    print(f"\n{'═'*72}\n")


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

def main():
    seed_data = build_seed_conversation_data()
    cases = [c for c in _load_cases() if c.mode != "full"]
    logger.info("Data: %d turns | Cases: %d", len(seed_data), len(cases))

    print(f"\n🚀 检索准确率对比 Benchmark")
    print(f"   数据: {len(seed_data)} 轮 CRM 对话")
    print(f"   用例: {len(cases)} 条 (无 LLM, 纯向量+关键词)")
    print(f"   评判: recall@5 >= 0.3 视为通过\n")

    # Phase 1: 数据写入
    print(f"{'─'*72}")
    print(f"  Phase 1: 数据初始化")
    print(f"{'─'*72}\n")

    logger.info("=== 初始化 Local Engine ===")
    local_engine = LocalEngine()
    t0 = time.time()
    local_engine.write(seed_data)
    print(f"  [SQLite+HNSW] 写入 {len(seed_data)} 条: {(time.time()-t0)*1000:.0f}ms")

    logger.info("=== 初始化 VDB Engine ===")
    vdb_engine = VDBEngine()
    t0 = time.time()
    vdb_engine.write(seed_data)
    print(f"  [腾讯 VDB]    写入 {len(seed_data)} 条: {(time.time()-t0)*1000:.0f}ms")

    # 验证写入
    print(f"\n  写入验证:")
    l_test, _ = local_engine.search("PT Sentosa", top_k=3)
    v_test, _ = vdb_engine.search("PT Sentosa", top_k=3)
    print(f"    Local 检索 'PT Sentosa': {l_test}")
    print(f"    VDB   检索 'PT Sentosa': {v_test}")

    # Phase 2: 检索评测
    print(f"\n{'─'*72}")
    print(f"  Phase 2: 检索评测 ({len(cases)} 条用例)")
    print(f"{'─'*72}\n")

    logger.info("=== Running Local Eval ===")
    t0 = time.time()
    local_eval = run_eval(local_engine, cases, "Local")
    local_total_s = time.time() - t0
    print(f"  [Local] 完成: {local_total_s:.1f}s, 通过率={local_eval['pass_rate']*100:.1f}%")

    logger.info("=== Running VDB Eval ===")
    t0 = time.time()
    vdb_eval = run_eval(vdb_engine, cases, "VDB")
    vdb_total_s = time.time() - t0
    print(f"  [VDB]   完成: {vdb_total_s:.1f}s, 通过率={vdb_eval['pass_rate']*100:.1f}%")

    # Phase 3: 报告
    print_report(local_eval, vdb_eval)

    # 保存
    output = {
        "config": {"seed_count": len(seed_data), "case_count": len(cases), "top_k": _TOP_K,
                   "local_model": "Qwen3-Embedding-0.6B", "remote_model": "doubao-embedding-text-240715"},
        "local": {k: v for k, v in local_eval.items() if k != "results"},
        "vdb": {k: v for k, v in vdb_eval.items() if k != "results"},
        "diff": {
            "only_local_fail": sorted(set(r["id"] for r in local_eval["results"] if not r["passed"]) -
                                      set(r["id"] for r in vdb_eval["results"] if not r["passed"])),
            "only_vdb_fail": sorted(set(r["id"] for r in vdb_eval["results"] if not r["passed"]) -
                                    set(r["id"] for r in local_eval["results"] if not r["passed"])),
            "both_fail": sorted(set(r["id"] for r in local_eval["results"] if not r["passed"]) &
                                set(r["id"] for r in vdb_eval["results"] if not r["passed"])),
        },
    }
    out_path = "data/eval/runs/recall_benchmark.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(output, fp, ensure_ascii=False, indent=2)
    print(f"  📊 详细数据: {out_path}\n")


if __name__ == "__main__":
    main()
