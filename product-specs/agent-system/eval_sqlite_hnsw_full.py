"""SQLite + HNSW 完整优化版对照实验

在增强版基础上加入：
  6. LLM Query Rewrite — 轻量 LLM 改写（意图推理 + 关键词提取）
  7. 向量递归展开 — 目录节点定位 + 子节点按语义递归召回

完整优化清单：
  1. Entity Boost
  2. 通用记忆降权
  3. Multi-field Embedding
  4. Scoped Search
  5. RRF 融合
  6. LLM Query Rewrite（NEW）
  7. 向量递归展开（NEW）

约束：仍然是 SQLite + hnswlib 本地方案，LLM 仅用于 query rewrite（不用于 rerank）

依赖：pip install hnswlib numpy langchain-openai openai

运行：python eval_sqlite_hnsw_full.py
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

# LLM 配置（用于 Query Rewrite）
_LLM_MODEL = os.environ.get("OPENAI_MODEL_NAME") or os.environ.get("AGENT_MODEL", "deepseek-v4-flash")
_LLM_API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get(
    "AGENT_API_KEY", "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw"
)
_LLM_API_BASE = os.environ.get("OPENAI_BASE_URL") or os.environ.get(
    "AGENT_API_BASE", "https://tokenhub.tencentmaas.com/v1"
)

# HNSW
_HNSW_M = 16
_HNSW_EF_CONSTRUCTION = 200
_HNSW_EF_SEARCH = 100

# RRF
_RRF_K = 60

# 检索参数
_SEARCH_TOP_K = 5
_ENTITY_BOOST = 1.8
_GENERIC_DECAY = 0.55

# 递归参数
_RECURSIVE_MAX_ROUNDS = 3
_RECURSIVE_SCORE_PROPAGATION = 0.5  # 子分数 = 0.5 * 自身 + 0.5 * 父目录


# ═══════════════════════════════════════════════════════════
# Embedding 客户端
# ═══════════════════════════════════════════════════════════

class EmbeddingClient:
    def __init__(self):
        from langchain_openai import OpenAIEmbeddings
        self._model = OpenAIEmbeddings(
            model=_EMBED_MODEL, api_key=_EMBED_API_KEY,
            base_url=_EMBED_API_BASE, check_embedding_ctx_length=False,
        )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self._model.embed_documents(texts) if texts else []

    def embed_query(self, query: str) -> list[float]:
        return self._model.embed_query(query)


# ═══════════════════════════════════════════════════════════
# LLM Query Rewriter（轻量版）
# ═══════════════════════════════════════════════════════════

class LightQueryRewriter:
    """轻量 LLM Query Rewrite — 无对话历史，纯查询改写

    功能：
      1. 意图推理 → 将抽象查询转为具体描述
      2. 关键词提取 → 提取检索用关键词
      3. 实体推断 → 推断查询可能涉及的实体
    """

    PROMPT = """你是 CRM 记忆库的检索改写模块。将用户查询改写为适合向量检索的形式。

## 已知客户实体
{entities}

## 用户查询
{query}

## 任务
1. 将抽象/口语化查询改写为包含具体描述性词汇的检索查询
2. 如果查询暗示某个客户的特征，推断可能的客户名
3. 提取 3-5 个核心检索关键词

## 改写规则
- "说话最直接" → 改写为含"直接""果断"等描述词
- "喜欢运动" → 改写为含运动类型如"羽毛球""篮球"等
- "喜欢看demo" → 改写为含"live demo""演示"等
- "追求快速迭代" → 改写为含"敏捷""迭代""互联网思维"等
- 不要编造信息，只做语义展开

## 输出格式（严格 JSON）
{{"rewritten_query": "改写后查询（≤60字）", "keywords": ["关键词1", "关键词2", ...], "inferred_entities": ["可能的客户名"]}}"""

    def __init__(self):
        from openai import OpenAI
        self._client = OpenAI(api_key=_LLM_API_KEY, base_url=_LLM_API_BASE)

    def rewrite(self, query: str, known_entities: list[str]) -> dict:
        """改写查询，返回 {rewritten_query, keywords, inferred_entities}"""
        try:
            prompt = self.PROMPT.format(
                entities=", ".join(known_entities),
                query=query,
            )
            resp = self._client.chat.completions.create(
                model=_LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=200,
            )
            content = resp.choices[0].message.content.strip()
            # 提取 JSON
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return {"rewritten_query": query, "keywords": [], "inferred_entities": []}
        except Exception as exc:
            logger.debug("Query rewrite failed: %s", exc)
            return {"rewritten_query": query, "keywords": [], "inferred_entities": []}


# ═══════════════════════════════════════════════════════════
# 完整优化版 SQLite + HNSW 记忆存储
# ═══════════════════════════════════════════════════════════

class FullOptimizedStore:
    """SQLite FTS5 + hnswlib HNSW — 完整优化版

    相比增强版新增：
      - LLM Query Rewrite（意图推理 + 关键词提取）
      - 向量递归展开（目录→子节点语义搜索 + 分数传播）
    """

    def __init__(self, embedding_client: EmbeddingClient, rewriter: LightQueryRewriter):
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row
        self._embedding = embedding_client
        self._rewriter = rewriter
        self._hnsw_index = None
        self._id_map: dict[int, str] = {}
        self._memories: dict[str, dict] = {}
        self._known_entities: set[str] = set()
        self._vectors: dict[str, np.ndarray] = {}  # merge_key → vector（用于递归搜索）
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
                content='memories', content_rowid='id', tokenize='unicode61'
            );
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, merge_key, abstract, content)
                VALUES (new.id, new.merge_key, new.abstract, new.content);
            END;
        """)

    def seed(self, memories: list[dict]):
        logger.info("Seeding %d memories (full optimized)...", len(memories))

        for mem in memories:
            pe = mem.get("parent_entity", "")
            if pe:
                self._known_entities.add(pe)

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

        # Multi-field Embedding
        texts_to_embed = []
        keys_ordered = []
        for mem in memories:
            mk = mem["merge_key"]
            pe = mem.get("parent_entity", "")
            abstract = mem.get("abstract", "")
            content = mem.get("content", "")
            embed_text = f"{pe} {mk} {mk} {abstract} {content[:300]}"
            texts_to_embed.append(embed_text)
            keys_ordered.append(mk)

        logger.info("Embedding %d texts...", len(texts_to_embed))
        vectors = self._embedding.embed_texts(texts_to_embed)
        vectors_np = np.array(vectors, dtype=np.float32)

        # 保存向量供递归搜索用
        for idx, key in enumerate(keys_ordered):
            self._vectors[key] = vectors_np[idx]

        # HNSW
        import hnswlib
        dim = vectors_np.shape[1]
        self._hnsw_index = hnswlib.Index(space="cosine", dim=dim)
        self._hnsw_index.init_index(
            max_elements=len(memories) * 2,
            ef_construction=_HNSW_EF_CONSTRUCTION, M=_HNSW_M,
        )
        self._hnsw_index.set_ef(_HNSW_EF_SEARCH)
        self._hnsw_index.add_items(vectors_np, list(range(len(memories))))

        for idx, key in enumerate(keys_ordered):
            self._id_map[idx] = key

        logger.info("Full optimized index built: %d vectors, dim=%d", len(memories), dim)

    def search(self, query: str, top_k: int = _SEARCH_TOP_K) -> list[dict]:
        """完整检索流水线：LLM Rewrite → Entity Extract → Scoped+Global → RRF → 递归展开 → Boost"""

        # [优化 6] LLM Query Rewrite
        rewrite_result = self._rewriter.rewrite(query, list(self._known_entities))
        rewritten_query = rewrite_result.get("rewritten_query", query)
        inferred_entities = rewrite_result.get("inferred_entities", [])
        extra_keywords = rewrite_result.get("keywords", [])

        # 实体提取：原始 query 中的 + LLM 推断的
        detected_entities = self._extract_entities(query)
        for ie in inferred_entities:
            if ie in self._known_entities and ie not in detected_entities:
                detected_entities.append(ie)

        # 使用改写后的 query 做检索
        search_query = rewritten_query if rewritten_query != query else query

        # 两路检索
        if detected_entities:
            scoped_results = self._search_scoped(search_query, detected_entities, top_k=top_k * 2)
            global_results = self._search_global(search_query, top_k=top_k * 2)
            merged = self._merge_scoped_global(scoped_results, global_results, top_k * 2)
        else:
            merged = self._search_global(search_query, top_k=top_k * 2)

        # [优化 7] 向量递归展开
        if detected_entities:
            recursive_results = self._recursive_expand(search_query, detected_entities, top_k)
            # 合并递归结果
            merged = self._merge_with_recursive(merged, recursive_results)

        # Entity Boost + 通用降权
        boosted = self._apply_entity_boost(merged, detected_entities)
        boosted.sort(key=lambda x: -x.get("final_score", 0))
        return boosted[:top_k]

    # ── 向量递归展开 ──

    def _recursive_expand(self, query: str, entities: list[str], top_k: int) -> list[dict]:
        """[优化 7] 向量递归展开

        逻辑：
          1. 找到目标实体下的所有记忆
          2. 用 query vector 在该子集内做 ANN
          3. 分数传播：final = 0.5 * 自身cosine + 0.5 * 实体匹配基础分
        """
        query_vec = np.array(self._embedding.embed_query(query), dtype=np.float32)

        # 收集目标实体下的所有记忆向量
        entity_memories: list[tuple[str, np.ndarray]] = []
        for mk, mem in self._memories.items():
            if mem.get("parent_entity", "") in entities:
                if mk in self._vectors:
                    entity_memories.append((mk, self._vectors[mk]))

        if not entity_memories:
            return []

        # 在子集内计算 cosine similarity
        scored = []
        for mk, vec in entity_memories:
            # cosine similarity
            dot = float(np.dot(query_vec, vec))
            norm_q = float(np.linalg.norm(query_vec))
            norm_v = float(np.linalg.norm(vec))
            cosine = dot / (norm_q * norm_v + 1e-8)
            # 分数传播：实体基础分 0.5（确认是对的实体）+ 自身语义分 0.5
            propagated_score = _RECURSIVE_SCORE_PROPAGATION * cosine + _RECURSIVE_SCORE_PROPAGATION * 0.8
            scored.append((mk, propagated_score))

        scored.sort(key=lambda x: -x[1])

        results = []
        for mk, score in scored[:top_k]:
            mem = self._memories.get(mk, {})
            results.append({
                "merge_key": mk,
                "category": mem.get("category", ""),
                "parent_entity": mem.get("parent_entity", ""),
                "abstract": mem.get("abstract", ""),
                "content": mem.get("content", ""),
                "rrf_score": score,
                "final_score": score,
                "source": "recursive",
            })
        return results

    def _merge_with_recursive(self, base: list[dict], recursive: list[dict]) -> list[dict]:
        """合并基础结果和递归结果 — 递归结果额外 boost"""
        seen = {r["merge_key"] for r in base}
        merged = list(base)

        for r in recursive:
            if r["merge_key"] not in seen:
                r["final_score"] = r.get("final_score", 0) * 1.2  # 递归 boost
                merged.append(r)
                seen.add(r["merge_key"])
            else:
                # 已在 base 中 → 取较高分
                for b in merged:
                    if b["merge_key"] == r["merge_key"]:
                        b["final_score"] = max(b.get("final_score", 0), r.get("final_score", 0))
                        break

        return merged

    # ── 基础检索方法（同增强版）──

    def _search_global(self, query: str, top_k: int = 15) -> list[dict]:
        dense_ranked = self._search_dense(query, top_k=top_k)
        sparse_ranked = self._search_sparse(query, top_k=top_k)
        return self._rrf_fuse(dense_ranked, sparse_ranked, top_k)

    def _search_scoped(self, query: str, entities: list[str], top_k: int = 10) -> list[dict]:
        dense_all = self._search_dense(query, top_k=top_k * 3)
        dense_scoped = [(k, s) for k, s in dense_all
                        if self._memories.get(k, {}).get("parent_entity", "") in entities]
        sparse_scoped = self._search_sparse_scoped(query, entities, top_k=top_k)
        return self._rrf_fuse(dense_scoped, sparse_scoped, top_k)

    def _search_dense(self, query: str, top_k: int = 15) -> list[tuple[str, float]]:
        if self._hnsw_index is None:
            return []
        query_vec = np.array([self._embedding.embed_query(query)], dtype=np.float32)
        k = min(top_k, self._hnsw_index.get_current_count())
        labels, distances = self._hnsw_index.knn_query(query_vec, k=k)
        return [(self._id_map.get(int(l), ""), 1.0 - d)
                for l, d in zip(labels[0], distances[0]) if self._id_map.get(int(l))]

    def _search_sparse(self, query: str, top_k: int = 15) -> list[tuple[str, float]]:
        keywords = self._extract_keywords(query)
        if not keywords:
            return []
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
            return []

    def _search_sparse_scoped(self, query: str, entities: list[str], top_k: int = 10) -> list[tuple[str, float]]:
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

    def _rrf_fuse(self, dense: list[tuple[str, float]], sparse: list[tuple[str, float]], top_k: int) -> list[dict]:
        scores: dict[str, float] = {}
        for rank, (key, _) in enumerate(dense, 1):
            scores[key] = scores.get(key, 0) + 1.0 / (_RRF_K + rank)
        for rank, (key, _) in enumerate(sparse, 1):
            scores[key] = scores.get(key, 0) + 1.0 / (_RRF_K + rank)

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

    def _merge_scoped_global(self, scoped: list[dict], global_r: list[dict], top_k: int) -> list[dict]:
        seen = set()
        merged = []
        for r in scoped:
            r["final_score"] = r.get("rrf_score", 0) * 1.3
            merged.append(r)
            seen.add(r["merge_key"])
        for r in global_r:
            if r["merge_key"] not in seen:
                r["final_score"] = r.get("rrf_score", 0)
                merged.append(r)
                seen.add(r["merge_key"])
        merged.sort(key=lambda x: -x.get("final_score", 0))
        return merged[:top_k]

    def _apply_entity_boost(self, results: list[dict], detected_entities: list[str]) -> list[dict]:
        if not detected_entities:
            return results
        for r in results:
            pe = r.get("parent_entity", "")
            if pe and pe in detected_entities:
                r["final_score"] = r.get("final_score", 0) * _ENTITY_BOOST
            elif pe and pe not in detected_entities:
                r["final_score"] = r.get("final_score", 0) * 0.75
            elif not pe:
                r["final_score"] = r.get("final_score", 0) * _GENERIC_DECAY
        return results

    def _extract_entities(self, query: str) -> list[str]:
        return [e for e in self._known_entities if e in query]

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


def run_full_eval():
    from src.eval.memory_eval_runner import SEED_MEMORIES
    from src.eval.memory_eval_cases import build_all_cases
    from src.eval.memory_eval_runner import EvalLayer

    embedding_client = EmbeddingClient()
    rewriter = LightQueryRewriter()
    store = FullOptimizedStore(embedding_client=embedding_client, rewriter=rewriter)
    store.seed(SEED_MEMORIES)

    all_cases = build_all_cases()
    retrieval_cases = [c for c in all_cases if c.layer == EvalLayer.RETRIEVAL]
    logger.info("Loaded %d retrieval eval cases", len(retrieval_cases))

    report = EvalReport()
    all_recall = []
    top1_hits = 0
    start_time = time.time()

    for i, case in enumerate(retrieval_cases):
        if i % 20 == 0:
            logger.info("Progress: %d/%d", i, len(retrieval_cases))

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
    print("\n" + "═" * 64)
    print("  SQLite + HNSW 完整优化版评测报告")
    print("  (全部 7 项优化：含 LLM Query Rewrite + 向量递归展开)")
    print("═" * 64)

    print(f"\n  总用例: {report.total}")
    print(f"  通过:   {report.passed} ({report.pass_rate:.1%})")
    print(f"  失败:   {report.failed}")
    print(f"  耗时:   {report.duration_ms:.0f}ms")

    print(f"\n── 聚合指标 ──────────────────────────────────────────")
    print(f"  Recall@5:     {report.avg_recall_at_5 * 100:.1f}%")
    print(f"  Top-1 命中率: {report.top1_hit_rate * 100:.1f}%")

    print(f"\n── 按查询类型 ────────────────────────────────────────")
    type_names = {
        "exact_entity": "精确实体", "fuzzy_semantic": "模糊语义",
        "time_related": "时间相关", "cross_category": "跨类别",
        "update_override": "更新覆盖", "conflict_resolve": "冲突消解",
        "long_tail_decay": "长尾衰减", "negative": "负例验证",
        "multi_dimension": "多维度",
    }
    print(f"  {'类型':<12} {'通过率':<10} {'通过/总':<10}")
    print(f"  {'─' * 40}")
    for qt, stats in sorted(report.by_type.items()):
        name = type_names.get(qt, qt)
        rate = stats["passed"] / max(stats["total"], 1) * 100
        icon = "✅" if rate >= 80 else ("⚠️" if rate >= 60 else "❌")
        print(f"  {icon} {name:<10} {rate:>5.1f}%     {stats['passed']}/{stats['total']}")

    print(f"\n── 四方对比 ──────────────────────────────────────────────────")
    print(f"  ┌──────────────────┬──────────┬──────────┬──────────┬────────────┐")
    print(f"  │ 指标             │ Baseline │ Enhanced │ Full     │ Viking     │")
    print(f"  │                  │ (极简)   │ (+5优化) │ (+LLM)   │ (200场景)  │")
    print(f"  ├──────────────────┼──────────┼──────────┼──────────┼────────────┤")
    print(f"  │ 通过率           │  91.5%   │  95.4%   │ {report.pass_rate*100:>5.1f}%   │     —      │")
    print(f"  │ Recall@5         │  78.8%   │  83.9%   │ {report.avg_recall_at_5*100:>5.1f}%   │  ≥80%      │")
    print(f"  │ Top-1 命中率     │  55.5%   │  51.8%   │ {report.top1_hit_rate*100:>5.1f}%   │  76.2%     │")
    print(f"  └──────────────────┴──────────┴──────────┴──────────┴────────────┘")

    failures = [r for r in report.results if not r.passed]
    if failures:
        print(f"\n── 失败用例 ({len(failures)} 条) ────────────────────────────────")
        for f in failures[:10]:
            print(f"  ❌ [{f.query_type}] {f.query[:45]}")
            print(f"     期望: {f.expected[:3]} | 实际: {f.actual_keys[:3]}")

    output_path = "data/eval/runs/sqlite_hnsw_full.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump({
            "total": report.total, "passed": report.passed, "failed": report.failed,
            "pass_rate": round(report.pass_rate, 4),
            "avg_recall_at_5": round(report.avg_recall_at_5, 4),
            "top1_hit_rate": round(report.top1_hit_rate, 4),
            "duration_ms": round(report.duration_ms, 1),
            "by_type": report.by_type,
            "enhancements": [
                "1. Entity Boost (1.8x)",
                "2. Generic Memory Decay (0.55x)",
                "3. Multi-field Embedding",
                "4. Scoped Search",
                "5. RRF Fusion (k=60)",
                "6. LLM Query Rewrite (deepseek-v4-flash)",
                "7. Vector Recursive Expand (score propagation 0.5)",
            ],
            "results": [
                {"case_id": r.case_id, "query": r.query, "query_type": r.query_type,
                 "passed": r.passed, "recall_at_k": round(r.recall_at_k, 4),
                 "top1_hit": r.top1_hit, "expected": r.expected, "actual": r.actual_keys[:5]}
                for r in report.results
            ],
        }, fp, ensure_ascii=False, indent=2)
    print(f"\n  📊 详细结果已保存: {output_path}")


if __name__ == "__main__":
    print("🚀 启动 SQLite + HNSW 完整优化版对照实验...")
    print("   全部 7 项优化：Entity Boost + Scoped + RRF + Multi-field")
    print("                 + LLM Query Rewrite + 向量递归展开")
    print("   约束：仍为本地 SQLite+hnswlib，无 Rerank\n")

    report = run_full_eval()
    print_report(report)
