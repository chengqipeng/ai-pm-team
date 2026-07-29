"""检索准确率验证 — jieba 分词 vs N-gram 分词

在 SQLite+HNSW+Qwen3 方案中，对比 BM25 稀疏路的分词策略：
  A. N-gram（当前方案）：2/3字滑动窗口，无词典
  B. jieba：词典分词，语义切分

相同的 Dense 路（Qwen3 HNSW），只替换 Sparse 路的分词方式。
190 条用例，输出准确率差异。

运行：python demo_recall_jieba.py
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

import jieba
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

_HNSW_M, _HNSW_EF_C, _HNSW_EF_S = 16, 200, 100
_RRF_K = 60
_TOP_K = 5

# 预热 jieba（避免首次分词计入延迟）
jieba.initialize()

# ═══════════════════════════════════════════════════════════
# 数据
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
    return (
        f"{turn['user_query']} {turn['answer_preview']} "
        f"{turn['entities_text']} {turn['keywords']} "
        f"{turn.get('tool_names', '')} {turn.get('biz_object', '')}"
    )[:800]


# ═══════════════════════════════════════════════════════════
# 两种分词策略
# ═══════════════════════════════════════════════════════════

_STOPS = {"什么", "怎么", "哪个", "哪些", "有没有", "帮我", "请问", "一下", "可以",
          "能否", "这个", "那个", "就是", "不是", "怎么样", "多少", "现在", "上次",
          "之前", "所有", "相关", "什么时", "的", "了", "是", "在", "有", "和",
          "与", "或", "也", "都", "就", "把", "被", "给", "让", "从", "到",
          "对", "向", "着", "过", "吗", "呢", "啊", "吧", "呀", "嘛", "哦"}


def tokenize_ngram(text: str) -> list[str]:
    """N-gram 分词（当前方案）"""
    cn = re.findall(r'[\u4e00-\u9fff]+', text)
    en = re.findall(r'[a-zA-Z0-9$¥_-]+', text)
    words = []
    for s in cn:
        if len(s) <= 4:
            words.append(s)
        else:
            for i in range(len(s) - 1): words.append(s[i:i+2])
            for i in range(len(s) - 2): words.append(s[i:i+3])
    return list(set(w for w in words + en if w not in _STOPS and len(w) >= 2))


def tokenize_jieba(text: str) -> list[str]:
    """jieba 分词"""
    words = jieba.cut(text, cut_all=False)
    en = re.findall(r'[a-zA-Z0-9$¥_-]+', text)
    all_words = list(words) + en
    return list(set(w for w in all_words if w not in _STOPS and len(w) >= 2))


# ═══════════════════════════════════════════════════════════
# 检索引擎（参数化分词策略）
# ═══════════════════════════════════════════════════════════

class SearchEngine:
    """SQLite+HNSW+Qwen3，可切换分词策略"""

    def __init__(self, tokenizer_fn, label: str):
        from src.embedding import LocalEmbedding
        self._emb = LocalEmbedding()
        self._tokenizer = tokenizer_fn
        self._label = label
        self._conn = sqlite3.connect(":memory:")
        self._hnsw = None
        self._id_map: dict[int, int] = {}
        # FTS5 用 unicode61 tokenizer（实际匹配靠我们外部构造 MATCH 查询）
        self._conn.executescript("""
            CREATE TABLE turns(turn_id INT PRIMARY KEY, text TEXT);
            CREATE VIRTUAL TABLE turns_fts USING fts5(text, content='turns', content_rowid='turn_id', tokenize='unicode61');
            CREATE TRIGGER ti AFTER INSERT ON turns BEGIN
                INSERT INTO turns_fts(rowid, text) VALUES(new.turn_id, new.text);
            END;
        """)

    def write(self, turns: list[dict]):
        texts = [build_embed_text(t) for t in turns]
        # 向量
        vecs = self._emb.embed_documents_np(texts)
        # SQLite（写入原文，FTS5 建索引）
        for i, turn in enumerate(turns):
            self._conn.execute("INSERT INTO turns VALUES(?,?)", (turn["turn_id"], texts[i]))
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
        logger.info("[%s] Written %d turns", self._label, len(turns))

    def search(self, query: str, top_k: int = _TOP_K) -> tuple[list[int], float]:
        t0 = time.time()
        # Dense
        qv = self._emb.embed_query_np(query)
        labels, dists = self._hnsw.knn_query(np.array([qv], dtype=np.float32), k=min(top_k*3, 30))
        dense = [(self._id_map[int(l)], 1.0-d) for l, d in zip(labels[0], dists[0])]
        # Sparse（使用指定的分词器）
        kws = self._tokenizer(query)
        sparse = self._fts_search(kws, top_k * 3)
        # RRF
        scores: dict[int, float] = {}
        for rank, (tid, _) in enumerate(dense, 1):
            scores[tid] = scores.get(tid, 0) + 1.0/(_RRF_K+rank)
        for rank, (tid, _) in enumerate(sparse, 1):
            scores[tid] = scores.get(tid, 0) + 1.0/(_RRF_K+rank)
        result = sorted(scores, key=lambda t: -scores[t])[:top_k]
        ms = (time.time()-t0)*1000
        return result, ms

    def _fts_search(self, keywords: list[str], top_k: int) -> list[tuple[int, float]]:
        if not keywords:
            return []
        fts_q = " OR ".join(f'"{w}"' for w in keywords[:15])  # 限制关键词数避免 FTS5 过长
        try:
            rows = self._conn.execute(
                "SELECT t.turn_id, rank FROM turns_fts "
                "JOIN turns t ON turns_fts.rowid=t.turn_id "
                "WHERE turns_fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_q, top_k)).fetchall()
            return [(r[0], abs(r[1])) for r in rows]
        except Exception:
            return []


# ═══════════════════════════════════════════════════════════
# 评测
# ═══════════════════════════════════════════════════════════

def evaluate(hits: list[int], case: Case) -> tuple[bool, float]:
    if case.expect_no_hit:
        passed = not any(t in (case.expected_turns or []) for t in hits)
        return passed, 1.0 if passed else 0.0
    if not case.expected_turns:
        return len(hits) > 0, 1.0 if hits else 0.0
    exp = set(case.expected_turns)
    hit = set(hits)
    recall = len(exp & hit) / max(len(exp), 1)
    return recall >= 0.3, recall


def run_eval(engine: SearchEngine, cases: list[Case], label: str) -> dict:
    results = []
    all_recall, all_ms = [], []
    for i, case in enumerate(cases):
        if i % 50 == 0:
            logger.info("[%s] Progress: %d/%d", label, i, len(cases))
        hits, ms = engine.search(case.query, top_k=_TOP_K)
        passed, recall = evaluate(hits, case)
        all_recall.append(recall)
        all_ms.append(ms)
        results.append({"id": case.id, "cat": case.category, "passed": passed,
                        "recall": recall, "query": case.query,
                        "expected": case.expected_turns, "hit": hits})

    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    cats = {}
    for r in results:
        cats.setdefault(r["cat"], []).append(r)
    sorted_ms = sorted(all_ms)

    return {
        "total": total,
        "passed": passed_count,
        "pass_rate": round(passed_count / total, 4),
        "avg_recall": round(sum(all_recall) / total, 4),
        "p50_ms": round(sorted_ms[total//2], 1),
        "avg_ms": round(sum(all_ms) / total, 1),
        "by_category": {
            cat: {"total": len(rs), "passed": sum(1 for r in rs if r["passed"]),
                  "rate": round(sum(1 for r in rs if r["passed"]) / len(rs), 4)}
            for cat, rs in cats.items()},
        "results": results,
    }


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

def main():
    seed_data = build_seed_conversation_data()
    cases = [c for c in _load_cases() if c.mode != "full"]
    logger.info("Data: %d turns | Cases: %d", len(seed_data), len(cases))

    print(f"\n🚀 BM25 分词策略对比：N-gram vs jieba")
    print(f"   相同: Qwen3-0.6B + HNSW + RRF (k=60) + top_k=5")
    print(f"   不同: FTS5 查询时的分词方式\n")

    # 方案 A: N-gram
    logger.info("=== 构建 N-gram 引擎 ===")
    ngram_engine = SearchEngine(tokenize_ngram, "N-gram")
    ngram_engine.write(seed_data)

    # 方案 B: jieba（共享同一份 embedding，只需重建 SQLite）
    logger.info("=== 构建 jieba 引擎 ===")
    jieba_engine = SearchEngine(tokenize_jieba, "jieba")
    jieba_engine.write(seed_data)

    # 评测
    logger.info("=== 评测 N-gram ===")
    ngram_eval = run_eval(ngram_engine, cases, "N-gram")

    logger.info("=== 评测 jieba ===")
    jieba_eval = run_eval(jieba_engine, cases, "jieba")

    # 报告
    print(f"\n{'═'*68}")
    print(f"  BM25 分词策略对比 — N-gram vs jieba")
    print(f"  {len(cases)} 条用例 | Dense 路完全相同 | 只有 Sparse 分词不同")
    print(f"{'═'*68}")

    print(f"\n── 总体对比 ──────────────────────────────────────────")
    print(f"  ┌────────────────────┬──────────────┬──────────────┐")
    print(f"  │ 指标               │ N-gram       │ jieba        │")
    print(f"  ├────────────────────┼──────────────┼──────────────┤")
    print(f"  │ 通过率             │ {ngram_eval['pass_rate']*100:>6.1f}%     │ {jieba_eval['pass_rate']*100:>6.1f}%     │")
    print(f"  │ 平均召回率         │ {ngram_eval['avg_recall']*100:>6.1f}%     │ {jieba_eval['avg_recall']*100:>6.1f}%     │")
    print(f"  │ 检索延迟 P50       │ {ngram_eval['p50_ms']:>6.1f}ms     │ {jieba_eval['p50_ms']:>6.1f}ms     │")
    print(f"  └────────────────────┴──────────────┴──────────────┘")

    # 按分类
    print(f"\n── 按分类 ────────────────────────────────────────────")
    print(f"  {'分类':<8} {'N-gram':>8} {'jieba':>8} {'差异':>8}")
    print(f"  {'─'*40}")
    all_cats = sorted(set(list(ngram_eval["by_category"].keys()) + list(jieba_eval["by_category"].keys())))
    for cat in all_cats:
        n = ngram_eval["by_category"].get(cat, {})
        j = jieba_eval["by_category"].get(cat, {})
        nr = n.get("rate", 0) * 100
        jr = j.get("rate", 0) * 100
        diff = jr - nr
        icon = "✅" if abs(diff) < 1 else ("📈" if diff > 0 else "📉")
        print(f"  {icon} {cat:<7} {nr:>6.1f}% {jr:>6.1f}% {diff:>+6.1f}%")

    # 差异用例
    ngram_fails = set(r["id"] for r in ngram_eval["results"] if not r["passed"])
    jieba_fails = set(r["id"] for r in jieba_eval["results"] if not r["passed"])
    only_ngram_fail = ngram_fails - jieba_fails
    only_jieba_fail = jieba_fails - ngram_fails

    print(f"\n── 差异分析 ──────────────────────────────────────────")
    print(f"  N-gram 失败但 jieba 通过: {len(only_ngram_fail)} 条")
    print(f"  jieba 失败但 N-gram 通过: {len(only_jieba_fail)} 条")
    print(f"  两者都失败:              {len(ngram_fails & jieba_fails)} 条")

    if only_ngram_fail:
        print(f"\n  jieba 修复的用例（N-gram 失败 → jieba 通过）:")
        for fid in sorted(only_ngram_fail):
            r = next(r for r in ngram_eval["results"] if r["id"] == fid)
            print(f"    {fid} [{r['cat']}] {r['query'][:40]}")

    if only_jieba_fail:
        print(f"\n  jieba 引入的退化（jieba 失败 → N-gram 通过）:")
        for fid in sorted(only_jieba_fail):
            r = next(r for r in jieba_eval["results"] if r["id"] == fid)
            print(f"    {fid} [{r['cat']}] {r['query'][:40]}")

    # 分词对比示例
    print(f"\n── 分词对比示例 ──────────────────────────────────────")
    samples = ["华为报价是多少", "PT Sentosa 客户信息", "哪些客户的报价超过¥100万", "还在谈判的客户", "竞品对比"]
    for s in samples:
        ng = tokenize_ngram(s)
        jb = tokenize_jieba(s)
        print(f"  \"{s}\"")
        print(f"    N-gram: {sorted(ng)[:8]}")
        print(f"    jieba:  {sorted(jb)[:8]}")
        print()

    print(f"{'═'*68}\n")

    # 保存
    out_path = "data/eval/runs/recall_jieba_vs_ngram.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump({
            "ngram": {k: v for k, v in ngram_eval.items() if k != "results"},
            "jieba": {k: v for k, v in jieba_eval.items() if k != "results"},
            "diff": {"only_ngram_fail": sorted(only_ngram_fail),
                     "only_jieba_fail": sorted(only_jieba_fail)},
        }, fp, ensure_ascii=False, indent=2)
    print(f"  📊 保存: {out_path}")


if __name__ == "__main__":
    main()
