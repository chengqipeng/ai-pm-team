"""1000 条用例三方对比验证 — SQLite+HNSW+Qwen3 vs grep+jieba vs VDB+doubao

一键运行:
  python demo_1000cases_benchmark.py

输出:
  - Console 汇总表 (通过率 / 召回率 / 延迟)
  - 分类对比表
  - JSON 结果文件 → data/eval/runs/1000cases_benchmark.json
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
import jieba

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()
jieba.initialize()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

_TOP_K = 5
_RRF_K = 60
_HNSW_M, _HNSW_EF_C, _HNSW_EF_S = 16, 200, 100

_VDB_URL = os.environ.get("TENCENT_VDB_URL", "http://10.60.2.17")
_VDB_KEY = os.environ.get("TENCENT_VDB_KEY", "bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck")
_VDB_USER = "root"
_VDB_DB = "viking_memory"
_VDB_COLLECTION = "archive_1000cases_eval"

_REMOTE_EMBED_MODEL = os.environ.get("EMBEDDING_MODEL", "doubao-embedding-text-240715")
_REMOTE_EMBED_KEY = os.environ.get("EMBEDDING_API_KEY") or os.environ.get(
    "DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")
_REMOTE_EMBED_BASE = os.environ.get("EMBEDDING_API_BASE", "https://ark.cn-beijing.volces.com/api/v3/")

_STOPS = frozenset("的 了 在 是 我 有 和 就 不 人 都 一 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这 他 她 它 们 那 些 什么 怎么 哪个 哪些 为什么 可以 能 吗 呢 吧 啊 帮 帮我 一下 把 被 让 给 从 对 但 而 如果 因为 所以 然后 还 又 再 已经 做 多少 现在 上次 之前 所有 相关 有没有 是否 需要 请问 能否 还是 以及 这个 那个 就是 不是 怎么样 到底".split())

# ═══════════════════════════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════════════════════════

from eval_1000cases_data import build_1000_seed, build_1000_cases, Case


def build_text(t: dict) -> str:
    """统一的文本构造"""
    return (
        f"{t['user_query']} {t['answer_preview']} "
        f"{t['entities_text']} {t['keywords']} "
        f"{t.get('tool_names', '')} {t.get('biz_object', '')}"
    ).lower()


# ═══════════════════════════════════════════════════════════
# 方案 A: SQLite + HNSW + Qwen3-Embedding-0.6B
# ═══════════════════════════════════════════════════════════

class LocalEngine:
    def __init__(self):
        from src.embedding import LocalEmbedding
        self._emb = LocalEmbedding()
        self._conn = sqlite3.connect(":memory:")
        self._hnsw = None
        self._id_map = {}
        self._conn.executescript("""
            CREATE TABLE t(tid INT PRIMARY KEY, text TEXT);
            CREATE VIRTUAL TABLE fts USING fts5(text, content='t', content_rowid='tid', tokenize='unicode61');
            CREATE TRIGGER ti AFTER INSERT ON t BEGIN INSERT INTO fts(rowid, text) VALUES(new.tid, new.text); END;
        """)

    def write(self, turns: list[dict]):
        texts = [build_text(t) for t in turns]
        vecs = self._emb.embed_documents_np(texts)
        for i, t in enumerate(turns):
            self._conn.execute("INSERT INTO t VALUES(?,?)", (t["turn_id"], texts[i]))
        self._conn.commit()
        import hnswlib
        self._hnsw = hnswlib.Index(space="cosine", dim=vecs.shape[1])
        self._hnsw.init_index(max_elements=len(turns) * 2, ef_construction=_HNSW_EF_C, M=_HNSW_M)
        self._hnsw.set_ef(_HNSW_EF_S)
        self._hnsw.add_items(vecs, list(range(len(turns))))
        for i, t in enumerate(turns):
            self._id_map[i] = t["turn_id"]

    def search(self, query: str, top_k: int = _TOP_K) -> tuple[list[int], float]:
        t0 = time.time()
        qv = self._emb.embed_query_np(query)
        n_items = len(self._id_map)
        labels, dists = self._hnsw.knn_query(
            np.array([qv], dtype=np.float32), k=min(top_k * 3, n_items)
        )
        dense = [(self._id_map[int(l)], 1.0 - d) for l, d in zip(labels[0], dists[0])]

        # FTS 关键词
        kws = [w for w in jieba.cut(query.lower()) if w not in _STOPS and len(w) >= 2]
        kws += re.findall(r'[a-zA-Z0-9$¥_\-]+', query.lower())
        sparse = []
        if kws:
            match_expr = " OR ".join(f'"{k}"' for k in kws[:10])
            try:
                rows = self._conn.execute(
                    f"SELECT rowid, rank FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT ?",
                    (match_expr, top_k * 3)
                ).fetchall()
                max_score = abs(rows[0][1]) if rows else 1.0
                sparse = [(int(r[0]), abs(r[1]) / max_score) for r in rows]
            except Exception:
                pass

        # RRF 融合
        rrf = {}
        for rank, (tid, _) in enumerate(sorted(dense, key=lambda x: -x[1])):
            rrf[tid] = rrf.get(tid, 0) + 1.0 / (rank + _RRF_K)
        for rank, (tid, _) in enumerate(sorted(sparse, key=lambda x: -x[1])):
            rrf[tid] = rrf.get(tid, 0) + 1.0 / (rank + _RRF_K)

        result = sorted(rrf.items(), key=lambda x: -x[1])[:top_k]
        ms = (time.time() - t0) * 1000
        return [tid for tid, _ in result], ms


# ═══════════════════════════════════════════════════════════
# 方案 B: grep + jieba 字段加权 (原始版)
# ═══════════════════════════════════════════════════════════

class GrepEngine:
    def __init__(self):
        self._fields: dict[int, dict] = {}

    def write(self, turns: list[dict]):
        for t in turns:
            self._fields[t["turn_id"]] = {
                "entities": t.get("entities_text", "").lower(),
                "user_query": t["user_query"].lower(),
                "answer": t["answer_preview"].lower(),
                "keywords": t.get("keywords", "").lower(),
                "tools": t.get("tool_names", "").lower(),
                "biz": t.get("biz_object", "").lower(),
            }

    def search(self, query: str, top_k: int = _TOP_K) -> tuple[list[int], float]:
        t0 = time.time()
        kws = [w for w in jieba.cut(query.lower()) if w not in _STOPS and len(w) >= 2]
        en = re.findall(r'[a-zA-Z0-9$¥_\-]+', query.lower())
        # 中文 bigram/trigram
        s = re.sub(r'[a-zA-Z0-9\s$¥_\-]+', '', query.lower())
        for i in range(len(s) - 1):
            kws.append(s[i:i + 2])
        for i in range(len(s) - 2):
            kws.append(s[i:i + 3])
        kws = list(set(kws + en))

        scored = []
        for tid, f in self._fields.items():
            score = 0
            for kw in kws:
                if kw in f["entities"]:
                    score += 3
                if kw in f["user_query"]:
                    score += 2
                if kw in f["keywords"]:
                    score += 2
                if kw in f["tools"]:
                    score += 2
                if kw in f["biz"]:
                    score += 2
                if kw in f["answer"]:
                    score += 1
            if score > 0:
                scored.append((tid, score))
        scored.sort(key=lambda x: -x[1])
        ms = (time.time() - t0) * 1000
        return [tid for tid, _ in scored[:top_k]], ms


# ═══════════════════════════════════════════════════════════
# 方案 B+: grep 优化版 — IDF加权 + 去bigram + 实体优先 + 业务停用词
# ═══════════════════════════════════════════════════════════

import math
from collections import Counter

# 扩展业务停用词 (高频通用词，区分度极低)
_BIZ_STOPS = frozenset({
    "客户", "信息", "查询", "查了", "查到", "数据查询", "数据",
    "执行操作", "更新", "修改", "创建", "执行",
    "数据分析", "分析", "统计", "生成",
    "网络搜索", "搜索", "网上查", "竞品调研",
})


class GrepEngineV2:
    """优化版 grep: IDF加权 + 自定义词典 + 实体倒排 + 分层评分"""

    def __init__(self):
        self._fields: dict[int, dict] = {}
        self._entity_index: dict[str, list[int]] = {}  # 实体名 → turn_ids
        self._idf: dict[str, float] = {}
        self._n_docs = 0

    def write(self, turns: list[dict]):
        self._n_docs = len(turns)

        # 1. 注册自定义词典 (从 entities_text 提取)
        all_entities = set()
        for t in turns:
            for ent in t.get("entities_text", "").split():
                ent_lower = ent.lower().strip()
                if len(ent_lower) >= 2:
                    all_entities.add(ent_lower)
        for ent in all_entities:
            jieba.add_word(ent, freq=50000)

        # 2. 构建字段索引 + 实体倒排索引
        for t in turns:
            tid = t["turn_id"]
            self._fields[tid] = {
                "entities": t.get("entities_text", "").lower(),
                "user_query": t["user_query"].lower(),
                "answer": t["answer_preview"].lower(),
                "keywords": t.get("keywords", "").lower(),
                "tools": t.get("tool_names", "").lower(),
                "biz": t.get("biz_object", "").lower(),
                "action": t.get("action_subtype", "").lower(),
            }
            # 实体倒排
            for ent in t.get("entities_text", "").lower().split():
                ent = ent.strip()
                if len(ent) >= 2:
                    self._entity_index.setdefault(ent, []).append(tid)

        # 3. 计算 IDF (基于所有字段拼接后的文档)
        word_df = Counter()
        for tid, f in self._fields.items():
            doc_text = " ".join(f.values())
            seen = set()
            for w in jieba.cut(doc_text):
                if w not in _STOPS and len(w) >= 2 and w not in seen:
                    word_df[w] += 1
                    seen.add(w)
            for w in re.findall(r'[a-zA-Z0-9$¥_\-]+', doc_text):
                if w not in seen:
                    word_df[w] += 1
                    seen.add(w)

        n = self._n_docs
        self._idf = {w: math.log((n + 1) / (df + 1)) + 1.0 for w, df in word_df.items()}

    def _get_idf(self, word: str) -> float:
        """获取 IDF 值, 未见过的词给高 IDF (强区分度)"""
        return self._idf.get(word, math.log(self._n_docs + 1) + 1.0)

    def _extract_keywords(self, query: str) -> tuple[list[str], list[str]]:
        """分词 + 提取实体，返回 (普通词, 实体词)"""
        q = query.lower()
        # jieba 分词 (已含自定义词典) — 不过滤业务停用词，靠 IDF 自然降权
        words = [w for w in jieba.cut(q) if w not in _STOPS and len(w) >= 2]
        # 英文/数字/特殊符号
        en_tokens = re.findall(r'[a-zA-Z][a-zA-Z0-9_\-]*[a-zA-Z0-9]|[a-zA-Z]|\d+[a-zA-Z¥$%]+[\d.]*|\$[\d,.]+[kKmM]?|¥[\d,.万亿]+|[A-Z][\w\-]+\d+|\d{3,}', q)
        # ID 模式 (opp_xxx, Q-xxx, CON-xxx, con_xxx, POC-xxx)
        id_tokens = re.findall(r'(?:opp|con|q|poc|req|tp|cон)[-_][a-zA-Z0-9_\-]+', q, re.IGNORECASE)

        all_words = list(set(words + en_tokens + id_tokens))

        # 区分: 实体词 vs 普通词
        entities = [w for w in all_words if w in self._entity_index]
        normals = [w for w in all_words if w not in self._entity_index]

        return normals, entities

    def search(self, query: str, top_k: int = _TOP_K) -> tuple[list[int], float]:
        t0 = time.time()
        normals, entities = self._extract_keywords(query)

        # ═══ 第 1 层: 精确实体匹配 (最高优先级) ═══
        entity_scores: dict[int, float] = {}
        for ent in entities:
            tids = self._entity_index.get(ent, [])
            idf = self._get_idf(ent)
            for tid in tids:
                entity_scores[tid] = entity_scores.get(tid, 0) + 10.0 * idf

        # ═══ 第 2 层: IDF 加权字段匹配 ═══
        field_scores: dict[int, float] = {}
        all_kws = normals + entities  # 实体也参与字段匹配

        for tid, f in self._fields.items():
            score = 0.0
            for kw in all_kws:
                idf = self._get_idf(kw)
                # 字段权重: entities(5) > user_query(3) > keywords(2) > tools(2) > biz(2) > answer(1)
                if kw in f["entities"]:
                    score += 5.0 * idf
                if kw in f["user_query"]:
                    score += 3.0 * idf
                if kw in f["keywords"]:
                    score += 2.0 * idf
                if kw in f["tools"]:
                    score += 2.0 * idf
                if kw in f["biz"]:
                    score += 2.0 * idf
                if kw in f["action"]:
                    score += 2.0 * idf
                if kw in f["answer"]:
                    score += 1.0 * idf
            if score > 0:
                field_scores[tid] = score

        # ═══ 合并评分 ═══
        final_scores: dict[int, float] = {}
        all_tids = set(entity_scores.keys()) | set(field_scores.keys())
        for tid in all_tids:
            es = entity_scores.get(tid, 0)
            fs = field_scores.get(tid, 0)
            # 实体命中加成
            if es > 0:
                final_scores[tid] = fs * 1.5 + es
            else:
                final_scores[tid] = fs

        # 排序返回 top_k
        ranked = sorted(final_scores.items(), key=lambda x: -x[1])[:top_k]
        ms = (time.time() - t0) * 1000
        return [tid for tid, _ in ranked], ms


# ═══════════════════════════════════════════════════════════
# 方案 C: 腾讯 VDB + doubao Embedding
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
        records = []
        for turn in turns:
            tid = turn["turn_id"]
            text = build_text(turn)
            vec = self._embedding.embed_query(text)
            bm25_text = f"{turn['user_query']} {turn['answer_preview']}"[:800]
            records.append({
                "id": f"eval_1000_turn_{tid}",
                "vector": vec,
                "tenant_id": "eval1000",
                "thread_id": "eval_1000_session",
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
        filter_expr = 'thread_id = "eval_1000_session"'
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
# 评测逻辑
# ═══════════════════════════════════════════════════════════

def evaluate(hits: list[int], case: Case) -> tuple[bool, float]:
    """统一评判: recall@5 >= 0.3 即通过"""
    if case.expect_no_hit:
        # 负例: 不应命中任何 expected_turns (如果有的话), 或者 hits 应为空
        if case.expected_turns:
            passed = not any(t in case.expected_turns for t in hits)
        else:
            passed = len(hits) == 0
        return passed, 1.0 if passed else 0.0
    if not case.expected_turns:
        return len(hits) > 0, 1.0 if hits else 0.0
    exp, hit = set(case.expected_turns), set(hits)
    recall = len(exp & hit) / max(len(exp), 1)
    return recall >= 0.3, recall


def run_eval(engine, cases: list[Case], label: str) -> dict:
    """运行评测并返回汇总结果"""
    results = []
    all_recall = []
    all_ms = []
    for i, c in enumerate(cases):
        if i % 100 == 0:
            logger.info("[%s] %d/%d ...", label, i, len(cases))
        hits, ms = engine.search(c.query, _TOP_K)
        passed, recall = evaluate(hits, c)
        all_recall.append(recall)
        all_ms.append(ms)
        results.append({"id": c.id, "cat": c.category, "passed": passed, "recall": recall, "ms": ms})

    total = len(results)
    passed_cnt = sum(1 for r in results if r["passed"])
    sorted_ms = sorted(all_ms)

    # 按分类统计
    cats = {}
    for r in results:
        cats.setdefault(r["cat"], []).append(r)

    return {
        "total": total,
        "passed": passed_cnt,
        "pass_rate": passed_cnt / total,
        "avg_recall": sum(all_recall) / total,
        "p50_ms": sorted_ms[total // 2],
        "p95_ms": sorted_ms[int(total * 0.95)],
        "p99_ms": sorted_ms[int(total * 0.99)],
        "avg_ms": sum(all_ms) / total,
        "by_category": {
            cat: {
                "total": len(rs),
                "passed": sum(1 for r in rs if r["passed"]),
                "rate": round(sum(1 for r in rs if r["passed"]) / len(rs) * 100, 1),
                "avg_recall": round(sum(r["recall"] for r in rs) / len(rs) * 100, 1),
            }
            for cat, rs in sorted(cats.items())
        },
        "details": results,
    }


# ═══════════════════════════════════════════════════════════
# 报告输出
# ═══════════════════════════════════════════════════════════

def print_report(local_r: dict, grep_r: dict, vdb_r: dict | None, n_turns: int, n_cases: int):
    """输出三方对比汇总表"""
    has_vdb = vdb_r is not None

    print(f"\n{'═' * 80}")
    print(f"  📊 1000 条用例三方对比 — {n_turns} 轮种子 × {n_cases} 条用例 (20 客户)")
    print(f"{'═' * 80}")

    # 总览表
    header = f"  ┌{'─' * 28}┬{'─' * 14}┬{'─' * 14}┐"
    if has_vdb:
        header = f"  ┌{'─' * 28}┬{'─' * 14}┬{'─' * 14}┬{'─' * 14}┐"
    print(f"\n{header}")
    if has_vdb:
        print(f"  │ {'指标':<24} │ {'HNSW+Qwen3':^12} │ {'grep+jieba':^12} │ {'VDB+doubao':^12} │")
        print(f"  ├{'─' * 28}┼{'─' * 14}┼{'─' * 14}┼{'─' * 14}┤")
        print(f"  │ {'通过率':<24} │ {local_r['pass_rate']*100:>8.1f}%    │ {grep_r['pass_rate']*100:>8.1f}%    │ {vdb_r['pass_rate']*100:>8.1f}%    │")
        print(f"  │ {'平均召回率':<22} │ {local_r['avg_recall']*100:>8.1f}%    │ {grep_r['avg_recall']*100:>8.1f}%    │ {vdb_r['avg_recall']*100:>8.1f}%    │")
        print(f"  │ {'P50 延迟':<23} │ {local_r['p50_ms']:>8.1f}ms   │ {grep_r['p50_ms']:>8.2f}ms   │ {vdb_r['p50_ms']:>8.1f}ms   │")
        print(f"  │ {'P95 延迟':<23} │ {local_r['p95_ms']:>8.1f}ms   │ {grep_r['p95_ms']:>8.2f}ms   │ {vdb_r['p95_ms']:>8.1f}ms   │")
        print(f"  │ {'P99 延迟':<23} │ {local_r['p99_ms']:>8.1f}ms   │ {grep_r['p99_ms']:>8.2f}ms   │ {vdb_r['p99_ms']:>8.1f}ms   │")
        print(f"  └{'─' * 28}┴{'─' * 14}┴{'─' * 14}┴{'─' * 14}┘")
    else:
        print(f"  │ {'指标':<24} │ {'HNSW+Qwen3':^12} │ {'grep+jieba':^12} │")
        print(f"  ├{'─' * 28}┼{'─' * 14}┼{'─' * 14}┤")
        print(f"  │ {'通过率':<24} │ {local_r['pass_rate']*100:>8.1f}%    │ {grep_r['pass_rate']*100:>8.1f}%    │")
        print(f"  │ {'平均召回率':<22} │ {local_r['avg_recall']*100:>8.1f}%    │ {grep_r['avg_recall']*100:>8.1f}%    │")
        print(f"  │ {'P50 延迟':<23} │ {local_r['p50_ms']:>8.1f}ms   │ {grep_r['p50_ms']:>8.2f}ms   │")
        print(f"  │ {'P95 延迟':<23} │ {local_r['p95_ms']:>8.1f}ms   │ {grep_r['p95_ms']:>8.2f}ms   │")
        print(f"  │ {'P99 延迟':<23} │ {local_r['p99_ms']:>8.1f}ms   │ {grep_r['p99_ms']:>8.2f}ms   │")
        print(f"  └{'─' * 28}┴{'─' * 14}┴{'─' * 14}┘")

    # 分类对比表
    print(f"\n  📋 分类通过率对比:")
    all_cats = sorted(set(
        list(local_r["by_category"].keys()) +
        list(grep_r["by_category"].keys()) +
        (list(vdb_r["by_category"].keys()) if has_vdb else [])
    ))

    if has_vdb:
        print(f"  {'分类':<12} {'HNSW':>8} {'grep':>8} {'VDB':>8} {'HNSW-grep':>10} {'HNSW-VDB':>10}")
        print(f"  {'─' * 62}")
        for cat in all_cats:
            l = local_r["by_category"].get(cat, {}).get("rate", 0)
            g = grep_r["by_category"].get(cat, {}).get("rate", 0)
            v = vdb_r["by_category"].get(cat, {}).get("rate", 0)
            icon = "✅" if l >= g and l >= v else "⚠️"
            print(f"  {icon} {cat:<10} {l:>6.1f}% {g:>6.1f}% {v:>6.1f}% {l-g:>+8.1f}% {l-v:>+8.1f}%")
    else:
        print(f"  {'分类':<12} {'HNSW':>8} {'grep':>8} {'差异':>8}")
        print(f"  {'─' * 44}")
        for cat in all_cats:
            l = local_r["by_category"].get(cat, {}).get("rate", 0)
            g = grep_r["by_category"].get(cat, {}).get("rate", 0)
            icon = "✅" if l >= g else "❌"
            print(f"  {icon} {cat:<10} {l:>6.1f}% {g:>6.1f}% {l-g:>+6.1f}%")

    # 速度对比
    speed_ratio = grep_r["avg_ms"] / max(local_r["avg_ms"], 0.01)
    print(f"\n  ⚡ 速度: grep 平均 {grep_r['avg_ms']:.2f}ms vs HNSW 平均 {local_r['avg_ms']:.1f}ms (grep {'快' if speed_ratio < 1 else '慢'} {abs(1-speed_ratio)*100:.0f}%)")
    if has_vdb:
        vdb_ratio = vdb_r["avg_ms"] / max(local_r["avg_ms"], 0.01)
        print(f"  ⚡ 速度: VDB 平均 {vdb_r['avg_ms']:.1f}ms vs HNSW 平均 {local_r['avg_ms']:.1f}ms (VDB 慢 {(vdb_ratio-1)*100:.0f}%)")

    print(f"\n{'═' * 80}\n")


def compute_diff(local_r: dict, grep_r: dict, vdb_r: dict | None) -> dict:
    """计算方案差异"""
    local_details = {r["id"]: r["passed"] for r in local_r["details"]}
    grep_details = {r["id"]: r["passed"] for r in grep_r["details"]}

    only_local_fail = [cid for cid, p in local_details.items() if not p and grep_details.get(cid, False)]
    only_grep_fail = [cid for cid, p in grep_details.items() if not p and local_details.get(cid, False)]
    both_fail = [cid for cid, p in local_details.items() if not p and not grep_details.get(cid, True)]

    diff = {
        "only_local_fail": sorted(only_local_fail),
        "only_grep_fail": sorted(only_grep_fail),
        "both_fail": sorted(both_fail),
    }

    if vdb_r:
        vdb_details = {r["id"]: r["passed"] for r in vdb_r["details"]}
        diff["only_vdb_fail"] = sorted(
            cid for cid, p in vdb_details.items() if not p and local_details.get(cid, False)
        )

    return diff


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="1000 条用例三方对比验证")
    parser.add_argument("--no-vdb", action="store_true", help="跳过 VDB 方案 (无需远程依赖)")
    parser.add_argument("--no-local", action="store_true", help="跳过 Local HNSW 方案 (无需 torch)")
    parser.add_argument("--top-k", type=int, default=5, help="检索 top_k (default: 5)")
    parser.add_argument("--save", type=str, default="data/eval/runs/1000cases_benchmark.json", help="结果保存路径")
    args = parser.parse_args()

    global _TOP_K
    _TOP_K = args.top_k

    # 加载数据
    logger.info("Loading seed data & cases...")
    seed = build_1000_seed()
    cases = build_1000_cases()
    logger.info("Data: %d turns | Cases: %d", len(seed), len(cases))

    print(f"\n🚀 1000 条用例三方对比验证")
    print(f"   {len(seed)} 轮种子 × {len(cases)} 条用例 | 15 客户 | 12 类场景")
    print(f"   top_k={_TOP_K} | VDB={'ON' if not args.no_vdb else 'OFF'} | Local={'ON' if not args.no_local else 'OFF'}\n")

    local_r = None
    vdb_r = None

    # ════ 方案 A: SQLite+HNSW+Qwen3 ════
    if not args.no_local:
        logger.info("=== [A] SQLite+HNSW+Qwen3 ===")
        local = LocalEngine()
        local.write(seed)

    # ════ 方案 B: grep+jieba (原始) ════
    logger.info("=== [B] grep+jieba (原始) ===")
    grep = GrepEngine()
    grep.write(seed)

    # ════ 方案 B+: grep 优化版 ════
    logger.info("=== [B+] grep 优化版 (IDF+实体优先) ===")
    grep_v2 = GrepEngineV2()
    grep_v2.write(seed)

    # ════ 方案 C: VDB+doubao (可选) ════
    if not args.no_vdb:
        try:
            logger.info("=== [C] VDB+doubao ===")
            vdb = VDBEngine()
            vdb.write(seed)
            logger.info("=== Eval VDB ===")
            vdb_r = run_eval(vdb, cases, "VDB")
        except Exception as e:
            logger.warning("VDB unavailable, skipping: %s", e)

    # ════ 评测 ════
    if not args.no_local:
        logger.info("=== Eval Local ===")
        local_r = run_eval(local, cases, "Local")

    logger.info("=== Eval grep (原始) ===")
    grep_r = run_eval(grep, cases, "grep")

    logger.info("=== Eval grep V2 (优化) ===")
    grep_v2_r = run_eval(grep_v2, cases, "grepV2")

    # ════ 报告: grep 原始 vs grep 优化 ════
    print(f"\n{'═' * 80}")
    print(f"  📊 grep 优化对比 — {len(seed)} 轮 × {len(cases)} 用例")
    print(f"{'═' * 80}")

    print(f"\n  ┌{'─' * 28}┬{'─' * 14}┬{'─' * 14}┬{'─' * 14}┐")
    cols = "grep原始", "grep优化", "提升"
    print(f"  │ {'指标':<24} │ {cols[0]:^12} │ {cols[1]:^12} │ {cols[2]:^12} │")
    print(f"  ├{'─' * 28}┼{'─' * 14}┼{'─' * 14}┼{'─' * 14}┤")
    delta_pass = (grep_v2_r['pass_rate'] - grep_r['pass_rate']) * 100
    delta_recall = (grep_v2_r['avg_recall'] - grep_r['avg_recall']) * 100
    print(f"  │ {'通过率':<24} │ {grep_r['pass_rate']*100:>8.1f}%    │ {grep_v2_r['pass_rate']*100:>8.1f}%    │ {delta_pass:>+8.1f}%    │")
    print(f"  │ {'平均召回率':<22} │ {grep_r['avg_recall']*100:>8.1f}%    │ {grep_v2_r['avg_recall']*100:>8.1f}%    │ {delta_recall:>+8.1f}%    │")
    print(f"  │ {'P50 延迟':<23} │ {grep_r['p50_ms']:>8.2f}ms   │ {grep_v2_r['p50_ms']:>8.2f}ms   │ {'':12} │")
    print(f"  │ {'P95 延迟':<23} │ {grep_r['p95_ms']:>8.2f}ms   │ {grep_v2_r['p95_ms']:>8.2f}ms   │ {'':12} │")
    print(f"  └{'─' * 28}┴{'─' * 14}┴{'─' * 14}┴{'─' * 14}┘")

    # 分类对比
    print(f"\n  📋 分类通过率 (grep原始 vs grep优化):")
    all_cats = sorted(set(list(grep_r["by_category"].keys()) + list(grep_v2_r["by_category"].keys())))
    print(f"  {'分类':<12} {'原始':>8} {'优化':>8} {'提升':>8}")
    print(f"  {'─' * 40}")
    for cat in all_cats:
        g1 = grep_r["by_category"].get(cat, {}).get("rate", 0)
        g2 = grep_v2_r["by_category"].get(cat, {}).get("rate", 0)
        icon = "✅" if g2 > g1 else ("➖" if g2 == g1 else "❌")
        print(f"  {icon} {cat:<10} {g1:>6.1f}% {g2:>6.1f}% {g2-g1:>+6.1f}%")

    # ════ 全方案总览 (如果有 local) ════
    if local_r:
        print(f"\n{'═' * 80}")
        print(f"  📊 全方案总览")
        print(f"{'═' * 80}")
        print_report(local_r, grep_r, vdb_r, len(seed), len(cases))

        # 加入 grep_v2 和 local 的对比
        print(f"  🆚 grep优化 vs HNSW+Qwen3:")
        print(f"     grep优化: {grep_v2_r['pass_rate']*100:.1f}% | HNSW: {local_r['pass_rate']*100:.1f}% | 差距: {(grep_v2_r['pass_rate']-local_r['pass_rate'])*100:+.1f}%")
        print()

    # ════ 差异分析 ════
    diff_v2 = compute_diff(grep_v2_r, grep_r, None)
    print(f"  🔍 grep 优化 vs 原始 差异:")
    print(f"     优化后新增通过: {len(diff_v2['only_local_fail'])} 条")  # 注: local_fail 在这里是 grep_v2 fail
    print(f"     优化后新增失败: {len(diff_v2['only_grep_fail'])} 条")
    # 反向: grep_v2 通过但 grep 失败的
    v2_details = {r["id"]: r["passed"] for r in grep_v2_r["details"]}
    g1_details = {r["id"]: r["passed"] for r in grep_r["details"]}
    v2_gained = [cid for cid, p in v2_details.items() if p and not g1_details.get(cid, False)]
    v2_lost = [cid for cid, p in v2_details.items() if not p and g1_details.get(cid, False)]
    print(f"     优化新增通过 (gained): {len(v2_gained)} 条")
    print(f"     优化新增失败 (lost): {len(v2_lost)} 条")
    print(f"     净提升: {len(v2_gained) - len(v2_lost):+d} 条")

    # ════ 保存结果 ════
    local_save = {k: v for k, v in local_r.items() if k != "details"} if local_r else None
    grep_save = {k: v for k, v in grep_r.items() if k != "details"}
    grep_v2_save = {k: v for k, v in grep_v2_r.items() if k != "details"}
    output = {
        "config": {
            "seed_count": len(seed),
            "case_count": len(cases),
            "top_k": _TOP_K,
            "local_model": "Qwen3-Embedding-0.6B",
            "grep_engine": "jieba+bigram+field_weight",
            "grep_v2_engine": "jieba+idf+entity_priority+biz_stops",
        },
        "grep": grep_save,
        "grep_v2": grep_v2_save,
        "grep_improvement": {
            "pass_rate_delta": round(delta_pass, 2),
            "recall_delta": round(delta_recall, 2),
            "gained": len(v2_gained),
            "lost": len(v2_lost),
            "net": len(v2_gained) - len(v2_lost),
        },
    }
    if local_save:
        output["local"] = local_save
    if vdb_r:
        vdb_save = {k: v for k, v in vdb_r.items() if k != "details"}
        output["vdb"] = vdb_save

    os.makedirs(os.path.dirname(args.save), exist_ok=True)
    with open(args.save, "w", encoding="utf-8") as fp:
        json.dump(output, fp, ensure_ascii=False, indent=2)
    print(f"\n  💾 结果已保存: {args.save}")
    print()


if __name__ == "__main__":
    main()
