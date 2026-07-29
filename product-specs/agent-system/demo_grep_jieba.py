"""grep + jieba + 字段加权 对比验证

方案 A: grep N-gram（当前基线 87.9%）
方案 B: grep jieba + 字段加权

190 条用例，相同数据。

运行：python demo_grep_jieba.py
"""
from __future__ import annotations

import json, logging, os, re, sys, time
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

import jieba
jieba.initialize()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

_TOP_K = 5

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

def _load_cases():
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

# ═══════════════════════════════════════════════════════════
# 停用词
# ═══════════════════════════════════════════════════════════

_STOPS = frozenset(
    "的 了 在 是 我 有 和 就 不 人 都 一 上 也 很 到 说 要 去 你 会 着 没有 看 好 "
    "自己 这 他 她 它 们 那 些 什么 怎么 哪个 哪些 为什么 可以 能 吗 呢 吧 啊 哦 "
    "帮 帮我 一下 下 把 被 让 给 从 对 但 而 如果 因为 所以 虽然 然后 还 又 再 已经 "
    "做 多少 现在 上次 之前 所有 相关 有没有 是否 需要 请问 能否 还是 以及 "
    "这个 那个 就是 不是 怎么样 到底 什么时候".split()
)

# ═══════════════════════════════════════════════════════════
# 方案 A: N-gram grep（当前基线）
# ═══════════════════════════════════════════════════════════

class GrepNgram:
    def __init__(self):
        self._turns = {}
        self._texts = {}

    def write(self, turns):
        for t in turns:
            tid = t["turn_id"]
            self._turns[tid] = t
            self._texts[tid] = (
                f"{t['user_query']} {t['answer_preview']} "
                f"{t['entities_text']} {t['keywords']} "
                f"{t.get('tool_names', '')} {t.get('biz_object', '')}"
            ).lower()

    def search(self, query, top_k=_TOP_K):
        t0 = time.time()
        kws = self._tokenize(query)
        scored = []
        for tid, text in self._texts.items():
            score = sum(1 for kw in kws if kw in text)
            if score > 0:
                scored.append((tid, score))
        scored.sort(key=lambda x: -x[1])
        ms = (time.time() - t0) * 1000
        return [tid for tid, _ in scored[:top_k]], ms

    @staticmethod
    def _tokenize(text):
        text = text.lower()
        cn = re.findall(r'[\u4e00-\u9fff]+', text)
        en = re.findall(r'[a-zA-Z0-9$¥_-]+', text)
        words = []
        for s in cn:
            if len(s) <= 4:
                words.append(s)
            else:
                for i in range(len(s)-1): words.append(s[i:i+2])
                for i in range(len(s)-2): words.append(s[i:i+3])
        return list(set(w for w in words + en if w not in _STOPS and len(w) >= 2))


# ═══════════════════════════════════════════════════════════
# 方案 B: jieba + 字段加权
# ═══════════════════════════════════════════════════════════

class GrepJieba:
    def __init__(self):
        self._turns = {}
        self._fields = {}  # tid → {entities, user_query, keywords, tools, answer}

    def write(self, turns):
        for t in turns:
            tid = t["turn_id"]
            self._turns[tid] = t
            self._fields[tid] = {
                "entities": t["entities_text"].lower(),
                "user_query": t["user_query"].lower(),
                "keywords": t["keywords"].lower(),
                "tools": t.get("tool_names", "").lower(),
                "biz": t.get("biz_object", "").lower(),
                "answer": t["answer_preview"].lower(),
            }

    def search(self, query, top_k=_TOP_K):
        t0 = time.time()
        kws = self._tokenize(query)
        scored = []
        for tid, fields in self._fields.items():
            score = 0
            for kw in kws:
                if kw in fields["entities"]:   score += 3
                if kw in fields["user_query"]: score += 2
                if kw in fields["keywords"]:   score += 2
                if kw in fields["tools"]:      score += 2
                if kw in fields["biz"]:        score += 2
                if kw in fields["answer"]:     score += 1
            if score > 0:
                scored.append((tid, score))
        scored.sort(key=lambda x: -x[1])
        ms = (time.time() - t0) * 1000
        return [tid for tid, _ in scored[:top_k]], ms

    @staticmethod
    def _tokenize(text):
        text = text.lower()
        # jieba 分词
        words = list(jieba.cut(text, cut_all=False))
        # 英文/数字单独提取（jieba 可能切不好英文）
        en = re.findall(r'[a-zA-Z0-9$¥_-]+', text)
        all_words = words + en
        return list(set(w for w in all_words if w not in _STOPS and len(w) >= 2))


# ═══════════════════════════════════════════════════════════
# 评测
# ═══════════════════════════════════════════════════════════

def evaluate(hits, case):
    if case.expect_no_hit:
        passed = not any(t in (case.expected_turns or []) for t in hits)
        return passed, 1.0 if passed else 0.0
    if not case.expected_turns:
        return len(hits) > 0, 1.0 if hits else 0.0
    exp = set(case.expected_turns)
    hit = set(hits)
    recall = len(exp & hit) / max(len(exp), 1)
    return recall >= 0.3, recall

def run_eval(engine, cases, label):
    results = []
    all_recall, all_ms = [], []
    for case in cases:
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
    return {
        "total": total,
        "passed": passed_count,
        "pass_rate": round(passed_count / total, 4),
        "avg_recall": round(sum(all_recall) / total, 4),
        "avg_ms": round(sum(all_ms) / total, 4),
        "by_category": {cat: {"total": len(rs), "passed": sum(1 for r in rs if r["passed"]),
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

    print(f"\n🚀 grep 对比: N-gram vs jieba+字段加权")
    print(f"   用例: {len(cases)} 条 | top_k={_TOP_K}\n")

    # N-gram
    ngram = GrepNgram()
    ngram.write(seed_data)
    ngram_eval = run_eval(ngram, cases, "N-gram")

    # jieba + 字段加权
    jb = GrepJieba()
    jb.write(seed_data)
    jieba_eval = run_eval(jb, cases, "jieba")

    # 报告
    print(f"{'═'*60}")
    print(f"  grep 对比: N-gram vs jieba + 字段加权")
    print(f"{'═'*60}")

    print(f"\n── 总体 ──────────────────────────────────────────")
    print(f"  ┌─────────────────┬──────────────┬──────────────────────┐")
    print(f"  │ 指标            │ N-gram       │ jieba + 字段加权      │")
    print(f"  ├─────────────────┼──────────────┼──────────────────────┤")
    print(f"  │ 通过率          │ {ngram_eval['pass_rate']*100:>6.1f}%     │ {jieba_eval['pass_rate']*100:>6.1f}%             │")
    print(f"  │ 平均召回率      │ {ngram_eval['avg_recall']*100:>6.1f}%     │ {jieba_eval['avg_recall']*100:>6.1f}%             │")
    print(f"  │ 平均延迟        │ {ngram_eval['avg_ms']:.3f}ms    │ {jieba_eval['avg_ms']:.3f}ms            │")
    print(f"  └─────────────────┴──────────────┴──────────────────────┘")

    print(f"\n── 按分类 ────────────────────────────────────────")
    print(f"  {'分类':<8} {'N-gram':>8} {'jieba':>8} {'差异':>8}")
    print(f"  {'─'*40}")
    all_cats = sorted(set(list(ngram_eval["by_category"].keys()) + list(jieba_eval["by_category"].keys())))
    for cat in all_cats:
        n = ngram_eval["by_category"].get(cat, {})
        j = jieba_eval["by_category"].get(cat, {})
        nr = n.get("rate", 0) * 100
        jr = j.get("rate", 0) * 100
        diff = jr - nr
        icon = "📈" if diff > 0 else ("📉" if diff < 0 else "✅")
        print(f"  {icon} {cat:<7} {nr:>6.1f}% {jr:>6.1f}% {diff:>+6.1f}%")

    # 差异
    ngram_fails = set(r["id"] for r in ngram_eval["results"] if not r["passed"])
    jieba_fails = set(r["id"] for r in jieba_eval["results"] if not r["passed"])
    fixed = ngram_fails - jieba_fails
    broken = jieba_fails - ngram_fails

    print(f"\n── 差异 ──────────────────────────────────────────")
    print(f"  jieba 修复: {len(fixed)} 条 | jieba 退化: {len(broken)} 条")

    if fixed:
        print(f"\n  jieba 修复的用例:")
        for fid in sorted(fixed):
            r = next(x for x in ngram_eval["results"] if x["id"] == fid)
            print(f"    ✅ {fid} [{r['cat']}] {r['query'][:40]}")

    if broken:
        print(f"\n  jieba 退化的用例:")
        for fid in sorted(broken):
            r = next(x for x in jieba_eval["results"] if x["id"] == fid)
            print(f"    ❌ {fid} [{r['cat']}] {r['query'][:40]}")

    # 全方案汇总
    print(f"\n── 全方案汇总 ────────────────────────────────────")
    print(f"  ┌────────────────────────────┬────────┬──────────┐")
    print(f"  │ 方案                       │ 通过率 │ 平均召回 │")
    print(f"  ├────────────────────────────┼────────┼──────────┤")
    print(f"  │ SQLite+HNSW+Qwen3         │  96.3% │   90.7%  │")
    print(f"  │ VDB+Qwen3                 │  94.7% │   89.3%  │")
    print(f"  │ grep jieba+字段加权 (本次) │ {jieba_eval['pass_rate']*100:>5.1f}% │  {jieba_eval['avg_recall']*100:>5.1f}%  │")
    print(f"  │ grep N-gram               │  87.9% │   81.5%  │")
    print(f"  └────────────────────────────┴────────┴──────────┘")
    print(f"{'═'*60}\n")

    # 保存
    out = "data/eval/runs/grep_jieba_compare.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fp:
        json.dump({"ngram": {k:v for k,v in ngram_eval.items() if k!="results"},
                   "jieba": {k:v for k,v in jieba_eval.items() if k!="results"}},
                  fp, ensure_ascii=False, indent=2)
    print(f"  📊 保存: {out}")


if __name__ == "__main__":
    main()
