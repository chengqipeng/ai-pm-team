"""上下文存档检索 — 本地 Embedding + SQLite + HNSW 验证

使用 Qwen3-Embedding-0.6B 本地推理（MPS/CPU），零网络依赖。
验证纯本地方案在上下文存档检索场景的效果和延迟。

运行：python eval_archive_local_embed.py
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field

import numpy as np
import torch

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

_MODEL_PATH = os.path.expanduser("~/models/Qwen3-Embedding-0.6B")
_DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
_HNSW_M = 16
_HNSW_EF_CONSTRUCTION = 200
_HNSW_EF_SEARCH = 100
_RRF_K = 60
_SEARCH_TOP_K = 5


# ═══════════════════════════════════════════════════════════
# 本地 Embedding
# ═══════════════════════════════════════════════════════════

class LocalEmbedding:
    """Qwen3-Embedding-0.6B 本地推理"""

    def __init__(self):
        from sentence_transformers import SentenceTransformer
        logger.info("Loading Qwen3-Embedding-0.6B on %s...", _DEVICE)
        t0 = time.time()
        self._model = SentenceTransformer(
            _MODEL_PATH,
            device=_DEVICE,
            trust_remote_code=True,
        )
        logger.info("Model loaded in %.1fs", time.time() - t0)
        # Warmup
        self._model.encode(["warmup"], normalize_embeddings=True)
        logger.info("Warmup done. Ready.")

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """批量 embedding"""
        if not texts:
            return np.array([])
        return self._model.encode(
            texts, normalize_embeddings=True,
            batch_size=32, show_progress_bar=False,
        )

    def embed_query(self, query: str) -> np.ndarray:
        """单条 query embedding（带 instruction prefix）"""
        # Qwen3-Embedding 支持 instruction-aware embedding
        prefixed = f"Instruct: Retrieve relevant conversation context\nQuery: {query}"
        return self._model.encode(
            [prefixed], normalize_embeddings=True,
            show_progress_bar=False,
        )[0]


# ═══════════════════════════════════════════════════════════
# SQLite + HNSW 引擎
# ═══════════════════════════════════════════════════════════

class LocalArchiveEngine:
    """纯本地：SQLite FTS5 + hnswlib + Qwen3-Embedding-0.6B"""

    def __init__(self, embedding: LocalEmbedding):
        self._conn = sqlite3.connect(":memory:")
        self._embedding = embedding
        self._hnsw_index = None
        self._id_map: dict[int, int] = {}
        self._turns: dict[int, dict] = {}
        self._setup_db()

    def _setup_db(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS archive_turns (
                turn_id INTEGER PRIMARY KEY,
                user_query TEXT,
                answer_preview TEXT,
                entities_text TEXT,
                tool_names TEXT,
                keywords TEXT,
                biz_object TEXT,
                action_subtype TEXT
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS archive_fts USING fts5(
                user_query, answer_preview, entities_text, tool_names, keywords, biz_object,
                content='archive_turns', content_rowid='turn_id',
                tokenize='unicode61'
            );
            CREATE TRIGGER IF NOT EXISTS archive_ai AFTER INSERT ON archive_turns BEGIN
                INSERT INTO archive_fts(rowid, user_query, answer_preview, entities_text, tool_names, keywords, biz_object)
                VALUES (new.turn_id, new.user_query, new.answer_preview, new.entities_text, new.tool_names, new.keywords, new.biz_object);
            END;
        """)

    def seed(self, turns: list[dict]):
        """写入种子数据 + 构建索引"""
        logger.info("Seeding %d archive turns...", len(turns))

        texts_to_embed = []
        turn_ids_ordered = []

        for turn in turns:
            tid = turn["turn_id"]
            self._conn.execute(
                "INSERT OR REPLACE INTO archive_turns VALUES (?,?,?,?,?,?,?,?)",
                (tid, turn["user_query"], turn["answer_preview"],
                 turn["entities_text"], turn.get("tool_names", ""),
                 turn["keywords"], turn.get("biz_object", ""),
                 turn.get("action_subtype", "")),
            )
            self._turns[tid] = turn
            # 构造 embedding 文本
            embed_text = (
                f"{turn['user_query']} {turn['answer_preview']} "
                f"{turn['entities_text']} {turn['keywords']} "
                f"{turn.get('tool_names', '')} {turn.get('biz_object', '')}"
            )
            texts_to_embed.append(embed_text)
            turn_ids_ordered.append(tid)

        self._conn.commit()

        # 本地 embedding（批量）
        logger.info("Local embedding %d texts...", len(texts_to_embed))
        t0 = time.time()
        vectors = self._embedding.embed_texts(texts_to_embed)
        embed_ms = (time.time() - t0) * 1000
        logger.info("Embedding done: %.0fms (%.1fms/text)", embed_ms, embed_ms / len(texts_to_embed))

        # HNSW 索引
        import hnswlib
        dim = vectors.shape[1]
        self._hnsw_index = hnswlib.Index(space="cosine", dim=dim)
        self._hnsw_index.init_index(max_elements=len(turns) * 2, ef_construction=_HNSW_EF_CONSTRUCTION, M=_HNSW_M)
        self._hnsw_index.set_ef(_HNSW_EF_SEARCH)
        self._hnsw_index.add_items(vectors, list(range(len(turns))))

        for idx, tid in enumerate(turn_ids_ordered):
            self._id_map[idx] = tid

        logger.info("HNSW built: %d vectors, dim=%d", len(turns), dim)

    def search(self, query: str, top_k: int = _SEARCH_TOP_K) -> list[dict]:
        """混合检索：HNSW + FTS5 → RRF"""
        t0 = time.time()

        # Dense
        dense = self._search_dense(query)
        dense_ms = (time.time() - t0) * 1000

        # Sparse
        t1 = time.time()
        sparse = self._search_sparse(query)
        sparse_ms = (time.time() - t1) * 1000

        # RRF
        results = self._rrf_fuse(dense, sparse, top_k)

        total_ms = (time.time() - t0) * 1000
        return results, {"total_ms": total_ms, "dense_ms": dense_ms, "sparse_ms": sparse_ms}

    def _search_dense(self, query: str, top_k: int = 15) -> list[tuple[int, float]]:
        if not query or not query.strip():
            return []
        query_vec = self._embedding.embed_query(query)
        query_vec = np.array([query_vec], dtype=np.float32)
        k = min(top_k, self._hnsw_index.get_current_count())
        labels, distances = self._hnsw_index.knn_query(query_vec, k=k)
        return [(self._id_map.get(int(l), 0), 1.0 - d)
                for l, d in zip(labels[0], distances[0]) if self._id_map.get(int(l))]

    def _search_sparse(self, query: str, top_k: int = 15) -> list[tuple[int, float]]:
        keywords = self._extract_keywords(query)
        if not keywords:
            return []
        fts_query = " OR ".join(f'"{w}"' for w in keywords)
        try:
            rows = self._conn.execute(
                "SELECT a.turn_id, rank FROM archive_fts "
                "JOIN archive_turns a ON archive_fts.rowid = a.turn_id "
                "WHERE archive_fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, top_k),
            ).fetchall()
            return [(row[0], abs(row[1])) for row in rows]
        except Exception:
            return []

    def _rrf_fuse(self, dense: list[tuple[int, float]], sparse: list[tuple[int, float]], top_k: int) -> list[dict]:
        scores: dict[int, float] = {}
        for rank, (tid, _) in enumerate(dense, 1):
            scores[tid] = scores.get(tid, 0) + 1.0 / (_RRF_K + rank)
        for rank, (tid, _) in enumerate(sparse, 1):
            scores[tid] = scores.get(tid, 0) + 1.0 / (_RRF_K + rank)
        sorted_tids = sorted(scores.keys(), key=lambda t: -scores[t])
        results = []
        for tid in sorted_tids[:top_k]:
            turn = self._turns.get(tid, {})
            results.append({"turn_id": tid, "score": scores[tid], **turn})
        return results

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        cn_segments = re.findall(r'[\u4e00-\u9fff]+', text)
        en_words = re.findall(r'[a-zA-Z0-9$¥]+', text)
        cn_words = []
        for seg in cn_segments:
            if len(seg) <= 4:
                cn_words.append(seg)
            else:
                for i in range(len(seg) - 1):
                    cn_words.append(seg[i:i + 2])
                for i in range(len(seg) - 2):
                    cn_words.append(seg[i:i + 3])
        stopwords = {"什么", "怎么", "哪个", "哪些", "有没有", "是否", "需要",
                     "帮我", "请问", "一下", "可以", "能否", "还是", "以及",
                     "这个", "那个", "就是", "不是", "的是", "们的", "怎么样",
                     "多少", "到底", "现在", "上次", "之前"}
        return list(set(w for w in cn_words + en_words if w not in stopwords and len(w) >= 2))


# ═══════════════════════════════════════════════════════════
# 规则代词消解（零 LLM）
# ═══════════════════════════════════════════════════════════

def rule_based_rewrite(query: str, active_entities: list[str]) -> str:
    """纯规则代词消解 + 同义词扩展"""
    pronouns = ['他们', '她们', '对方', '那个客户', '这个客户', '该客户',
                '那家公司', '这家公司', '那边', '它的', '它']
    rewritten = query
    if active_entities:
        for p in pronouns:
            if p in rewritten:
                rewritten = rewritten.replace(p, active_entities[0], 1)
                break

    # 同义词扩展
    expansions = {
        '谈判': ' negotiation 谈判阶段',
        '竞品': ' Odoo SAP Salesforce 竞品对比 搜索',
        '签约': ' closed 成交 签合同',
        '技术评估': ' POC 技术方案 评审',
        '报价': ' 报价 quote 金额',
    }
    for term, expansion in expansions.items():
        if term in rewritten:
            rewritten += expansion
    return rewritten


# ═══════════════════════════════════════════════════════════
# 评测
# ═══════════════════════════════════════════════════════════

@dataclass
class EvalResult:
    case_id: str
    category: str
    query: str
    passed: bool
    recall_at_k: float = 0.0
    hit_turns: list[int] = field(default_factory=list)
    expected_turns: list[int] = field(default_factory=list)
    search_ms: float = 0.0


@dataclass
class EvalReport:
    total: int = 0
    passed: int = 0
    failed: int = 0
    avg_recall: float = 0.0
    avg_search_ms: float = 0.0
    duration_ms: float = 0.0
    by_category: dict[str, dict] = field(default_factory=dict)
    results: list[EvalResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passed / max(self.total, 1)


def run_eval():
    from src.eval.archive_recall_eval_runner import build_seed_conversation_data
    from src.eval.archive_recall_eval_cases import build_archive_recall_cases

    # 初始化
    embedding = LocalEmbedding()
    engine = LocalArchiveEngine(embedding=embedding)

    # 种子数据
    seed_data = build_seed_conversation_data()
    engine.seed(seed_data)

    # 评测用例
    cases = build_archive_recall_cases()
    recall_cases = [c for c in cases if c.expect_hit_turns or c.expect_no_hit]
    logger.info("Loaded %d recall cases", len(recall_cases))

    # 运行
    report = EvalReport(total=len(recall_cases))
    all_recalls = []
    all_search_ms = []
    start = time.time()

    for i, case in enumerate(recall_cases):
        if i % 30 == 0:
            logger.info("Progress: %d/%d", i, len(recall_cases))

        # 规则改写（零 LLM）
        rewritten = rule_based_rewrite(case.query, case.active_entities)

        # 检索
        hits, timing = engine.search(rewritten, top_k=_SEARCH_TOP_K)
        hit_turn_ids = [h["turn_id"] for h in hits]
        search_ms = timing["total_ms"]
        all_search_ms.append(search_ms)

        # 评估
        if case.expect_no_hit:
            passed = not any(t in (case.expect_hit_turns or []) for t in hit_turn_ids)
            recall = 1.0 if passed else 0.0
        else:
            exp_set = set(case.expect_hit_turns)
            hit_set = set(hit_turn_ids)
            recall = len(exp_set & hit_set) / max(len(exp_set), 1)
            passed = recall >= 0.3

        all_recalls.append(recall)

        result = EvalResult(
            case_id=case.id, category=case.category, query=case.query,
            passed=passed, recall_at_k=recall,
            hit_turns=hit_turn_ids[:5], expected_turns=case.expect_hit_turns,
            search_ms=search_ms,
        )
        report.results.append(result)
        if passed:
            report.passed += 1
        else:
            report.failed += 1

        cat = case.category
        if cat not in report.by_category:
            report.by_category[cat] = {"total": 0, "passed": 0, "failed": 0}
        report.by_category[cat]["total"] += 1
        if passed:
            report.by_category[cat]["passed"] += 1
        else:
            report.by_category[cat]["failed"] += 1

    report.duration_ms = (time.time() - start) * 1000
    n = max(len(all_recalls), 1)
    report.avg_recall = sum(all_recalls) / n
    report.avg_search_ms = sum(all_search_ms) / n

    return report


def print_report(report: EvalReport):
    print("\n" + "═" * 64)
    print("  上下文存档检索 — 本地 Embedding + SQLite + HNSW")
    print("  模型: Qwen3-Embedding-0.6B (本地 MPS/CPU)")
    print("  零网络依赖 · 零 LLM 调用 · 纯本地计算")
    print("═" * 64)

    print(f"\n  总用例: {report.total}")
    print(f"  通过:   {report.passed} ({report.pass_rate:.1%})")
    print(f"  失败:   {report.failed}")
    print(f"  总耗时: {report.duration_ms:.0f}ms")
    print(f"  平均单次检索: {report.avg_search_ms:.1f}ms")

    print(f"\n── 聚合指标 ──────────────────────────────────────────")
    print(f"  平均召回率: {report.avg_recall:.1%}")

    print(f"\n── 按分类 ────────────────────────────────────────────")
    for cat, stats in sorted(report.by_category.items()):
        rate = stats["passed"] / max(stats["total"], 1) * 100
        icon = "✅" if rate >= 80 else ("⚠️" if rate >= 50 else "❌")
        print(f"  {icon} {cat:<8} {rate:>5.1f}%   {stats['passed']}/{stats['total']}")

    print(f"\n── 方案对比 ──────────────────────────────────────────")
    print(f"  ┌────────────────────────────┬────────┬──────────┬────────────────┐")
    print(f"  │ 方案                       │ 通过率 │ 平均召回 │ 单次检索延迟   │")
    print(f"  ├────────────────────────────┼────────┼──────────┼────────────────┤")
    print(f"  │ PG ILIKE 降级              │  56%   │   53%    │ ~100ms         │")
    print(f"  │ SQLite+HNSW+doubao (API)   │  94.5% │   86.3%  │ ~70-120ms      │")
    print(f"  │ SQLite+HNSW+Qwen3 (本地)   │ {report.pass_rate*100:>4.1f}% │  {report.avg_recall*100:>4.1f}%  │ {report.avg_search_ms:>5.1f}ms        │")
    print(f"  │ VDB 预估                   │ 75-78% │    —     │ ~80-150ms      │")
    print(f"  └────────────────────────────┴────────┴──────────┴────────────────┘")

    # 失败用例
    failures = [r for r in report.results if not r.passed]
    if failures:
        print(f"\n── 失败用例 (前 10 条) ──────────────────────────────")
        for f in failures[:10]:
            print(f"  ❌ [{f.category}] {f.query[:40]}")
            print(f"     期望: {f.expected_turns[:5]} | 命中: {f.hit_turns[:5]} | {f.search_ms:.1f}ms")

    # 延迟分布
    search_times = [r.search_ms for r in report.results]
    if search_times:
        search_times.sort()
        p50 = search_times[len(search_times) // 2]
        p95 = search_times[int(len(search_times) * 0.95)]
        p99 = search_times[int(len(search_times) * 0.99)]
        print(f"\n── 延迟分布 ──────────────────────────────────────────")
        print(f"  P50: {p50:.1f}ms  |  P95: {p95:.1f}ms  |  P99: {p99:.1f}ms")
        print(f"  Min: {min(search_times):.1f}ms  |  Max: {max(search_times):.1f}ms")

    # 保存
    output_path = "data/eval/runs/archive_local_embed.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump({
            "model": "Qwen3-Embedding-0.6B",
            "device": _DEVICE,
            "total": report.total, "passed": report.passed, "failed": report.failed,
            "pass_rate": round(report.pass_rate, 4),
            "avg_recall": round(report.avg_recall, 4),
            "avg_search_ms": round(report.avg_search_ms, 2),
            "total_duration_ms": round(report.duration_ms, 1),
            "by_category": report.by_category,
            "latency_p50_ms": round(search_times[len(search_times) // 2], 2) if search_times else 0,
            "latency_p95_ms": round(search_times[int(len(search_times) * 0.95)], 2) if search_times else 0,
            "results": [
                {"case_id": r.case_id, "category": r.category, "query": r.query,
                 "passed": r.passed, "recall": round(r.recall_at_k, 4),
                 "expected": r.expected_turns, "hit": r.hit_turns[:5],
                 "search_ms": round(r.search_ms, 2)}
                for r in report.results
            ],
        }, fp, ensure_ascii=False, indent=2)
    print(f"\n  📊 详细结果已保存: {output_path}")


if __name__ == "__main__":
    print("🚀 启动本地 Embedding + SQLite + HNSW 验证")
    print(f"   模型: Qwen3-Embedding-0.6B")
    print(f"   设备: {_DEVICE}")
    print(f"   方案: 纯本地（零网络 · 零 LLM）\n")

    report = run_eval()
    print_report(report)
