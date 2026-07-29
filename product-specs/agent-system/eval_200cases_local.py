"""ContextArchive 200 场景 — 本地 Qwen3 + SQLite + HNSW 对照评测

复用 tests/test_context_archive_200cases.py 的 200 条用例 + 30 轮对话数据，
用纯本地方案替代 PG ILIKE，输出与原报告对齐的准确率和性能数据。

运行：python eval_200cases_local.py
"""
from __future__ import annotations

import json, logging, os, re, sqlite3, sys, time
from dataclasses import dataclass, field
import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

_MODEL_PATH = os.path.expanduser("~/models/Qwen3-Embedding-0.6B")
_DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
_HNSW_M, _HNSW_EF_C, _HNSW_EF_S = 16, 200, 100
_RRF_K = 60
_TOP_K = 5

# ═══════════════════════════════════════════════════════════
# 从 test file 复用数据（避免 mock 依赖）
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

# 直接通过 _load_cases 加载
def _load_cases():
    """通过 exec 加载 build_cases，避免 mock 问题"""
    # 手动解析文件提取 build_cases 函数体
    with open("tests/test_context_archive_200cases.py", "r") as f:
        content = f.read()
    # 找到 build_cases 定义
    start = content.index("def build_cases() -> list[Case]:")
    # 找到下一个顶级 def 或 class
    rest = content[start:]
    lines = rest.split("\n")
    func_lines = [lines[0]]
    for line in lines[1:]:
        if line and not line[0].isspace() and not line.startswith("#"):
            break
        func_lines.append(line)
    func_code = "\n".join(func_lines)
    # Execute in isolated namespace
    ns = {"Case": Case, "field": field}
    exec(func_code, ns)
    return ns["build_cases"]()

# ═══════════════════════════════════════════════════════════
# 本地 Embedding + SQLite + HNSW
# ═══════════════════════════════════════════════════════════

class LocalEmbed:
    def __init__(self):
        from sentence_transformers import SentenceTransformer
        logger.info("Loading model on %s...", _DEVICE)
        t0 = time.time()
        self._m = SentenceTransformer(_MODEL_PATH, device=_DEVICE, trust_remote_code=True)
        self._m.encode(["warmup"], normalize_embeddings=True)
        logger.info("Model ready: %.1fs", time.time() - t0)

    def embed_batch(self, texts):
        return self._m.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)

    def embed_query(self, q):
        return self._m.encode([f"Instruct: Retrieve relevant conversation context\nQuery: {q}"],
                              normalize_embeddings=True, show_progress_bar=False)[0]


class ArchiveStore:
    def __init__(self, emb: LocalEmbed):
        self._conn = sqlite3.connect(":memory:")
        self._emb = emb
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

    def seed(self, turns):
        texts = []
        tids = []
        for t in turns:
            tid = t["turn_id"]
            full = f"{t['user_query']} {t['answer_preview']} {t['entities_text']} {t['keywords']} {t.get('tool_names','')} {t.get('biz_object','')}"
            self._conn.execute("INSERT INTO turns VALUES(?,?,?,?,?,?)",
                (tid, full, t["entities_text"], t.get("tool_names",""), t["keywords"], t.get("biz_object","")))
            self._turns[tid] = t
            texts.append(full)
            tids.append(tid)
        self._conn.commit()

        logger.info("Embedding %d turns...", len(texts))
        t0 = time.time()
        vecs = self._emb.embed_batch(texts)
        logger.info("Embed done: %.0fms", (time.time()-t0)*1000)

        import hnswlib
        dim = vecs.shape[1]
        self._hnsw = hnswlib.Index(space="cosine", dim=dim)
        self._hnsw.init_index(max_elements=60, ef_construction=_HNSW_EF_C, M=_HNSW_M)
        self._hnsw.set_ef(_HNSW_EF_S)
        self._hnsw.add_items(vecs, list(range(len(tids))))
        for i, tid in enumerate(tids):
            self._id_map[i] = tid
        logger.info("Index ready: %d vecs, dim=%d", len(tids), dim)

    def search(self, query, top_k=_TOP_K):
        t0 = time.time()
        # dense
        qv = self._emb.embed_query(query)
        labels, dists = self._hnsw.knn_query(np.array([qv], dtype=np.float32), k=min(top_k*3, 30))
        dense = [(self._id_map[int(l)], 1.0-d) for l, d in zip(labels[0], dists[0])]
        # sparse
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
        sorted_t = sorted(scores, key=lambda t: -scores[t])[:top_k]
        ms = (time.time()-t0)*1000
        return sorted_t, ms

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
# 评测
# ═══════════════════════════════════════════════════════════

def main():
    emb = LocalEmbed()
    store = ArchiveStore(emb)
    seed_data = build_seed_conversation_data()
    store.seed(seed_data)

    cases = _load_cases()
    # 排除 full 模式用例（turn_id 精确查询，不涉及检索）
    eval_cases = [c for c in cases if c.mode != "full"]
    logger.info("Evaluating %d cases (excluded %d full-mode)", len(eval_cases), len(cases)-len(eval_cases))

    results = []
    all_recall, all_ms = [], []
    start = time.time()

    for i, case in enumerate(eval_cases):
        if i % 30 == 0:
            logger.info("Progress: %d/%d", i, len(eval_cases))

        hits, ms = store.search(case.query, top_k=_TOP_K)
        all_ms.append(ms)

        if case.expect_no_hit:
            passed = len(hits) == 0 or not any(t in (case.expected_turns or []) for t in hits)
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
        results.append({"id": case.id, "cat": case.category, "passed": passed,
                        "recall": recall, "query": case.query,
                        "expected": case.expected_turns, "hit": hits, "ms": ms})

    total_ms = (time.time() - start) * 1000

    # 统计
    cats = {}
    for r in results:
        cats.setdefault(r["cat"], []).append(r)

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    avg_recall = sum(all_recall) / total
    avg_ms = sum(all_ms) / total
    p50 = sorted(all_ms)[total//2]
    p95 = sorted(all_ms)[int(total*0.95)]

    # 输出
    print(f"\n{'═'*70}")
    print(f"  ContextArchive 200 场景 — 本地 Qwen3 + SQLite + HNSW")
    print(f"  模型: Qwen3-Embedding-0.6B | 设备: {_DEVICE} | 零网络/零LLM")
    print(f"{'═'*70}")
    print(f"\n  用例: {total} | 通过: {passed} ({passed/total*100:.1f}%) | 总耗时: {total_ms:.0f}ms")
    print(f"  平均召回率: {avg_recall*100:.1f}% | 平均精确率: —")
    print(f"  检索延迟 P50: {p50:.1f}ms | P95: {p95:.1f}ms | Avg: {avg_ms:.1f}ms")

    print(f"\n── 按分类对比（vs PG ILIKE 56% 基线）──────────────────")
    print(f"  {'分类':<8} {'本次':>6} {'PG基线':>6} {'提升':>6}")
    print(f"  {'─'*35}")
    pg_baseline = {"精确实体":87,"模糊语义":60,"变更追踪":40,"工具结果":65,
                   "时间线":40,"跨任务":50,"决策追踪":20,"负例":60,"时效性":40}
    for cat, cat_r in sorted(cats.items()):
        rate = sum(1 for r in cat_r if r["passed"]) / len(cat_r) * 100
        pg = pg_baseline.get(cat, 0)
        delta = f"+{rate-pg:.0f}%" if pg else "—"
        icon = "✅" if rate >= 80 else ("⚠️" if rate >= 50 else "❌")
        print(f"  {icon} {cat:<7} {rate:>5.1f}% {pg:>5}% {delta:>6}")

    print(f"\n── 总结对比 ──────────────────────────────────────────")
    print(f"  ┌───────────────────────────┬────────┬──────────┬──────────┐")
    print(f"  │ 方案                      │ 通过率 │ 平均召回 │ P50 延迟 │")
    print(f"  ├───────────────────────────┼────────┼──────────┼──────────┤")
    print(f"  │ PG ILIKE (原报告)         │  56.0% │   53.0%  │ ~100ms   │")
    print(f"  │ Qwen3+SQLite+HNSW (本次)  │ {passed/total*100:>4.1f}% │  {avg_recall*100:>4.1f}%  │ {p50:>4.1f}ms  │")
    print(f"  │ VDB 预估 (原报告)         │ 75-78% │    —     │ ~80-150ms│")
    print(f"  └───────────────────────────┴────────┴──────────┴──────────┘")

    # 失败
    failures = [r for r in results if not r["passed"]]
    if failures:
        print(f"\n── 失败用例 (前 15 条 / 共 {len(failures)} 条) ────────────────")
        for f in failures[:15]:
            print(f"  ❌ [{f['cat']}] {f['query'][:40]}")
            print(f"     期望: {f['expected'][:5]} | 命中: {f['hit'][:5]}")

    # 保存
    out = "data/eval/runs/200cases_local_embed.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fp:
        json.dump({"model":"Qwen3-Embedding-0.6B","device":_DEVICE,
                   "total":total,"passed":passed,"pass_rate":round(passed/total,4),
                   "avg_recall":round(avg_recall,4),"avg_ms":round(avg_ms,2),
                   "p50_ms":round(p50,2),"p95_ms":round(p95,2),
                   "by_category":{cat:{"total":len(rs),"passed":sum(1 for r in rs if r["passed"])}
                                  for cat,rs in cats.items()},
                   "results":results}, fp, ensure_ascii=False, indent=2)
    print(f"\n  📊 保存: {out}")


if __name__ == "__main__":
    main()
