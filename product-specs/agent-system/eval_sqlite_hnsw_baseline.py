"""SQLite + HNSW 向量检索 Baseline 对照实验

目的：对比当前 VikingMemoryEngine（腾讯VDB + BM25+向量递归）与
      Headroom 风格的 SQLite + HNSW 方案的检索准确率差异。

方案：
  - SQLite FTS5 做 BM25 稀疏检索
  - hnswlib 做稠密向量 ANN 检索
  - 双路融合（可调权重）
  - 使用相同的种子数据 + 相同的 200 条评测用例
  - 无 LLM Query Rewrite、无 Rerank、无目录递归（模拟 Headroom 的极简方案）

依赖：
  pip install hnswlib numpy openai langchain-openai

运行：
  python eval_sqlite_hnsw_baseline.py
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

# Embedding 配置（与现有系统一致用 doubao）
_EMBED_MODEL = os.environ.get("EMBEDDING_MODEL", "doubao-embedding-text-240715")
_EMBED_API_KEY = os.environ.get("EMBEDDING_API_KEY") or os.environ.get(
    "DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1"
)
_EMBED_API_BASE = os.environ.get(
    "EMBEDDING_API_BASE", "https://ark.cn-beijing.volces.com/api/v3/"
)
_EMBED_DIM = 2560  # doubao-embedding-text-240715 维度

# HNSW 参数
_HNSW_M = 16
_HNSW_EF_CONSTRUCTION = 200
_HNSW_EF_SEARCH = 100

# 融合权重（与 Headroom 保持一致：简单双路加权）
_DENSE_WEIGHT = 0.5
_SPARSE_WEIGHT = 0.5

# 检索 Top-K
_SEARCH_TOP_K = 5


# ═══════════════════════════════════════════════════════════
# Embedding 客户端
# ═══════════════════════════════════════════════════════════

class EmbeddingClient:
    """OpenAI-compatible Embedding API 客户端"""

    def __init__(self):
        from langchain_openai import OpenAIEmbeddings
        self._model = OpenAIEmbeddings(
            model=_EMBED_MODEL,
            api_key=_EMBED_API_KEY,
            base_url=_EMBED_API_BASE,
            check_embedding_ctx_length=False,
        )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._model.embed_documents(texts)

    def embed_query(self, query: str) -> list[float]:
        return self._model.embed_query(query)


# ═══════════════════════════════════════════════════════════
# SQLite + HNSW 记忆存储引擎
# ═══════════════════════════════════════════════════════════

class SQLiteHNSWMemoryStore:
    """SQLite FTS5 + hnswlib — 模拟 Headroom 的本地极简记忆方案

    设计：
      - SQLite 存储记忆元数据 + FTS5 全文索引
      - hnswlib 存储向量索引
      - 检索时双路召回 → 分数归一化 → 加权融合
      - 无 LLM Query Rewrite
      - 无目录递归
      - 无 Rerank
    """

    def __init__(self, db_path: str = ":memory:", embedding_client: EmbeddingClient = None):
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._embedding = embedding_client
        self._hnsw_index = None
        self._id_map: dict[int, str] = {}  # hnsw_idx → merge_key
        self._memories: dict[str, dict] = {}  # merge_key → memory
        self._setup_db()

    def _setup_db(self):
        """建表 + FTS5 索引"""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                merge_key TEXT UNIQUE NOT NULL,
                category TEXT DEFAULT 'entities',
                parent_entity TEXT DEFAULT '',
                abstract TEXT DEFAULT '',
                content TEXT DEFAULT '',
                created_at REAL DEFAULT 0
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                merge_key, abstract, content,
                content='memories',
                content_rowid='id',
                tokenize='unicode61'
            );

            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, merge_key, abstract, content)
                VALUES (new.id, new.merge_key, new.abstract, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, merge_key, abstract, content)
                VALUES ('delete', old.id, old.merge_key, old.abstract, old.content);
            END;
        """)

    def seed(self, memories: list[dict]):
        """批量写入种子数据 + 构建 HNSW 索引"""
        logger.info("Seeding %d memories into SQLite + HNSW...", len(memories))

        # 1. 写入 SQLite
        for mem in memories:
            self._conn.execute(
                "INSERT OR REPLACE INTO memories (merge_key, category, parent_entity, abstract, content, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    mem["merge_key"],
                    mem.get("category", "entities"),
                    mem.get("parent_entity", ""),
                    mem.get("abstract", ""),
                    mem.get("content", ""),
                    time.time(),
                ),
            )
            self._memories[mem["merge_key"]] = mem
        self._conn.commit()

        # 2. 构建 HNSW 向量索引
        texts_to_embed = []
        keys_ordered = []
        for mem in memories:
            # 用 abstract + content 拼接作为 embedding 文本（与 VikingEngine 对齐）
            text = f"{mem.get('abstract', '')} {mem.get('content', '')}"
            texts_to_embed.append(text)
            keys_ordered.append(mem["merge_key"])

        logger.info("Embedding %d texts...", len(texts_to_embed))
        vectors = self._embedding.embed_texts(texts_to_embed)
        vectors_np = np.array(vectors, dtype=np.float32)

        # 构建 HNSW
        import hnswlib
        dim = vectors_np.shape[1]
        self._hnsw_index = hnswlib.Index(space="cosine", dim=dim)
        self._hnsw_index.init_index(
            max_elements=len(memories) * 2,
            ef_construction=_HNSW_EF_CONSTRUCTION,
            M=_HNSW_M,
        )
        self._hnsw_index.set_ef(_HNSW_EF_SEARCH)

        ids = list(range(len(memories)))
        self._hnsw_index.add_items(vectors_np, ids)

        # 建立 idx → merge_key 映射
        for idx, key in enumerate(keys_ordered):
            self._id_map[idx] = key

        logger.info("HNSW index built: %d vectors, dim=%d", len(memories), dim)

    def search(self, query: str, top_k: int = _SEARCH_TOP_K) -> list[dict]:
        """双路混合检索：FTS5 BM25 + HNSW ANN → 归一化加权融合

        这是 Headroom 风格的极简方案：
          - 无 LLM Query Rewrite
          - 无目录递归
          - 无 Rerank
          - 直接用原始 query 做检索
        """
        # 路 1: HNSW 向量检索（Dense）
        dense_results = self._search_dense(query, top_k=top_k * 3)

        # 路 2: SQLite FTS5 BM25 检索（Sparse）
        sparse_results = self._search_sparse(query, top_k=top_k * 3)

        # 归一化 + 融合
        fused = self._fuse_results(dense_results, sparse_results, top_k)
        return fused

    def _search_dense(self, query: str, top_k: int = 15) -> list[tuple[str, float]]:
        """HNSW 向量检索 — 返回 [(merge_key, cosine_similarity), ...]"""
        if self._hnsw_index is None:
            return []

        query_vec = np.array([self._embedding.embed_query(query)], dtype=np.float32)
        labels, distances = self._hnsw_index.knn_query(query_vec, k=min(top_k, self._hnsw_index.get_current_count()))

        results = []
        for label, dist in zip(labels[0], distances[0]):
            merge_key = self._id_map.get(int(label), "")
            # hnswlib cosine 返回的是 1 - cosine_similarity
            similarity = 1.0 - dist
            if merge_key:
                results.append((merge_key, similarity))
        return results

    def _search_sparse(self, query: str, top_k: int = 15) -> list[tuple[str, float]]:
        """SQLite FTS5 BM25 检索 — 返回 [(merge_key, bm25_score), ...]

        FTS5 的 BM25 函数返回负数（越小越相关），这里取绝对值归一化。
        """
        # 提取关键词用于 FTS5 查询
        keywords = self._extract_keywords(query)
        if not keywords:
            # FTS5 查不到，用 LIKE 兜底
            return self._search_like(query, top_k)

        # FTS5 查询：多词 OR
        fts_query = " OR ".join(f'"{w}"' for w in keywords)

        try:
            rows = self._conn.execute(
                """
                SELECT m.merge_key, rank
                FROM memories_fts
                JOIN memories m ON memories_fts.rowid = m.id
                WHERE memories_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, top_k),
            ).fetchall()

            results = []
            for row in rows:
                # FTS5 rank 是负数，绝对值越大越相关
                score = abs(row[1]) if row[1] else 0.0
                results.append((row[0], score))
            return results
        except Exception as exc:
            logger.debug("FTS5 search failed: %s, falling back to LIKE", exc)
            return self._search_like(query, top_k)

    def _search_like(self, query: str, top_k: int) -> list[tuple[str, float]]:
        """LIKE 兜底检索"""
        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        conditions = " OR ".join(
            f"(abstract LIKE '%{kw}%' OR content LIKE '%{kw}%' OR merge_key LIKE '%{kw}%')"
            for kw in keywords[:5]
        )
        rows = self._conn.execute(
            f"SELECT merge_key FROM memories WHERE {conditions} LIMIT ?",
            (top_k,),
        ).fetchall()

        # LIKE 没有分数，给固定分
        return [(row[0], 1.0) for row in rows]

    def _fuse_results(
        self,
        dense: list[tuple[str, float]],
        sparse: list[tuple[str, float]],
        top_k: int,
    ) -> list[dict]:
        """归一化 + 加权融合"""
        # 归一化 dense scores [0, 1]（cosine 已经在 [0, 1]）
        dense_scores: dict[str, float] = {}
        if dense:
            max_d = max(s for _, s in dense) if dense else 1.0
            min_d = min(s for _, s in dense) if dense else 0.0
            rng = max_d - min_d if max_d != min_d else 1.0
            for key, score in dense:
                dense_scores[key] = (score - min_d) / rng

        # 归一化 sparse scores [0, 1]
        sparse_scores: dict[str, float] = {}
        if sparse:
            max_s = max(s for _, s in sparse) if sparse else 1.0
            min_s = min(s for _, s in sparse) if sparse else 0.0
            rng = max_s - min_s if max_s != min_s else 1.0
            for key, score in sparse:
                sparse_scores[key] = (score - min_s) / rng

        # 融合
        all_keys = set(dense_scores.keys()) | set(sparse_scores.keys())
        fused: list[tuple[str, float]] = []
        for key in all_keys:
            d_score = dense_scores.get(key, 0.0)
            s_score = sparse_scores.get(key, 0.0)
            final = _DENSE_WEIGHT * d_score + _SPARSE_WEIGHT * s_score
            fused.append((key, final))

        fused.sort(key=lambda x: -x[1])

        # 转为 memory dict 输出
        results = []
        for key, score in fused[:top_k]:
            mem = self._memories.get(key, {})
            results.append({
                "merge_key": key,
                "category": mem.get("category", ""),
                "parent_entity": mem.get("parent_entity", ""),
                "abstract": mem.get("abstract", ""),
                "content": mem.get("content", ""),
                "score": score,
            })
        return results

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """简单中文分词 — N-gram + 停用词过滤"""
        cn_segments = re.findall(r'[\u4e00-\u9fff]+', text)
        en_words = re.findall(r'[a-zA-Z0-9]+', text)

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
                     "这个", "那个", "就是", "不是", "的是", "们的", "怎么样"}

        all_words = cn_words + en_words
        return list(set(w for w in all_words if w not in stopwords and len(w) >= 2))


# ═══════════════════════════════════════════════════════════
# 评测引擎
# ═══════════════════════════════════════════════════════════

@dataclass
class BaselineEvalResult:
    case_id: str
    query: str
    query_type: str
    passed: bool
    expected: list[str]
    actual_keys: list[str]
    recall_at_k: float = 0.0
    precision_at_k: float = 0.0
    top1_hit: bool = False
    detail: str = ""


@dataclass
class BaselineEvalReport:
    total: int = 0
    passed: int = 0
    failed: int = 0
    results: list[BaselineEvalResult] = field(default_factory=list)
    by_type: dict[str, dict] = field(default_factory=dict)
    avg_recall_at_5: float = 0.0
    top1_hit_rate: float = 0.0
    duration_ms: float = 0.0

    @property
    def pass_rate(self) -> float:
        return self.passed / max(self.total, 1)


def run_baseline_eval():
    """执行 SQLite + HNSW baseline 评测"""
    from src.eval.memory_eval_runner import SEED_MEMORIES
    from src.eval.memory_eval_cases import build_all_cases
    from src.eval.memory_eval_runner import EvalLayer

    # 1. 初始化存储引擎
    embedding_client = EmbeddingClient()
    store = SQLiteHNSWMemoryStore(embedding_client=embedding_client)

    # 2. 写入种子数据
    store.seed(SEED_MEMORIES)

    # 3. 加载评测用例（仅检索召回类，排除提取类）
    all_cases = build_all_cases()
    retrieval_cases = [c for c in all_cases if c.layer == EvalLayer.RETRIEVAL]
    logger.info("Loaded %d retrieval eval cases", len(retrieval_cases))

    # 4. 逐条评测
    report = BaselineEvalReport()
    all_recall = []
    top1_hits = 0
    start_time = time.time()

    for case in retrieval_cases:
        if case.negative:
            # 负例：检索结果不应命中期望
            results = store.search(case.query, top_k=case.top_k)
            actual_keys = [r["merge_key"] for r in results]
            hit = _check_hit(actual_keys, case.expected_memories)
            passed = not hit  # 负例不应命中
            result = BaselineEvalResult(
                case_id=case.id,
                query=case.query,
                query_type=case.query_type.value if hasattr(case.query_type, 'value') else str(case.query_type),
                passed=passed,
                expected=case.expected_memories,
                actual_keys=actual_keys[:5],
                recall_at_k=0.0 if passed else 1.0,
                detail="负例" + ("通过" if passed else "误命中"),
            )
        else:
            # 正例：检索结果应命中期望
            results = store.search(case.query, top_k=case.top_k)
            actual_keys = [r["merge_key"] for r in results]

            # 计算 recall@k
            hit_count = 0
            first_hit_rank = 0
            for exp_key in case.expected_memories:
                for rank, ak in enumerate(actual_keys, 1):
                    if exp_key.lower() in ak.lower():
                        hit_count += 1
                        if first_hit_rank == 0:
                            first_hit_rank = rank
                        break

            total_expected = max(len(case.expected_memories), 1)
            recall_at_k = hit_count / total_expected
            top1_hit = first_hit_rank == 1

            # 通过条件
            if case.assertion_mode == "all":
                passed = hit_count >= total_expected
            else:  # "any"
                passed = hit_count > 0

            all_recall.append(recall_at_k)
            if top1_hit:
                top1_hits += 1

            result = BaselineEvalResult(
                case_id=case.id,
                query=case.query,
                query_type=case.query_type.value if hasattr(case.query_type, 'value') else str(case.query_type),
                passed=passed,
                expected=case.expected_memories,
                actual_keys=actual_keys[:5],
                recall_at_k=recall_at_k,
                top1_hit=top1_hit,
                detail=f"命中{hit_count}/{total_expected}",
            )

        report.results.append(result)
        report.total += 1
        if result.passed:
            report.passed += 1
        else:
            report.failed += 1

        # 按类型统计
        qt = result.query_type
        if qt not in report.by_type:
            report.by_type[qt] = {"total": 0, "passed": 0, "failed": 0}
        report.by_type[qt]["total"] += 1
        if result.passed:
            report.by_type[qt]["passed"] += 1
        else:
            report.by_type[qt]["failed"] += 1

    report.duration_ms = (time.time() - start_time) * 1000
    n = max(len(all_recall), 1)
    report.avg_recall_at_5 = sum(all_recall) / n
    report.top1_hit_rate = top1_hits / n

    return report


def _check_hit(actual_keys: list[str], expected: list[str]) -> bool:
    """检查是否有任一期望关键词命中"""
    for exp in expected:
        for ak in actual_keys:
            if exp.lower() in ak.lower():
                return True
    return False


# ═══════════════════════════════════════════════════════════
# 报告打印
# ═══════════════════════════════════════════════════════════

def print_report(report: BaselineEvalReport):
    """打印评测报告"""
    print("\n" + "═" * 60)
    print("  SQLite + HNSW Baseline 评测报告")
    print("  (无 LLM Rewrite / 无 Rerank / 无目录递归)")
    print("═" * 60)

    print(f"\n  总用例: {report.total}")
    print(f"  通过:   {report.passed} ({report.pass_rate:.1%})")
    print(f"  失败:   {report.failed}")
    print(f"  耗时:   {report.duration_ms:.0f}ms")

    print(f"\n── 聚合指标 ──────────────────────────────────────────")
    print(f"  Recall@5:     {report.avg_recall_at_5 * 100:.1f}%")
    print(f"  Top-1 命中率: {report.top1_hit_rate * 100:.1f}%")

    print(f"\n── 按查询类型 ────────────────────────────────────────")
    type_names = {
        "exact_entity": "精确实体",
        "fuzzy_semantic": "模糊语义",
        "time_related": "时间相关",
        "cross_category": "跨类别",
        "update_override": "更新覆盖",
        "conflict_resolve": "冲突消解",
        "long_tail_decay": "长尾衰减",
        "negative": "负例验证",
        "multi_dimension": "多维度",
    }
    print(f"  {'类型':<12} {'通过率':<10} {'通过/总':<10}")
    print(f"  {'─' * 40}")
    for qt, stats in sorted(report.by_type.items()):
        name = type_names.get(qt, qt)
        rate = stats["passed"] / max(stats["total"], 1) * 100
        icon = "✅" if rate >= 80 else ("⚠️" if rate >= 60 else "❌")
        print(f"  {icon} {name:<10} {rate:>5.1f}%     {stats['passed']}/{stats['total']}")

    print(f"\n── 对比参考 ──────────────────────────────────────────")
    print(f"  ┌──────────────────┬────────────────┬────────────────┐")
    print(f"  │ 指标             │ SQLite+HNSW    │ VikingEngine   │")
    print(f"  │                  │ (本次实测)     │ (200场景文档)  │")
    print(f"  ├──────────────────┼────────────────┼────────────────┤")
    print(f"  │ 通过率           │ {report.pass_rate*100:>6.1f}%       │    —           │")
    print(f"  │ Recall@5         │ {report.avg_recall_at_5*100:>6.1f}%       │   ≥80% (目标) │")
    print(f"  │ Top-1 命中率     │ {report.top1_hit_rate*100:>6.1f}%       │   76.2%        │")
    print(f"  └──────────────────┴────────────────┴────────────────┘")

    # 失败用例
    failures = [r for r in report.results if not r.passed]
    if failures:
        print(f"\n── 失败用例 (前 15 条) ────────────────────────────────")
        for f in failures[:15]:
            print(f"  ❌ [{f.query_type}] {f.query[:40]}")
            print(f"     期望: {f.expected[:3]} | 实际: {f.actual_keys[:3]}")

    # 保存 JSON
    output_path = "data/eval/runs/sqlite_hnsw_baseline.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump({
            "total": report.total,
            "passed": report.passed,
            "failed": report.failed,
            "pass_rate": round(report.pass_rate, 4),
            "avg_recall_at_5": round(report.avg_recall_at_5, 4),
            "top1_hit_rate": round(report.top1_hit_rate, 4),
            "duration_ms": round(report.duration_ms, 1),
            "by_type": report.by_type,
            "results": [
                {
                    "case_id": r.case_id,
                    "query": r.query,
                    "query_type": r.query_type,
                    "passed": r.passed,
                    "recall_at_k": round(r.recall_at_k, 4),
                    "top1_hit": r.top1_hit,
                    "expected": r.expected,
                    "actual": r.actual_keys[:5],
                }
                for r in report.results
            ],
        }, fp, ensure_ascii=False, indent=2)
    print(f"\n  📊 详细结果已保存: {output_path}")


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("🚀 启动 SQLite + HNSW Baseline 对照实验...")
    print("   模拟 Headroom 风格：SQLite FTS5 + hnswlib HNSW")
    print("   无 LLM Query Rewrite / 无 Rerank / 无目录递归\n")

    report = run_baseline_eval()
    print_report(report)
