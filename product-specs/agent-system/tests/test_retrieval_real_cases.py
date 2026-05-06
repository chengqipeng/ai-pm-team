"""递归检索 vs 扁平检索 — 真实 CRM 销售场景对比

模拟一个销售经理积累了 15 条客户洞察后，
用日常工作中的真实问法来检索，对比两种检索方式的效果。

运行:
  cd product-specs/agent-system
  .venv/bin/python -B tests/test_retrieval_real_cases.py
"""
import asyncio
import heapq
import os
import sys
import time
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")


def _emb():
    from langchain_openai import OpenAIEmbeddings
    return OpenAIEmbeddings(
        model="doubao-embedding-text-240715",
        api_key=os.environ["DOUBAO_API_KEY"],
        base_url="https://ark.cn-beijing.volces.com/api/v3/",
        check_embedding_ctx_length=False,
    )


# ═══════════════════════════════════════════════════════════
# 模拟数据 — 销售经理 3 个月积累的客户洞察
# ═══════════════════════════════════════════════════════════

MEMORIES = [
    # ── 华为（5 条）──
    {"merge_key": "华为/张伟", "parent_entity": "华为",
     "abstract": "华为/张伟: 说话直接不绕弯子，汇报用PPT带数据，每次会议控制30分钟",
     "content": "华为IT总监张伟说话很直接，不喜欢绕弯子。给他汇报最好用PPT带数据，每次会议控制在30分钟内。"},
    {"merge_key": "华为/李娜", "parent_entity": "华为",
     "abstract": "华为/李娜: 采购经理，做事谨慎，关注合规和流程，需要提前准备审批材料",
     "content": "华为采购经理李娜做事非常谨慎，特别关注合规和流程。跟她打交道需要提前准备好所有审批材料。"},
    {"merge_key": "华为/ERP项目", "parent_entity": "华为",
     "abstract": "华为/ERP项目: 张伟支持但李娜担心预算，两人有分歧需分别沟通",
     "content": "华为ERP项目中张伟和李娜意见不一致。张伟想上ERP，李娜觉得预算不够。建议分别沟通，先搞定张伟的技术认可，再解决李娜的预算顾虑。"},
    {"merge_key": "华为/采购流程", "parent_entity": "华为",
     "abstract": "华为: 采购流程长，IT部门后还需采购委员会审批，一般3-4周",
     "content": "华为的采购流程特别长，IT部门同意了还要过采购委员会，一般要3到4周。签约前需要预留足够时间。"},
    {"merge_key": "华为/报价策略", "parent_entity": "华为",
     "abstract": "华为/报价: 先报标准价预留谈判空间，张伟喜欢有谈判的感觉",
     "content": "华为报价时不要一次报到底，先报标准价，等他们还价再给折扣。张伟喜欢有谈判的感觉，直接给底价反而让他觉得还有空间。"},

    # ── 腾讯（4 条）──
    {"merge_key": "腾讯/王强", "parent_entity": "腾讯",
     "abstract": "腾讯/王强: CTO，技术导向，喜欢看demo不喜欢看PPT，决策快",
     "content": "腾讯CTO王强是技术导向的人，喜欢看实际demo不喜欢看PPT。决策速度快，如果demo效果好当场就能拍板。"},
    {"merge_key": "腾讯/数据中台", "parent_entity": "腾讯",
     "abstract": "腾讯/数据中台: 同时评估我方和用友，王强倾向我方但VP看重价格",
     "content": "腾讯数据中台项目同时评估我方和用友。王强倾向我方产品，但他的VP更看重价格。需要在价格策略上做文章。"},
    {"merge_key": "腾讯/POC", "parent_entity": "腾讯",
     "abstract": "腾讯/POC: 上周POC效果好，王强内部表扬，性能比用友快3倍",
     "content": "上周给腾讯做的数据中台POC效果很好，王强在内部会议上表扬了我们的方案，特别提到性能比用友快3倍。"},
    {"merge_key": "腾讯/时间窗口", "parent_entity": "腾讯",
     "abstract": "腾讯: 王强本月忙于组织架构调整，下月初再跟进",
     "content": "腾讯王强最近忙于集团组织架构调整，本月没时间评估方案。建议下月初再联系跟进。"},

    # ── 招商银行（3 条）──
    {"merge_key": "招行/陈刚", "parent_entity": "招行",
     "abstract": "招行/陈刚: 信息部主管，注重数据安全，每次都会问安全认证",
     "content": "招行信息部主管陈刚非常注重数据安全，每次开会都会问我们的安全认证情况。给金融客户做方案安全资质要前置。"},
    {"merge_key": "招行/风控平台", "parent_entity": "招行",
     "abstract": "招行/风控平台: 陈刚私下确认选我方，正式流程还需两周",
     "content": "招行风控平台项目陈刚私下确认基本选择我们，但正式采购流程还需两周。在正式确认前保持低调。"},
    {"merge_key": "招行/合规要求", "parent_entity": "招行",
     "abstract": "招行: 金融行业合规要求严格，需要提供等保三级和SOC2认证",
     "content": "招行作为金融机构合规要求非常严格，需要我们提供等保三级认证和SOC2报告。建议提前准备好这些材料。"},

    # ── 跨客户经验（3 条）──
    {"merge_key": "金融行业方案策略", "parent_entity": "",
     "abstract": "金融行业方案: 安全资质前置，招行和华为都问过安全认证",
     "content": "金融行业客户特别在意数据安全，招行和华为都问过安全认证。给金融客户做方案时安全资质要放在前面。"},
    {"merge_key": "客户分析流程", "parent_entity": "",
     "abstract": "客户分析流程: 基本信息→商机→联系人→活动→汇总",
     "content": "分析客户时按以下顺序：先查基本信息，再看商机，然后查联系人，最后看活动记录。"},
    {"merge_key": "查询报错经验", "parent_entity": "",
     "abstract": "查询商机报错: 字段名stage写成status，用query_schema确认可避免",
     "content": "查询商机时报错，原因是字段名stage写成了status。建议查询前先用query_schema确认字段名。"},
]


# ═══════════════════════════════════════════════════════════
# 真实查询场景 — 销售经理日常会怎么问
# ═══════════════════════════════════════════════════════════

REAL_QUERIES = [
    # ── 场景 1: 开会前准备 ──
    {
        "query": "明天要去华为开会，有什么需要注意的",
        "expect_parent": "华为",
        "expect_keywords": ["张伟", "PPT", "直接"],
        "scenario": "开会前准备",
    },
    # ── 场景 2: 跟进客户前回忆 ──
    {
        "query": "腾讯那边现在什么情况",
        "expect_parent": "腾讯",
        "expect_keywords": ["王强", "数据中台"],
        "scenario": "跟进前回忆",
    },
    # ── 场景 3: 报价前确认策略 ──
    {
        "query": "给华为报价要注意什么",
        "expect_parent": "华为",
        "expect_keywords": ["标准价", "谈判"],
        "scenario": "报价前确认",
    },
    # ── 场景 4: 想不起来联系人特点 ──
    {
        "query": "招行那个陈刚是什么风格的人",
        "expect_parent": "招行",
        "expect_keywords": ["安全", "陈刚"],
        "scenario": "联系人风格",
    },
    # ── 场景 5: 项目进展确认 ──
    {
        "query": "招行风控项目现在到哪一步了",
        "expect_parent": "招行",
        "expect_keywords": ["确认", "两周"],
        "scenario": "项目进展",
    },
    # ── 场景 6: 模糊回忆 ──
    {
        "query": "之前哪个客户说预算不够来着",
        "expect_parent": "华为",
        "expect_keywords": ["预算", "李娜"],
        "scenario": "模糊回忆",
    },
    # ── 场景 7: 竞品信息 ──
    {
        "query": "用友在哪个客户那边跟我们竞争",
        "expect_parent": "腾讯",
        "expect_keywords": ["用友", "腾讯"],
        "scenario": "竞品信息",
    },
    # ── 场景 8: 签约流程确认 ──
    {
        "query": "华为签合同一般要多久",
        "expect_parent": "华为",
        "expect_keywords": ["采购", "3", "4"],
        "scenario": "签约流程",
    },
    # ── 场景 9: 金融客户通用经验 ──
    {
        "query": "做金融客户的方案有什么要注意的",
        "expect_parent": None,
        "expect_keywords": ["安全", "资质"],
        "scenario": "行业经验",
    },
    # ── 场景 10: 上次 POC 结果 ──
    {
        "query": "上次给腾讯做的POC结果怎么样",
        "expect_parent": "腾讯",
        "expect_keywords": ["POC", "3倍"],
        "scenario": "POC结果",
    },
]


async def flat_search(vdb, emb, query, uid, top_k=3):
    vec = emb.embed_query(query)
    start = time.monotonic()
    try:
        results = vdb.hybrid_search(vec, query, top_k, f'user_id = "{uid}"')
    except Exception:
        results = vdb.search(vec, top_k, f'user_id = "{uid}"')
    ms = (time.monotonic() - start) * 1000
    return results, ms


async def recursive_search(vdb, emb, query, uid, top_k=3):
    vec = emb.embed_query(query)
    start = time.monotonic()

    try:
        global_r = vdb.hybrid_search(vec, query, 10, f'user_id = "{uid}"')
    except Exception:
        global_r = vdb.search(vec, 10, f'user_id = "{uid}"')

    collected, dir_queue, seen = [], [], set()
    for r in global_r:
        did = r.get("id", "")
        if did in seen: continue
        seen.add(did)
        s = float(r.get("score", 0))
        if r.get("is_leaf") == "false":
            uri = r.get("uri", "")
            if uri: heapq.heappush(dir_queue, (-s, uri))
        else:
            r["_fs"] = s
            collected.append(r)

    prev, unc = [], 0
    while dir_queue and unc < 3:
        ns, cur = heapq.heappop(dir_queue)
        ps = -ns
        try:
            children = vdb.search(vec, 10, f'user_id = "{uid}" and parent_uri = "{cur}"')
        except Exception:
            children = []
        for c in children:
            cid = c.get("id", "")
            if cid in seen: continue
            seen.add(cid)
            cs = float(c.get("score", 0))
            fs = 0.5 * cs + 0.5 * ps
            if c.get("is_leaf") == "false":
                cu = c.get("uri", "")
                if cu and fs > 0.3: heapq.heappush(dir_queue, (-fs, cu))
            else:
                c["_fs"] = fs
                collected.append(c)
        tk = sorted(collected, key=lambda x: x.get("_fs", 0), reverse=True)[:top_k]
        tids = [t.get("id") for t in tk]
        if tids == prev: unc += 1
        else: unc = 0; prev = tids

    ms = (time.monotonic() - start) * 1000
    collected.sort(key=lambda x: x.get("_fs", 0), reverse=True)
    return collected[:top_k], ms


def evaluate(results, q):
    """评估: 客户命中 + 关键词命中"""
    all_text = " ".join(r.get("abstract", "") + " " + r.get("content", "") for r in results[:3])
    parent_hit = True
    if q["expect_parent"]:
        parent_hit = q["expect_parent"] in all_text
    kw_hits = sum(1 for kw in q["expect_keywords"] if kw in all_text)
    kw_total = len(q["expect_keywords"])
    return parent_hit, kw_hits, kw_total


async def main():
    from src.memory.viking_engine import VikingMemoryEngine
    emb = _emb()
    uid = "real_user"

    e_flat = VikingMemoryEngine(
        vdb_url="http://10.60.2.17", vdb_key="bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
        database_name="viking_real_cmp", collection_name="real_flat",
        llm=None, use_pg=False,
    )
    e_rec = VikingMemoryEngine(
        vdb_url="http://10.60.2.17", vdb_key="bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
        database_name="viking_real_cmp", collection_name="real_rec",
        llm=None, use_pg=False,
    )

    print("写入 15 条客户洞察...")
    for m in MEMORIES:
        vec = emb.embed_query(m["abstract"])
        rid = str(uuid4())
        cat = "entities" if m["parent_entity"] else ("patterns" if "流程" in m["merge_key"] else "cases")
        lu = e_rec._build_uri(cat, m["merge_key"], m["parent_entity"])
        pu = e_rec._build_parent_uri(cat, m["parent_entity"])

        e_flat._vdb.upsert([{"id": rid+"_f", "vector": vec, "text": m["abstract"],
            "abstract": m["abstract"], "content": m["content"], "category": cat,
            "merge_key": m["merge_key"], "parent_entity": m["parent_entity"], "user_id": uid}])
        e_rec._vdb.upsert([{"id": rid+"_r", "vector": vec, "text": m["abstract"],
            "abstract": m["abstract"], "content": m["content"], "category": cat,
            "merge_key": m["merge_key"], "parent_entity": m["parent_entity"], "user_id": uid,
            "uri": lu, "parent_uri": pu, "is_leaf": "true"}])

    for pe in ["华为", "腾讯", "招行"]:
        await e_rec._ensure_directory_node("entities", pe, uid)

    print("等待索引...")
    time.sleep(8)

    # 对比
    print(f"\n{'='*90}")
    print(f"  {'#':<3} {'场景':<12} {'查询':<30} {'方法':<5} {'客户':>4} {'关键词':>5} {'耗时':>6} Top-1")
    print(f"{'='*90}")

    flat_score, rec_score = 0, 0
    flat_time, rec_time = 0, 0

    for i, q in enumerate(REAL_QUERIES):
        fr, ft = await flat_search(e_flat._vdb, emb, q["query"], uid)
        rr, rt = await recursive_search(e_rec._vdb, emb, q["query"], uid)

        fp, fkh, fkt = evaluate(fr, q)
        rp, rkh, rkt = evaluate(rr, q)

        f_top1 = fr[0].get("abstract", "")[:30] if fr else "(空)"
        r_top1 = rr[0].get("abstract", "")[:30] if rr else "(空)"

        f_mark = "✅" if fp and fkh == fkt else ("⚠️" if fp else "❌")
        r_mark = "✅" if rp and rkh == rkt else ("⚠️" if rp else "❌")

        print(f"  {i+1:<3} {q['scenario']:<12} {q['query']:<30} {'扁平':<5} {f_mark:>4} {fkh}/{fkt:>4} {ft:>5.0f}ms {f_top1}")
        print(f"  {'':<3} {'':<12} {'':<30} {'递归':<5} {r_mark:>4} {rkh}/{rkt:>4} {rt:>5.0f}ms {r_top1}")

        flat_score += (1 if fp else 0) + fkh / max(fkt, 1)
        rec_score += (1 if rp else 0) + rkh / max(rkt, 1)
        flat_time += ft
        rec_time += rt

    n = len(REAL_QUERIES)
    print(f"\n{'='*90}")
    print(f"  综合得分（客户命中+关键词命中）:")
    print(f"    扁平: {flat_score:.1f}/{n*2:.0f}  平均耗时: {flat_time/n:.0f}ms")
    print(f"    递归: {rec_score:.1f}/{n*2:.0f}  平均耗时: {rec_time/n:.0f}ms")
    print(f"    提升: {(rec_score-flat_score)/max(flat_score,0.01)*100:+.1f}%")
    print(f"{'='*90}")


if __name__ == "__main__":
    asyncio.run(main())
