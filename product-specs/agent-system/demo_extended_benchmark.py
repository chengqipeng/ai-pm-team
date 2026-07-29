"""扩展场景对比 — 15 客户 70 轮 + 400 用例 三方案对比

SQLite+HNSW+Qwen3 vs grep jieba+字段加权 vs VDB+Qwen3

运行：python demo_extended_benchmark.py
"""
from __future__ import annotations
import json, logging, os, re, sqlite3, sys, time
from dataclasses import dataclass, field
import numpy as np
import jieba
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()
jieba.initialize()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

_TOP_K = 5
_RRF_K = 60
_HNSW_M, _HNSW_EF_C, _HNSW_EF_S = 16, 200, 100
_STOPS = frozenset("的 了 在 是 我 有 和 就 不 人 都 一 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这 他 她 它 们 那 些 什么 怎么 哪个 哪些 为什么 可以 能 吗 呢 吧 啊 帮 帮我 一下 把 被 让 给 从 对 但 而 如果 因为 所以 然后 还 又 再 已经 做 多少 现在 上次 之前 所有 相关 有没有 是否 需要 请问 能否 还是 以及 这个 那个 就是 不是 怎么样 到底".split())

from eval_extended_data import build_extended_seed, build_extended_cases, Case

def build_text(t): return (f"{t['user_query']} {t['answer_preview']} {t['entities_text']} {t['keywords']} {t.get('tool_names','')} {t.get('biz_object','')}").lower()

# ════ 方案 A: SQLite+HNSW+Qwen3 ════
class LocalEngine:
    def __init__(self):
        from src.embedding import LocalEmbedding
        self._emb = LocalEmbedding()
        self._conn = sqlite3.connect(":memory:")
        self._hnsw = None
        self._id_map = {}
        self._conn.executescript("CREATE TABLE t(tid INT PRIMARY KEY, text TEXT); CREATE VIRTUAL TABLE fts USING fts5(text, content='t', content_rowid='tid', tokenize='unicode61'); CREATE TRIGGER ti AFTER INSERT ON t BEGIN INSERT INTO fts(rowid, text) VALUES(new.tid, new.text); END;")

    def write(self, turns):
        texts = [build_text(t) for t in turns]
        vecs = self._emb.embed_documents_np(texts)
        for i, t in enumerate(turns):
            self._conn.execute("INSERT INTO t VALUES(?,?)", (t["turn_id"], texts[i]))
        self._conn.commit()
        import hnswlib
        self._hnsw = hnswlib.Index(space="cosine", dim=vecs.shape[1])
        self._hnsw.init_index(max_elements=len(turns)*2, ef_construction=_HNSW_EF_C, M=_HNSW_M)
        self._hnsw.set_ef(_HNSW_EF_S)
        self._hnsw.add_items(vecs, list(range(len(turns))))
        for i, t in enumerate(turns): self._id_map[i] = t["turn_id"]

    def search(self, query, top_k=_TOP_K):
        t0 = time.time()
        qv = self._emb.embed_query_np(query)
        labels, dists = self._hnsw.knn_query(np.array([qv], dtype=np.float32), k=min(top_k*3, len(self._id_map)))
        dense = [(self._id_map[int(l)], 1.0-d) for l, d in zip(labels[0], dists[0])]
        kws = [w for w in jieba.cut(query.lower()) if w not in _STOPS and len(w)>=2]
        kws += re.findall(r'[a-zA-Z0-9$¥_-]+', query.lower())
        kws = list(set(w for w in kws if len(w)>=2))
        sparse = []
        if kws:
            fts_q = " OR ".join(f'"{w}"' for w in kws[:15])
            try:
                rows = self._conn.execute("SELECT t.tid, rank FROM fts JOIN t ON fts.rowid=t.tid WHERE fts MATCH ? ORDER BY rank LIMIT ?", (fts_q, top_k*3)).fetchall()
                sparse = [(r[0], abs(r[1])) for r in rows]
            except: pass
        scores = {}
        for rank, (tid, _) in enumerate(dense, 1): scores[tid] = scores.get(tid, 0) + 1.0/(_RRF_K+rank)
        for rank, (tid, _) in enumerate(sparse, 1): scores[tid] = scores.get(tid, 0) + 1.0/(_RRF_K+rank)
        result = sorted(scores, key=lambda t: -scores[t])[:top_k]
        return result, (time.time()-t0)*1000

# ════ 方案 B: grep jieba + 字段加权 ════
class GrepEngine:
    def __init__(self):
        self._fields = {}

    def write(self, turns):
        for t in turns:
            self._fields[t["turn_id"]] = {
                "entities": t["entities_text"].lower(),
                "user_query": t["user_query"].lower(),
                "keywords": t["keywords"].lower(),
                "tools": t.get("tool_names", "").lower(),
                "biz": t.get("biz_object", "").lower(),
                "answer": t["answer_preview"].lower(),
            }

    def search(self, query, top_k=_TOP_K):
        t0 = time.time()
        kws = [w for w in jieba.cut(query.lower()) if w not in _STOPS and len(w)>=2]
        kws += re.findall(r'[a-zA-Z0-9$¥_-]+', query.lower())
        kws = list(set(w for w in kws if len(w)>=2))
        scored = []
        for tid, f in self._fields.items():
            score = 0
            for kw in kws:
                if kw in f["entities"]: score += 3
                if kw in f["user_query"]: score += 2
                if kw in f["keywords"]: score += 2
                if kw in f["tools"]: score += 2
                if kw in f["biz"]: score += 2
                if kw in f["answer"]: score += 1
            if score > 0: scored.append((tid, score))
        scored.sort(key=lambda x: -x[1])
        return [tid for tid, _ in scored[:top_k]], (time.time()-t0)*1000

# ════ 评测 ════
def evaluate(hits, case):
    if case.expect_no_hit:
        return not any(t in (case.expected_turns or []) for t in hits), 1.0 if not hits else 0.0
    if not case.expected_turns: return len(hits) > 0, 1.0 if hits else 0.0
    exp, hit = set(case.expected_turns), set(hits)
    recall = len(exp & hit) / max(len(exp), 1)
    return recall >= 0.3, recall

def run_eval(engine, cases, label):
    results, all_recall, all_ms = [], [], []
    for i, c in enumerate(cases):
        if i % 80 == 0: logger.info("[%s] %d/%d", label, i, len(cases))
        hits, ms = engine.search(c.query, _TOP_K)
        passed, recall = evaluate(hits, c)
        all_recall.append(recall); all_ms.append(ms)
        results.append({"id": c.id, "cat": c.category, "passed": passed, "recall": recall})
    total = len(results)
    cats = {}
    for r in results: cats.setdefault(r["cat"], []).append(r)
    return {"total": total, "passed": sum(1 for r in results if r["passed"]),
            "pass_rate": sum(1 for r in results if r["passed"]) / total,
            "avg_recall": sum(all_recall) / total,
            "p50_ms": sorted(all_ms)[total//2], "avg_ms": sum(all_ms)/total,
            "by_category": {cat: round(sum(1 for r in rs if r["passed"])/len(rs)*100, 1) for cat, rs in cats.items()}}

# ════ Main ════
def main():
    seed = build_extended_seed()
    cases = build_extended_cases()
    logger.info("Data: %d turns | Cases: %d", len(seed), len(cases))

    print(f"\n🚀 扩展场景对比 — {len(seed)} 轮数据 × {len(cases)} 条用例")
    print(f"   15 客户 | 干扰区分 + 意图推理 + 否定排除 + 多跳推理 + 长尾定位\n")

    # 方案 A
    logger.info("=== SQLite+HNSW+Qwen3 ===")
    local = LocalEngine()
    local.write(seed)

    # 方案 B
    logger.info("=== grep jieba ===")
    grep = GrepEngine()
    grep.write(seed)

    # 评测
    logger.info("=== Eval Local ===")
    local_r = run_eval(local, cases, "Local")
    logger.info("=== Eval grep ===")
    grep_r = run_eval(grep, cases, "grep")

    # 报告
    print(f"\n{'═'*68}")
    print(f"  扩展验证 — {len(seed)} 轮 × {len(cases)} 用例")
    print(f"{'═'*68}")
    print(f"\n  ┌────────────────────────────┬──────────┬──────────┐")
    print(f"  │ 指标                       │ HNSW+Qwen│ grep+jieba│")
    print(f"  ├────────────────────────────┼──────────┼──────────┤")
    print(f"  │ 通过率                     │ {local_r['pass_rate']*100:>5.1f}%  │ {grep_r['pass_rate']*100:>5.1f}%  │")
    print(f"  │ 平均召回率                 │ {local_r['avg_recall']*100:>5.1f}%  │ {grep_r['avg_recall']*100:>5.1f}%  │")
    print(f"  │ P50 延迟                   │ {local_r['p50_ms']:>5.1f}ms │ {grep_r['p50_ms']:>5.2f}ms │")
    print(f"  └────────────────────────────┴──────────┴──────────┘")

    print(f"\n  按分类:")
    print(f"  {'分类':<10} {'HNSW':>8} {'grep':>8} {'差异':>8}")
    print(f"  {'─'*40}")
    all_cats = sorted(set(list(local_r["by_category"].keys()) + list(grep_r["by_category"].keys())))
    for cat in all_cats:
        l = local_r["by_category"].get(cat, 0)
        g = grep_r["by_category"].get(cat, 0)
        icon = "✅" if l-g >= 0 else "❌"
        print(f"  {icon} {cat:<9} {l:>6.1f}% {g:>6.1f}% {l-g:>+6.1f}%")

    print(f"\n{'═'*68}\n")

    out = "data/eval/runs/extended_benchmark.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fp:
        json.dump({"local": local_r, "grep": grep_r, "data_turns": len(seed), "cases": len(cases)}, fp, ensure_ascii=False, indent=2)
    print(f"  📊 保存: {out}")

if __name__ == "__main__":
    main()
