"""检索准确率对比 — 当前 recall 逻辑 vs 纯 grep 模式

方案 A (当前 recall): ContextArchive.hybrid_search()
  → doubao embedding + VDB hybrid (dense 0.6 + BM25 0.4) + score 阈值 + 邻轮扩展

方案 B (grep 模式): 纯关键词 LIKE 匹配
  → 提取 query 中的关键词 → 逐条 LIKE '%keyword%' → 计数排序

190 条用例，相同数据，对比准确率差异。

运行：python demo_recall_vs_grep.py
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

_TOP_K = 5

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


def build_search_text(turn: dict) -> str:
    """构造可搜索的全文"""
    return (
        f"{turn['user_query']} {turn['answer_preview']} "
        f"{turn['entities_text']} {turn['keywords']} "
        f"{turn.get('tool_names', '')} {turn.get('biz_object', '')}"
    ).lower()


# ═══════════════════════════════════════════════════════════
# 方案 B: grep 模式（纯关键词 LIKE 匹配）
# ═══════════════════════════════════════════════════════════

class GrepEngine:
    """纯 grep/LIKE 关键词匹配 — 最简单的基线"""

    def __init__(self):
        self._turns: list[dict] = []
        self._texts: dict[int, str] = {}  # turn_id → 可搜索全文

    def write(self, turns: list[dict]):
        self._turns = turns
        for turn in turns:
            self._texts[turn["turn_id"]] = build_search_text(turn)

    def search(self, query: str, top_k: int = _TOP_K) -> tuple[list[int], float]:
        """纯关键词 LIKE 匹配 — 等同于 PG ILIKE 降级模式"""
        t0 = time.time()
        keywords = self._extract_keywords(query)
        if not keywords:
            return [], (time.time() - t0) * 1000

        # 逐条匹配，计算命中关键词数
        scored = []
        for tid, text in self._texts.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scored.append((tid, score))

        # 按命中数降序
        scored.sort(key=lambda x: -x[1])
        result = [tid for tid, _ in scored[:top_k]]
        ms = (time.time() - t0) * 1000
        return result, ms

    @staticmethod
    def _extract_keywords(query: str) -> list[str]:
        """简单分词 — 模拟 PG search_by_keywords 的逻辑"""
        query_lower = query.lower()
        # 英文单词
        en = re.findall(r'[a-zA-Z0-9$¥_-]+', query_lower)
        # 中文：按 2-4 字切分
        cn = re.findall(r'[\u4e00-\u9fff]+', query_lower)
        cn_words = []
        for seg in cn:
            if len(seg) <= 4:
                cn_words.append(seg)
            else:
                for i in range(len(seg) - 1):
                    cn_words.append(seg[i:i+2])
                for i in range(len(seg) - 2):
                    cn_words.append(seg[i:i+3])

        stops = {"什么", "怎么", "哪个", "哪些", "有没有", "帮我", "请问", "一下",
                 "可以", "能否", "这个", "那个", "就是", "不是", "怎么样", "多少",
                 "现在", "上次", "之前", "所有", "相关", "什么时", "哪次"}
        return list(set(w for w in cn_words + en if w not in stops and len(w) >= 2))


# ═══════════════════════════════════════════════════════════
# 方案 A: 当前 recall 逻辑（VDB hybrid_search）
# ═══════════════════════════════════════════════════════════

class CurrentRecallEngine:
    """VDB hybrid_search — 使用 Qwen3-0.6B 本地 Embedding 替代 doubao"""

    def __init__(self):
        from src.embedding import LocalEmbedding
        from src.memory.viking_engine import VectorStore

        _VDB_URL = os.environ.get("TENCENT_VDB_URL", "http://10.60.2.17")
        _VDB_KEY = os.environ.get("TENCENT_VDB_KEY", "bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck")

        self._vdb = VectorStore(
            url=_VDB_URL, key=_VDB_KEY, username="root",
            database_name="viking_memory", collection_name="archive_qwen3_eval",
            embedding_dims=1024,
        )
        self._embedding = LocalEmbedding()
        logger.info("[VDB+Qwen3] Engine ready")

    def write(self, turns: list[dict]):
        """写入 VDB（Qwen3 本地 embedding + 全字段 BM25）"""
        records = []
        texts = []
        for turn in turns:
            full_text = (
                f"{turn['user_query']} {turn['answer_preview']} "
                f"{turn['entities_text']} {turn['keywords']} "
                f"{turn.get('tool_names', '')} {turn.get('biz_object', '')}"
            )[:800]
            texts.append(full_text)

        # 批量 embedding
        import numpy as np
        vecs = self._embedding.embed_documents_np(texts)

        for i, turn in enumerate(turns):
            tid = turn["turn_id"]
            records.append({
                "id": f"eval_archive_turn_{tid}",
                "vector": vecs[i].tolist(),
                "tenant_id": "eval",
                "thread_id": "eval_session_001",
                "turn_id": str(tid),
                "has_decision": "0",
                "user_query": turn["user_query"][:500],
                "answer_preview": turn["answer_preview"][:500],
                "entities_text": turn.get("entities_text", "")[:300],
                "tool_names_text": turn.get("tool_names", "")[:200],
                "abstract": texts[i],
                "keywords_json": turn.get("keywords", ""),
            })
        self._vdb.upsert(records)
        logger.info("[VDB+Qwen3] Written %d turns", len(turns))

    def search(self, query: str, top_k: int = _TOP_K) -> tuple[list[int], float]:
        """hybrid_search (dense 0.4 + BM25 0.6) with Qwen3 embedding"""
        t0 = time.time()
        query_vec = self._embedding.embed_query(query)
        filter_expr = 'thread_id = "eval_session_001"'
        results = self._vdb.hybrid_search(
            vector=query_vec, query_text=query,
            top_k=top_k * 3,
            filter_expr=filter_expr,
            dense_weight=0.4,
            sparse_weight=0.6,
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


def run_eval(engine, cases: list[Case], label: str) -> dict:
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
        "p50_ms": round(sorted_ms[total // 2], 2),
        "avg_ms": round(sum(all_ms) / total, 2),
        "by_category": {
            cat: {"total": len(rs), "passed": sum(1 for r in rs if r["passed"]),
                  "rate": round(sum(1 for r in rs if r["passed"]) / len(rs), 4)}
            for cat, rs in cats.items()},
        "results": results,
    }


# ═══════════════════════════════════════════════════════════
# 报告
# ═══════════════════════════════════════════════════════════

def print_report(recall_eval: dict, grep_eval: dict):
    print(f"\n{'═'*68}")
    print(f"  检索准确率对比 — 当前 recall (VDB hybrid) vs grep (LIKE 匹配)")
    print(f"  {recall_eval['total']} 条用例 | top_k={_TOP_K}")
    print(f"{'═'*68}")

    print(f"\n── 总体 ──────────────────────────────────────────────")
    print(f"  ┌────────────────────┬───────────────────┬──────────────────┐")
    print(f"  │ 指标               │ 当前 recall (VDB) │ grep (LIKE)      │")
    print(f"  ├────────────────────┼───────────────────┼──────────────────┤")
    print(f"  │ 通过率             │ {recall_eval['pass_rate']*100:>7.1f}%        │ {grep_eval['pass_rate']*100:>7.1f}%       │")
    print(f"  │ 平均召回率         │ {recall_eval['avg_recall']*100:>7.1f}%        │ {grep_eval['avg_recall']*100:>7.1f}%       │")
    print(f"  │ P50 延迟           │ {recall_eval['p50_ms']:>7.1f}ms        │ {grep_eval['p50_ms']:>7.2f}ms       │")
    print(f"  └────────────────────┴───────────────────┴──────────────────┘")

    print(f"\n── 按分类 ────────────────────────────────────────────")
    print(f"  {'分类':<8} {'recall':>8} {'grep':>8} {'差异':>8}")
    print(f"  {'─'*40}")
    all_cats = sorted(set(list(recall_eval["by_category"].keys()) + list(grep_eval["by_category"].keys())))
    for cat in all_cats:
        r = recall_eval["by_category"].get(cat, {})
        g = grep_eval["by_category"].get(cat, {})
        rr = r.get("rate", 0) * 100
        gr = g.get("rate", 0) * 100
        diff = rr - gr
        icon = "✅" if diff > 0 else ("⚠️" if diff == 0 else "❌")
        print(f"  {icon} {cat:<7} {rr:>6.1f}% {gr:>6.1f}% {diff:>+6.1f}%")

    # 差异分析
    recall_fails = set(r["id"] for r in recall_eval["results"] if not r["passed"])
    grep_fails = set(r["id"] for r in grep_eval["results"] if not r["passed"])
    only_recall_fail = recall_fails - grep_fails
    only_grep_fail = grep_fails - recall_fails
    both_fail = recall_fails & grep_fails

    print(f"\n── 差异分析 ──────────────────────────────────────────")
    print(f"  仅 recall 失败 (VDB 不如 grep):  {len(only_recall_fail)} 条")
    print(f"  仅 grep 失败 (recall 优于 grep): {len(only_grep_fail)} 条")
    print(f"  两者都失败:                      {len(both_fail)} 条")

    if only_recall_fail:
        print(f"\n  VDB recall 不如 grep 的用例:")
        for fid in sorted(only_recall_fail)[:8]:
            r = next(x for x in recall_eval["results"] if x["id"] == fid)
            print(f"    {fid} [{r['cat']}] {r['query'][:35]}")

    if only_grep_fail:
        print(f"\n  VDB recall 优于 grep 的用例 (前 8 条):")
        for fid in sorted(only_grep_fail)[:8]:
            r = next(x for x in grep_eval["results"] if x["id"] == fid)
            print(f"    {fid} [{r['cat']}] {r['query'][:35]}")

    print(f"\n{'═'*68}\n")


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

def main():
    seed_data = build_seed_conversation_data()
    cases = [c for c in _load_cases() if c.mode != "full"]
    logger.info("Data: %d turns | Cases: %d", len(seed_data), len(cases))

    print(f"\n🚀 recall vs grep 对比")
    print(f"   方案 A: VDB hybrid_search (Qwen3 embed + dense 0.4 + BM25 0.6)")
    print(f"   方案 B: grep — 纯关键词 LIKE 计数排序")
    print(f"   用例: {len(cases)} 条 | top_k={_TOP_K}\n")

    # grep
    logger.info("=== 初始化 grep 引擎 ===")
    grep_engine = GrepEngine()
    grep_engine.write(seed_data)

    # VDB recall
    logger.info("=== 初始化 VDB recall 引擎 ===")
    recall_engine = CurrentRecallEngine()
    recall_engine.write(seed_data)

    # 评测 grep
    logger.info("=== 评测 grep ===")
    grep_eval = run_eval(grep_engine, cases, "grep")
    print(f"  [grep] 通过率: {grep_eval['pass_rate']*100:.1f}%")

    # 评测 recall
    logger.info("=== 评测 recall ===")
    recall_eval = run_eval(recall_engine, cases, "recall")
    print(f"  [recall] 通过率: {recall_eval['pass_rate']*100:.1f}%")

    # 报告
    print_report(recall_eval, grep_eval)

    # 保存
    out_path = "data/eval/runs/recall_vs_grep.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump({
            "recall_vdb": {k: v for k, v in recall_eval.items() if k != "results"},
            "grep": {k: v for k, v in grep_eval.items() if k != "results"},
        }, fp, ensure_ascii=False, indent=2)
    print(f"  📊 保存: {out_path}")


if __name__ == "__main__":
    main()
