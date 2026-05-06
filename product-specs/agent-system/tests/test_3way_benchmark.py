"""三种检索方式对比 — 200 条查询

A: 扁平 hybrid（BM25+向量）     ← 旧逻辑
B: 递归 vector（纯向量递归）     ← 当前新逻辑
C: 递归 hybrid（BM25+向量递归）  ← 递归展开时也用 BM25

运行:
  cd product-specs/agent-system
  .venv/bin/python -B tests/test_3way_benchmark.py
"""
import asyncio
import heapq
import os
import sys
import time
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")

# 复用数据和查询生成
from test_200_cases_benchmark import MEMORIES, generate_queries, evaluate


def _emb():
    from langchain_openai import OpenAIEmbeddings
    return OpenAIEmbeddings(
        model="doubao-embedding-text-240715",
        api_key=os.environ["DOUBAO_API_KEY"],
        base_url="https://ark.cn-beijing.volces.com/api/v3/",
        check_embedding_ctx_length=False,
    )


# ═══════════════════════════════════════════════════════════
# 三种检索方法
# ═══════════════════════════════════════════════════════════

async def method_a_flat_hybrid(vdb, vec, query, uid, top_k=3):
    """A: 扁平 hybrid（旧逻辑）"""
    start = time.monotonic()
    try:
        r = vdb.hybrid_search(vec, query, top_k, f'user_id = "{uid}"')
    except Exception:
        r = vdb.search(vec, top_k, f'user_id = "{uid}"')
    return r, (time.monotonic() - start) * 1000


async def method_b_recursive_vector(vdb, vec, query, uid, top_k=3):
    """B: 递归 vector（当前新逻辑 — 全局 hybrid + 递归纯向量）"""
    start = time.monotonic()
    try:
        gr = vdb.hybrid_search(vec, query, 10, f'user_id = "{uid}"')
    except Exception:
        gr = vdb.search(vec, 10, f'user_id = "{uid}"')

    collected, dq, seen = [], [], set()
    for r in gr:
        did = r.get("id", "")
        if did in seen: continue
        seen.add(did)
        s = float(r.get("score", 0))
        if r.get("is_leaf") == "false":
            u = r.get("uri", "")
            if u: heapq.heappush(dq, (-s, u))
        else:
            r["_fs"] = s; collected.append(r)

    prev, unc = [], 0
    while dq and unc < 3:
        ns, cu = heapq.heappop(dq)
        ps = -ns
        try:
            # 递归用纯向量
            ch = vdb.search(vec, 10, f'user_id = "{uid}" and parent_uri = "{cu}"')
        except Exception:
            ch = []
        for c in ch:
            cid = c.get("id", "")
            if cid in seen: continue
            seen.add(cid)
            fs = 0.5 * float(c.get("score", 0)) + 0.5 * ps
            if c.get("is_leaf") == "false":
                cu2 = c.get("uri", "")
                if cu2 and fs > 0.3: heapq.heappush(dq, (-fs, cu2))
            else:
                c["_fs"] = fs; collected.append(c)
        tk = sorted(collected, key=lambda x: x.get("_fs", 0), reverse=True)[:top_k]
        tids = [t.get("id") for t in tk]
        if tids == prev: unc += 1
        else: unc = 0; prev = tids

    ms = (time.monotonic() - start) * 1000
    collected.sort(key=lambda x: x.get("_fs", 0), reverse=True)
    return collected[:top_k], ms


async def method_c_recursive_hybrid(vdb, vec, query, uid, top_k=3):
    """C: 递归 hybrid（全局 hybrid + 递归也用 hybrid）"""
    start = time.monotonic()
    try:
        gr = vdb.hybrid_search(vec, query, 10, f'user_id = "{uid}"')
    except Exception:
        gr = vdb.search(vec, 10, f'user_id = "{uid}"')

    collected, dq, seen = [], [], set()
    for r in gr:
        did = r.get("id", "")
        if did in seen: continue
        seen.add(did)
        s = float(r.get("score", 0))
        if r.get("is_leaf") == "false":
            u = r.get("uri", "")
            if u: heapq.heappush(dq, (-s, u))
        else:
            r["_fs"] = s; collected.append(r)

    prev, unc = [], 0
    while dq and unc < 3:
        ns, cu = heapq.heappop(dq)
        ps = -ns
        try:
            # 递归也用 hybrid（BM25 + 向量）
            ch = vdb.hybrid_search(vec, query, 10, f'user_id = "{uid}" and parent_uri = "{cu}"')
        except Exception:
            try:
                ch = vdb.search(vec, 10, f'user_id = "{uid}" and parent_uri = "{cu}"')
            except Exception:
                ch = []
        for c in ch:
            cid = c.get("id", "")
            if cid in seen: continue
            seen.add(cid)
            fs = 0.5 * float(c.get("score", 0)) + 0.5 * ps
            if c.get("is_leaf") == "false":
                cu2 = c.get("uri", "")
                if cu2 and fs > 0.3: heapq.heappush(dq, (-fs, cu2))
            else:
                c["_fs"] = fs; collected.append(c)
        tk = sorted(collected, key=lambda x: x.get("_fs", 0), reverse=True)[:top_k]
        tids = [t.get("id") for t in tk]
        if tids == prev: unc += 1
        else: unc = 0; prev = tids

    ms = (time.monotonic() - start) * 1000
    collected.sort(key=lambda x: x.get("_fs", 0), reverse=True)
    return collected[:top_k], ms


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

async def main():
    from src.memory.viking_engine import VikingMemoryEngine
    emb = _emb()
    uid = "bench3_user"

    e = VikingMemoryEngine(
        vdb_url="http://10.60.2.17", vdb_key="bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
        database_name="viking_bench3", collection_name="bench3_v1",
        llm=None, use_pg=False,
    )

    # 写入数据
    print(f"写入 {len(MEMORIES)} 条记忆 + 目录节点...")
    parents = set()
    for m in MEMORIES:
        vec = emb.embed_query(m["abs"])
        cat = "entities" if m["pe"] else ("patterns" if "流程" in m["mk"] or "策略" in m["mk"] else "cases")
        lu = e._build_uri(cat, m["mk"], m["pe"])
        pu = e._build_parent_uri(cat, m["pe"])
        e._vdb.upsert([{
            "id": str(uuid4()), "vector": vec, "text": m["abs"],
            "abstract": m["abs"], "content": m["abs"],
            "category": cat, "merge_key": m["mk"],
            "parent_entity": m["pe"], "user_id": uid,
            "uri": lu, "parent_uri": pu, "is_leaf": "true",
        }])
        if m["pe"]: parents.add(m["pe"])

    for pe in parents:
        await e._ensure_directory_node("entities", pe, uid)

    print("等待索引...")
    time.sleep(10)

    queries = generate_queries()
    print(f"预计算 {len(queries)} 条查询向量...")
    qvecs = {}
    for q in queries:
        if q["query"] not in qvecs:
            qvecs[q["query"]] = emb.embed_query(q["query"])

    # 跑三种方法
    stats = {
        "A": {"name": "扁平hybrid", "parent_hit": 0, "top1_hit": 0, "kw_hit": 0, "kw_total": 0, "time": 0},
        "B": {"name": "递归vector", "parent_hit": 0, "top1_hit": 0, "kw_hit": 0, "kw_total": 0, "time": 0},
        "C": {"name": "递归hybrid", "parent_hit": 0, "top1_hit": 0, "kw_hit": 0, "kw_total": 0, "time": 0},
    }
    n = len(queries)
    qwp = sum(1 for q in queries if q["expect_parent"])

    for i, q in enumerate(queries):
        vec = qvecs[q["query"]]

        for key, method in [("A", method_a_flat_hybrid), ("B", method_b_recursive_vector), ("C", method_c_recursive_hybrid)]:
            results, ms = await method(e._vdb, vec, q["query"], uid)
            ph, kh, kt = evaluate(results, q)
            stats[key]["parent_hit"] += int(ph)
            stats[key]["kw_hit"] += kh
            stats[key]["kw_total"] += kt
            stats[key]["time"] += ms
            if results and q["expect_parent"] and q["expect_parent"] in results[0].get("abstract", ""):
                stats[key]["top1_hit"] += 1

        if (i + 1) % 50 == 0:
            print(f"  进度: {i+1}/{n}")

    # 输出
    print(f"\n{'='*75}")
    print(f"  200 条查询 × 3 种检索方式对比")
    print(f"{'='*75}")
    print(f"")
    print(f"  {'指标':<22} {'A:扁平hybrid':>14} {'B:递归vector':>14} {'C:递归hybrid':>14}")
    print(f"  {'─'*65}")
    print(f"  {'客户命中率(Top-3)':<22} {stats['A']['parent_hit']/qwp:>13.1%} {stats['B']['parent_hit']/qwp:>13.1%} {stats['C']['parent_hit']/qwp:>13.1%}")
    print(f"  {'Top-1精确命中':<22} {stats['A']['top1_hit']/qwp:>13.1%} {stats['B']['top1_hit']/qwp:>13.1%} {stats['C']['top1_hit']/qwp:>13.1%}")
    if stats["A"]["kw_total"] > 0:
        print(f"  {'关键词召回率':<22} {stats['A']['kw_hit']/stats['A']['kw_total']:>13.1%} {stats['B']['kw_hit']/stats['B']['kw_total']:>13.1%} {stats['C']['kw_hit']/stats['C']['kw_total']:>13.1%}")
    print(f"  {'平均耗时':<22} {stats['A']['time']/n:>12.0f}ms {stats['B']['time']/n:>12.0f}ms {stats['C']['time']/n:>12.0f}ms")
    print(f"")

    # 找最优
    best_parent = max(stats.items(), key=lambda x: x[1]["parent_hit"])[0]
    best_top1 = max(stats.items(), key=lambda x: x[1]["top1_hit"])[0]
    fastest = min(stats.items(), key=lambda x: x[1]["time"])[0]
    print(f"  最佳客户命中: {stats[best_parent]['name']} ({best_parent})")
    print(f"  最佳Top-1:   {stats[best_top1]['name']} ({best_top1})")
    print(f"  最快速度:     {stats[fastest]['name']} ({fastest})")
    print(f"{'='*75}")


if __name__ == "__main__":
    asyncio.run(main())
