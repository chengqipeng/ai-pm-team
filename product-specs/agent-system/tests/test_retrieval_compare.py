"""递归检索 vs 扁平检索 — 效率和准确率对比

用同一份数据，分别用旧逻辑（扁平 hybrid_search）和新逻辑（递归目录检索）检索，
对比准确率（Top-K 中目标客户的命中率）和耗时。

运行:
  cd product-specs/agent-system
  .venv/bin/python -B tests/test_retrieval_compare.py
"""
import asyncio
import os
import sys
import time
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw")


def _emb():
    from langchain_openai import OpenAIEmbeddings
    return OpenAIEmbeddings(
        model="doubao-embedding-text-240715",
        api_key=os.environ.get("EMBEDDING_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1"),
        base_url="https://ark.cn-beijing.volces.com/api/v3/",
        check_embedding_ctx_length=False,
    )


# ═══════════════════════════════════════════════════════════
# 测试数据 — 3 个客户 × 3-4 条记忆 = 10 条
# ═══════════════════════════════════════════════════════════

MEMORIES = [
    # 华为科技 (4 条)
    {"category": "entities", "merge_key": "华为科技/张伟", "parent_entity": "华为科技",
     "abstract": "华为科技/张伟: 说话直接不绕弯子，汇报用PPT带数据",
     "content": "华为联系人张伟说话直接，不喜欢绕弯子，汇报用PPT带数据。"},
    {"category": "entities", "merge_key": "华为科技/ERP项目", "parent_entity": "华为科技",
     "abstract": "华为科技/ERP项目: 张伟和李娜有分歧，需分别沟通",
     "content": "华为ERP项目中张伟和李娜意见不一致，张伟想上ERP，李娜觉得预算不够。"},
    {"category": "entities", "merge_key": "华为科技/采购流程", "parent_entity": "华为科技",
     "abstract": "华为科技: 采购流程3-4周，需经IT和采购委员会审批",
     "content": "华为采购流程长，IT部门同意后还需采购委员会审批，一般3-4周。"},
    {"category": "entities", "merge_key": "华为科技/预算", "parent_entity": "华为科技",
     "abstract": "华为科技: 今年IT预算收紧，所有项目需重新评估ROI",
     "content": "华为今年IT预算收紧，所有新项目都要重新评估ROI才能立项。"},

    # 腾讯 (3 条)
    {"category": "entities", "merge_key": "腾讯/数据中台", "parent_entity": "腾讯",
     "abstract": "腾讯/数据中台: 王强倾向我方产品，老板看重价格",
     "content": "腾讯评估我方和用友的数据中台产品，王强倾向我方但老板看重价格。"},
    {"category": "entities", "merge_key": "腾讯/王强", "parent_entity": "腾讯",
     "abstract": "腾讯/王强: 本月忙于组织架构调整，下月再跟进",
     "content": "腾讯王强忙于组织架构调整，本月没时间看方案，下月再跟进。"},
    {"category": "entities", "merge_key": "腾讯/报价", "parent_entity": "腾讯",
     "abstract": "腾讯/报价策略: 需要突出性价比，老板对价格敏感",
     "content": "腾讯报价时需要突出性价比，王强的老板对价格非常敏感。"},

    # 比亚迪 (3 条)
    {"category": "entities", "merge_key": "比亚迪/赵敏", "parent_entity": "比亚迪",
     "abstract": "比亚迪/赵敏: 不喜欢吃饭应酬，喜欢打羽毛球",
     "content": "比亚迪赵敏不喜欢吃饭应酬，喜欢打羽毛球，约球比约饭好。"},
    {"category": "entities", "merge_key": "比亚迪/MES项目", "parent_entity": "比亚迪",
     "abstract": "比亚迪/MES项目: 预算砍20%，需重新评估ROI",
     "content": "比亚迪今年数字化预算砍了20%，MES项目需要重新评估ROI。"},
    {"category": "entities", "merge_key": "比亚迪/决策链", "parent_entity": "比亚迪",
     "abstract": "比亚迪: 决策链长，需要同时搞定技术和采购两条线",
     "content": "比亚迪决策链很长，需要同时搞定技术线（赵敏）和采购线。"},
]

# 测试查询 + 期望命中的客户
QUERIES = [
    ("华为的情况", "华为科技", 4),
    ("腾讯项目进展", "腾讯", 3),
    ("比亚迪的联系人", "比亚迪", 3),
    ("采购流程", "华为科技", 1),       # 精确查询，只有华为有采购流程
    ("预算收紧", None, 2),             # 跨客户，华为和比亚迪都有
    ("报价策略", "腾讯", 1),           # 精确查询
    ("客户的社交偏好", "比亚迪", 1),    # 只有比亚迪赵敏有社交偏好
    ("ERP项目内部分歧", "华为科技", 1), # 精确查询
]


# ═══════════════════════════════════════════════════════════
# 扁平检索（旧逻辑）
# ═══════════════════════════════════════════════════════════

async def flat_retrieve(vdb, emb, query, uid, top_k=5):
    """旧逻辑: 直接 hybrid_search，无目录结构"""
    vec = emb.embed_query(query)
    filter_expr = f'user_id = "{uid}"'
    start = time.monotonic()
    try:
        results = vdb.hybrid_search(vec, query, top_k, filter_expr)
    except Exception:
        results = vdb.search(vec, top_k, filter_expr)
    elapsed = (time.monotonic() - start) * 1000
    return results, elapsed


# ═══════════════════════════════════════════════════════════
# 递归检索（新逻辑）
# ═══════════════════════════════════════════════════════════

async def recursive_retrieve(vdb, emb, query, uid, top_k=5):
    """新逻辑: 递归目录检索 + 分数传播"""
    import heapq
    ALPHA = 0.5
    MAX_CONVERGENCE = 3

    vec = emb.embed_query(query)
    filter_expr = f'user_id = "{uid}"'

    start = time.monotonic()

    # Step 1: 全局搜索
    try:
        global_results = vdb.hybrid_search(vec, query, 10, filter_expr)
    except Exception:
        global_results = vdb.search(vec, 10, filter_expr)

    collected = []
    dir_queue = []
    seen_ids = set()

    for r in global_results:
        doc_id = r.get("id", "")
        if doc_id in seen_ids:
            continue
        seen_ids.add(doc_id)
        score = float(r.get("score", 0))

        if r.get("is_leaf") == "false":
            dir_uri = r.get("uri", "") or r.get("parent_uri", "")
            if dir_uri:
                heapq.heappush(dir_queue, (-score, dir_uri))
        else:
            r["_final_score"] = score
            collected.append(r)

    # Step 2: 递归展开
    prev_topk_ids = []
    unchanged = 0

    while dir_queue and unchanged < MAX_CONVERGENCE:
        neg_score, current_uri = heapq.heappop(dir_queue)
        parent_score = -neg_score

        try:
            child_filter = f'user_id = "{uid}" and parent_uri = "{current_uri}"'
            children = vdb.search(vec, 10, child_filter)
        except Exception:
            children = []

        for child in children:
            cid = child.get("id", "")
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            cs = float(child.get("score", 0))
            fs = ALPHA * cs + (1 - ALPHA) * parent_score

            if child.get("is_leaf") == "false":
                child_uri = child.get("uri", "")
                if child_uri and fs > 0.3:
                    heapq.heappush(dir_queue, (-fs, child_uri))
            else:
                child["_final_score"] = fs
                collected.append(child)

        cur_topk = sorted(collected, key=lambda x: x.get("_final_score", 0), reverse=True)[:top_k]
        cur_ids = [c.get("id") for c in cur_topk]
        if cur_ids == prev_topk_ids:
            unchanged += 1
        else:
            unchanged = 0
            prev_topk_ids = cur_ids

    elapsed = (time.monotonic() - start) * 1000
    collected.sort(key=lambda x: x.get("_final_score", 0), reverse=True)
    return collected[:top_k], elapsed


# ═══════════════════════════════════════════════════════════
# 准确率计算
# ═══════════════════════════════════════════════════════════

def calc_precision(results, target_customer, expected_count, top_k=3):
    """计算 Top-K 中目标客户的命中率"""
    if target_customer is None:
        return 1.0  # 跨客户查询不评估精确率

    top_results = results[:top_k]
    hits = 0
    for r in top_results:
        pe = r.get("parent_entity", "")
        mk = r.get("merge_key", "")
        abstract = r.get("abstract", "")
        if target_customer in pe or target_customer in mk or target_customer in abstract:
            hits += 1

    return hits / min(expected_count, top_k)


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

async def main():
    from src.memory.viking_engine import VikingMemoryEngine

    emb = _emb()

    # 创建两个 collection: 一个无目录结构（扁平），一个有目录结构（递归）
    e_flat = VikingMemoryEngine(
        vdb_url="http://10.60.2.17", vdb_key="bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
        database_name="viking_compare", collection_name="cmp_flat",
        llm=None, use_pg=False,
    )
    e_recursive = VikingMemoryEngine(
        vdb_url="http://10.60.2.17", vdb_key="bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
        database_name="viking_compare", collection_name="cmp_recursive",
        llm=None, use_pg=False,
    )

    uid = "cmp_user"

    # 写入数据
    print("写入测试数据...")
    for m in MEMORIES:
        vec = emb.embed_query(m["abstract"])
        rid = str(uuid4())
        leaf_uri = e_recursive._build_uri(m["category"], m["merge_key"], m["parent_entity"])
        parent_uri = e_recursive._build_parent_uri(m["category"], m["parent_entity"])

        # 扁平 collection（无 uri/parent_uri/is_leaf）
        e_flat._vdb.upsert([{
            "id": rid + "_f", "vector": vec, "text": m["abstract"],
            "abstract": m["abstract"], "content": m["content"],
            "category": m["category"], "merge_key": m["merge_key"],
            "parent_entity": m["parent_entity"], "user_id": uid,
        }])

        # 递归 collection（有 uri/parent_uri/is_leaf）
        e_recursive._vdb.upsert([{
            "id": rid + "_r", "vector": vec, "text": m["abstract"],
            "abstract": m["abstract"], "content": m["content"],
            "category": m["category"], "merge_key": m["merge_key"],
            "parent_entity": m["parent_entity"], "user_id": uid,
            "uri": leaf_uri, "parent_uri": parent_uri, "is_leaf": "true",
        }])

    # 创建目录节点（只在递归 collection 中）
    for pe in ["华为科技", "腾讯", "比亚迪"]:
        await e_recursive._ensure_directory_node("entities", pe, uid)

    print("等待索引构建...")
    time.sleep(8)

    # 对比测试
    print(f"\n{'='*80}")
    print(f"  {'查询':<20} {'方法':<8} {'耗时':>6} {'Top-3精确率':>10} {'Top-1':>40}")
    print(f"{'='*80}")

    flat_total_precision = 0
    flat_total_time = 0
    rec_total_precision = 0
    rec_total_time = 0

    for query, target, expected in QUERIES:
        # 扁平检索
        flat_results, flat_ms = await flat_retrieve(e_flat._vdb, emb, query, uid, 5)
        flat_prec = calc_precision(flat_results, target, expected)
        flat_top1 = flat_results[0].get("abstract", "")[:35] if flat_results else "(空)"

        # 递归检索
        rec_results, rec_ms = await recursive_retrieve(e_recursive._vdb, emb, query, uid, 5)
        rec_prec = calc_precision(rec_results, target, expected)
        rec_top1 = rec_results[0].get("abstract", "")[:35] if rec_results else "(空)"

        print(f"  {query:<20} {'扁平':<8} {flat_ms:>5.0f}ms {flat_prec:>9.0%} {flat_top1:>40}")
        print(f"  {'':<20} {'递归':<8} {rec_ms:>5.0f}ms {rec_prec:>9.0%} {rec_top1:>40}")
        print()

        flat_total_precision += flat_prec
        flat_total_time += flat_ms
        rec_total_precision += rec_prec
        rec_total_time += rec_ms

    n = len(QUERIES)
    print(f"{'='*80}")
    print(f"  {'平均':<20} {'扁平':<8} {flat_total_time/n:>5.0f}ms {flat_total_precision/n:>9.0%}")
    print(f"  {'':<20} {'递归':<8} {rec_total_time/n:>5.0f}ms {rec_total_precision/n:>9.0%}")
    print(f"{'='*80}")

    improvement = (rec_total_precision - flat_total_precision) / max(flat_total_precision, 0.01) * 100
    time_diff = rec_total_time / n - flat_total_time / n
    print(f"\n  准确率提升: {improvement:+.1f}%")
    print(f"  耗时变化: {time_diff:+.0f}ms/查询")


if __name__ == "__main__":
    asyncio.run(main())
