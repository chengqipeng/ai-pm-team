"""SQLite + HNSW 增强版对照实验

在 baseline 基础上加入 5 个通用优化（无过拟合、无 LLM 依赖）：
  1. Entity Boost — 查询中识别已知实体名，匹配记忆加权
  2. 通用记忆降权 — parent_entity 为空的记忆在有实体查询时降权
  3. Multi-field Embedding — merge_key 重复加权构造 embedding 文本
  4. Scoped Search — 实体提取后分 scoped + global 两路检索
  5. RRF 融合 — 替代线性归一化加权

依赖：pip install hnswlib numpy langchain-openai

运行：python eval_sqlite_hnsw_enhanced.py
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

_EMBED_MODEL = os.environ.get("EMBEDDING_MODEL", "doubao-embedding-text-240715")
_EMBED_API_KEY = os.environ.get("EMBEDDING_API_KEY") or os.environ.get(
    "DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1"
)
_EMBED_API_BASE = os.environ.get(
    "EMBEDDING_API_BASE", "https://ark.cn-beijing.volces.com/api/v3/"
)
_EMBED_DIM = 2560

# HNSW 参数
_HNSW_M = 16
_HNSW_EF_CONSTRUCTION = 200
_HNSW_EF_SEARCH = 100

# RRF 参数
_RRF_K = 60

# 检索参数
_SEARCH_TOP_K = 5
_ENTITY_BOOST = 1.8          # 实体匹配 boost 系数
_GENERIC_DECAY = 0.55         # 通用记忆（无 parent_entity）在实体查询时的衰减


# ═══════════════════════════════════════════════════════════
# Embedding 客户端
# ═══════════════════════════════════════════════════════════

class EmbeddingClient:
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
# 增强版 SQLite + HNSW 记忆存储
# ═══════════════════════════════════════════════════════════

class EnhancedSQLiteHNSWStore:
    """SQLite FTS5 + hnswlib HNSW — 增强版

    相比 baseline 增加：
      1. Multi-field Embedding（merge_key 加权）
      2. Entity-aware Scoped Search
      3. RRF 融合（替代线性加权）
      4. Entity Boost + 通用记忆降权
    """

    def __init__(self, embedding_client: EmbeddingClient):
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row
        self._embedding = embedding_client
        self._hnsw_index = None
        self._id_map: dict[int, str] = {}
        self._memories: dict[str, dict] = {}
        self._known_entities: set[str] = set()  # 已知实体名集合
        self._setup_db()

    def _setup_db(self):
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
        """批量写入 + 构建索引"""
        logger.info("Seeding %d memories (enhanced)...", len(memories))

        # 收集已知实体名
        for mem in memories:
            pe = mem.get("parent_entity", "")
            if pe:
                self._known_entities.add(pe)

        # 写入 SQLite
        for mem in memories:
            self._conn.execute(
                "INSERT OR REPLACE INTO memories (merge_key, category, parent_entity, abstract, content, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (mem["merge_key"], mem.get("category", "entities"),
                 mem.get("parent_entity", ""), mem.get("abstract", ""),
                 mem.get("content", ""), time.time()),
            )
            self._memories[mem["merge_key"]] = mem
        self._conn.commit()

        # [优化 3] Multi-field Embedding — merge_key 重复加权
        texts_to_embed = []
        keys_ordered = []
        for mem in memories:
            mk = mem["merge_key"]
            abstract = mem.get("abstract", "")
            content = mem.get("content", "")
            # 重复 merge_key 和 parent_entity 让实体名在 embedding 空间更突出
            pe = mem.get("parent_entity", "")
            embed_text = f"{pe} {mk} {mk} {abstract} {content[:300]}"
            texts_to_embed.append(embed_text)
            keys_ordered.append(mk)

        logger.info("Embedding %d texts (multi-field)...", len(texts_to_embed))
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

        for idx, key in enumerate(keys_ordered):
            self._id_map[idx] = key

        logger.info("Enhanced HNSW index built: %d vectors, dim=%d", len(memories), dim)

    def search(self, query: str, top_k: int = _SEARCH_TOP_K) -> list[dict]:
        """增强检索：Entity Extraction → Scoped + Global → RRF → Entity Boost"""

        # [优化 4] 实体提取（纯正则，无 LLM）
        detected_entities = self._extract_entities(query)

        # 两路检索
        if detected_entities:
            # Scoped 路：只在匹配实体范围内检索
            scoped_results = self._search_scoped(query, detected_entities, top_k=top_k * 2)
            # Global 路：全库检索
            global_results = self._search_global(query, top_k=top_k * 2)
            # 合并：Scoped 优先
            merged = self._merge_scoped_global(scoped_results, global_results, top_k)
        else:
            # 无明确实体 → 纯全局检索
            merged = self._search_global(query, top_k=top_k)

        # [优化 1+2] Entity Boost + 通用记忆降权
        boosted = self._apply_entity_boost(merged, detected_entities)

        # 按最终分数重排 + 截断
        boosted.sort(key=lambda x: -x.get("final_score", 0))
        return boosted[:top_k]

    def _search_global(self, query: str, top_k: int = 15) -> list[dict]:
        """全局双路检索 + RRF 融合"""
        dense_ranked = self._search_dense(query, top_k=top_k)
        sparse_ranked = self._search_sparse(query, top_k=top_k)
        return self._rrf_fuse(dense_ranked, sparse_ranked, top_k)

    def _search_scoped(self, query: str, entities: list[str], top_k: int = 10) -> list[dict]:
        """Scoped 检索 — 限定 parent_entity 范围"""
        # Dense: 全库 ANN 后过滤
        dense_all = self._search_dense(query, top_k=top_k * 3)
        dense_scoped = [
            (k, s) for k, s in dense_all
            if self._memories.get(k, {}).get("parent_entity", "") in entities
        ]

        # Sparse: SQLite WHERE 限定
        sparse_scoped = self._search_sparse_scoped(query, entities, top_k=top_k)

        return self._rrf_fuse(dense_scoped, sparse_scoped, top_k)

    def _search_dense(self, query: str, top_k: int = 15) -> list[tuple[str, float]]:
        """HNSW ANN"""
        if self._hnsw_index is None:
            return []
        query_vec = np.array([self._embedding.embed_query(query)], dtype=np.float32)
        k = min(top_k, self._hnsw_index.get_current_count())
        labels, distances = self._hnsw_index.knn_query(query_vec, k=k)
        results = []
        for label, dist in zip(labels[0], distances[0]):
            merge_key = self._id_map.get(int(label), "")
            similarity = 1.0 - dist
            if merge_key:
                results.append((merge_key, similarity))
        return results

    def _search_sparse(self, query: str, top_k: int = 15) -> list[tuple[str, float]]:
        """FTS5 BM25 全局"""
        keywords = self._extract_keywords(query)
        if not keywords:
            return self._search_like(query, top_k)

        fts_query = " OR ".join(f'"{w}"' for w in keywords)
        try:
            rows = self._conn.execute(
                "SELECT m.merge_key, rank FROM memories_fts "
                "JOIN memories m ON memories_fts.rowid = m.id "
                "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, top_k),
            ).fetchall()
            return [(row[0], abs(row[1])) for row in rows]
        except Exception:
            return self._search_like(query, top_k)

    def _search_sparse_scoped(self, query: str, entities: list[str], top_k: int = 10) -> list[tuple[str, float]]:
        """FTS5 + parent_entity 过滤"""
        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        fts_query = " OR ".join(f'"{w}"' for w in keywords)
        placeholders = ",".join("?" * len(entities))
        try:
            rows = self._conn.execute(
                f"SELECT m.merge_key, rank FROM memories_fts "
                f"JOIN memories m ON memories_fts.rowid = m.id "
                f"WHERE memories_fts MATCH ? AND m.parent_entity IN ({placeholders}) "
                f"ORDER BY rank LIMIT ?",
                (fts_query, *entities, top_k),
            ).fetchall()
            return [(row[0], abs(row[1])) for row in rows]
        except Exception:
            return []

    def _search_like(self, query: str, top_k: int) -> list[tuple[str, float]]:
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
        return [(row[0], 1.0) for row in rows]

    # [优化 5] RRF 融合
    def _rrf_fuse(
        self,
        dense_ranked: list[tuple[str, float]],
        sparse_ranked: list[tuple[str, float]],
        top_k: int,
    ) -> list[dict]:
        """Reciprocal Rank Fusion"""
        scores: dict[str, float] = {}

        for rank, (key, _) in enumerate(dense_ranked, 1):
            scores[key] = scores.get(key, 0) + 1.0 / (_RRF_K + rank)

        for rank, (key, _) in enumerate(sparse_ranked, 1):
            scores[key] = scores.get(key, 0) + 1.0 / (_RRF_K + rank)

        # 排序
        sorted_keys = sorted(scores.keys(), key=lambda k: -scores[k])

        results = []
        for key in sorted_keys[:top_k]:
            mem = self._memories.get(key, {})
            results.append({
                "merge_key": key,
                "category": mem.get("category", ""),
                "parent_entity": mem.get("parent_entity", ""),
                "abstract": mem.get("abstract", ""),
                "content": mem.get("content", ""),
                "rrf_score": scores[key],
                "final_score": scores[key],
            })
        return results

    def _merge_scoped_global(
        self,
        scoped: list[dict],
        global_results: list[dict],
        top_k: int,
    ) -> list[dict]:
        """合并 Scoped 和 Global — Scoped 优先，Global 补充

        策略：Scoped 结果 score × 1.3（优先），然后合并去重取 Top-K
        """
        seen = set()
        merged = []

        # Scoped 路优先（加成 30%）
        for r in scoped:
            r["final_score"] = r.get("rrf_score", 0) * 1.3
            merged.append(r)
            seen.add(r["merge_key"])

        # Global 路补充
        for r in global_results:
            if r["merge_key"] not in seen:
                r["final_score"] = r.get("rrf_score", 0)
                merged.append(r)
                seen.add(r["merge_key"])

        merged.sort(key=lambda x: -x.get("final_score", 0))
        return merged[:top_k * 2]

    # [优化 1+2] Entity Boost + 通用记忆降权
    def _apply_entity_boost(self, results: list[dict], detected_entities: list[str]) -> list[dict]:
        """实体匹配加权 + 通用记忆衰减

        策略：
          - 查询含明确实体名 → 匹配实体的记忆 boost，通用记忆降权
          - 查询不含实体名 → 不做任何加权调整（避免误伤）
        """
        if not detected_entities:
            # 无实体查询 → 不干预排序
            return results

        for r in results:
            pe = r.get("parent_entity", "")
            if pe and pe in detected_entities:
                # 实体匹配 → boost
                r["final_score"] = r.get("final_score", 0) * _ENTITY_BOOST
            elif pe and pe not in detected_entities:
                # 其他客户的记忆 → 轻微降权（避免跨客户污染）
                r["final_score"] = r.get("final_score", 0) * 0.75
            elif not pe:
                # 通用记忆（无 parent_entity）→ 降权
                r["final_score"] = r.get("final_score", 0) * _GENERIC_DECAY

        return results

    # ── 实体提取（纯正则，无 LLM）──
    def _extract_entities(self, query: str) -> list[str]:
        """从查询中提取已知实体名"""
        found = []
        for entity in self._known_entities:
            if entity in query:
                found.append(entity)
        return found

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
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
                     "这个", "那个", "就是", "不是", "的是", "们的", "怎么样",
                     "做什", "什么的", "么的人", "现在", "到底"}
        return list(set(w for w in cn_words + en_words if w not in stopwords and len(w) >= 2))


# ═══════════════════════════════════════════════════════════
# 评测
# ═══════════════════════════════════════════════════════════

@dataclass
class EvalResult:
    case_id: str
    query: str
    query_type: str
    passed: bool
    expected: list[str]
    actual_keys: list[str]
    recall_at_k: float = 0.0
    top1_hit: bool = False
    detail: str = ""


@dataclass
class EvalReport:
    total: int = 0
    passed: int = 0
    failed: int = 0
    results: list[EvalResult] = field(default_factory=list)
    by_type: dict[str, dict] = field(default_factory=dict)
    avg_recall_at_5: float = 0.0
    top1_hit_rate: float = 0.0
    duration_ms: float = 0.0

    @property
    def pass_rate(self) -> float:
        return self.passed / max(self.total, 1)


def run_enhanced_eval():
    """执行增强版评测"""
    from src.eval.memory_eval_runner import SEED_MEMORIES
    from src.eval.memory_eval_cases import build_all_cases
    from src.eval.memory_eval_runner import EvalLayer

    # 初始化
    embedding_client = EmbeddingClient()
    store = EnhancedSQLiteHNSWStore(embedding_client=embedding_client)
    store.seed(SEED_MEMORIES)

    # 加载用例
    all_cases = build_all_cases()
    retrieval_cases = [c for c in all_cases if c.layer == EvalLayer.RETRIEVAL]
    logger.info("Loaded %d retrieval eval cases", len(retrieval_cases))

    # 评测
    report = EvalReport()
    all_recall = []
    top1_hits = 0
    start_time = time.time()

    for case in retrieval_cases:
        if case.negative:
            results = store.search(case.query, top_k=case.top_k)
            actual_keys = [r["merge_key"] for r in results]
            hit = _check_hit(actual_keys, case.expected_memories)
            passed = not hit
            result = EvalResult(
                case_id=case.id, query=case.query,
                query_type=case.query_type.value if hasattr(case.query_type, 'value') else str(case.query_type),
                passed=passed, expected=case.expected_memories,
                actual_keys=actual_keys[:5], detail="负例" + ("通过" if passed else "误命中"),
            )
        else:
            results = store.search(case.query, top_k=case.top_k)
            actual_keys = [r["merge_key"] for r in results]

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

            if case.assertion_mode == "all":
                passed = hit_count >= total_expected
            else:
                passed = hit_count > 0

            all_recall.append(recall_at_k)
            if top1_hit:
                top1_hits += 1

            result = EvalResult(
                case_id=case.id, query=case.query,
                query_type=case.query_type.value if hasattr(case.query_type, 'value') else str(case.query_type),
                passed=passed, expected=case.expected_memories,
                actual_keys=actual_keys[:5], recall_at_k=recall_at_k,
                top1_hit=top1_hit, detail=f"命中{hit_count}/{total_expected}",
            )

        report.results.append(result)
        report.total += 1
        if result.passed:
            report.passed += 1
        else:
            report.failed += 1

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
    for exp in expected:
        for ak in actual_keys:
            if exp.lower() in ak.lower():
                return True
    return False


def print_report(report: EvalReport):
    print("\n" + "═" * 60)
    print("  SQLite + HNSW 增强版评测报告")
    print("  (Entity Boost + Scoped Search + RRF + Multi-field Embed)")
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

    print(f"\n── 三方对比 ──────────────────────────────────────────")
    print(f"  ┌──────────────────┬────────────┬────────────┬──────────────┐")
    print(f"  │ 指标             │ Baseline   │ Enhanced   │ VikingEngine │")
    print(f"  │                  │ (极简)     │ (本次)     │ (200场景)    │")
    print(f"  ├──────────────────┼────────────┼────────────┼──────────────┤")
    print(f"  │ 通过率           │   91.5%    │ {report.pass_rate*100:>5.1f}%     │      —       │")
    print(f"  │ Recall@5         │   78.8%    │ {report.avg_recall_at_5*100:>5.1f}%     │  ≥80% (目标) │")
    print(f"  │ Top-1 命中率     │   55.5%    │ {report.top1_hit_rate*100:>5.1f}%     │    76.2%     │")
    print(f"  └──────────────────┴────────────┴────────────┴──────────────┘")

    # 失败用例
    failures = [r for r in report.results if not r.passed]
    if failures:
        print(f"\n── 失败用例 ({len(failures)} 条) ────────────────────────────────")
        for f in failures[:15]:
            print(f"  ❌ [{f.query_type}] {f.query[:45]}")
            print(f"     期望: {f.expected[:3]} | 实际: {f.actual_keys[:3]}")

    # 保存 JSON
    output_path = "data/eval/runs/sqlite_hnsw_enhanced.json"
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
            "enhancements": [
                "Entity Boost (1.8x)",
                "Generic Memory Decay (0.55x)",
                "Multi-field Embedding (merge_key repeat)",
                "Scoped Search (entity-aware two-path)",
                "RRF Fusion (k=60)",
            ],
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


if __name__ == "__main__":
    print("🚀 启动 SQLite + HNSW 增强版对照实验...")
    print("   优化: Entity Boost + Scoped Search + RRF + Multi-field Embed")
    print("   约束: 无 LLM / 无 Rerank / 无目录递归 / 无过拟合\n")

    report = run_enhanced_eval()
    print_report(report)
