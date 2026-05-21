"""200 条真实业务场景基准测试 — BM25 权重验证 + 递归检索评测

数据规模: 10 个客户 × 6-8 条洞察 = 75 条记忆 + 15 条通用记忆 = 90 条
查询规模: 200 条不同场景的查询
评测维度: 客户命中率、关键词召回率、Top-1 准确率、耗时

运行:
  cd product-specs/agent-system
  .venv/bin/python -B tests/test_200_cases_benchmark.py
"""
import asyncio
import heapq
import json
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
# 90 条记忆数据 — 10 个客户 + 通用经验
# ═══════════════════════════════════════════════════════════

MEMORIES = [
    # ── 华为（8 条）──
    {"mk": "华为/张伟", "pe": "华为", "abs": "华为/张伟: 说话直接不绕弯子，汇报用PPT带数据，会议控制30分钟"},
    {"mk": "华为/李娜", "pe": "华为", "abs": "华为/李娜: 采购经理，做事谨慎关注合规，需提前准备审批材料"},
    {"mk": "华为/ERP项目", "pe": "华为", "abs": "华为/ERP项目: 张伟支持但李娜担心预算，两人有分歧需分别沟通"},
    {"mk": "华为/采购流程", "pe": "华为", "abs": "华为: 采购流程3-4周，IT部门后还需采购委员会审批"},
    {"mk": "华为/报价策略", "pe": "华为", "abs": "华为/报价: 先报标准价预留谈判空间，张伟喜欢有谈判的感觉"},
    {"mk": "华为/预算", "pe": "华为", "abs": "华为: 今年IT预算收紧，所有项目需重新评估ROI"},
    {"mk": "华为/CRM部署", "pe": "华为", "abs": "华为/CRM部署: 李娜负责，已进入商务谈判阶段"},
    {"mk": "华为/安全审计", "pe": "华为", "abs": "华为/安全审计: 即将closing，本周推动签约"},

    # ── 腾讯（7 条）──
    {"mk": "腾讯/王强", "pe": "腾讯", "abs": "腾讯/王强: CTO，技术导向，喜欢看demo不喜欢PPT，决策快"},
    {"mk": "腾讯/数据中台", "pe": "腾讯", "abs": "腾讯/数据中台: 同时评估我方和用友，王强倾向我方但VP看重价格"},
    {"mk": "腾讯/POC", "pe": "腾讯", "abs": "腾讯/POC: 上周效果好，王强内部表扬，性能比用友快3倍"},
    {"mk": "腾讯/时间窗口", "pe": "腾讯", "abs": "腾讯: 王强本月忙于组织架构调整，下月初再跟进"},
    {"mk": "腾讯/报价", "pe": "腾讯", "abs": "腾讯/报价: 需要突出性价比，VP对价格非常敏感"},
    {"mk": "腾讯/赵经理", "pe": "腾讯", "abs": "腾讯/赵经理: 采购负责人，流程规范，需要三方比价"},
    {"mk": "腾讯/AI平台", "pe": "腾讯", "abs": "腾讯/AI平台: 新项目，王强很感兴趣，预算1200万"},

    # ── 招商银行（6 条）──
    {"mk": "招行/陈刚", "pe": "招行", "abs": "招行/陈刚: 信息部主管，注重数据安全，每次都问安全认证"},
    {"mk": "招行/风控平台", "pe": "招行", "abs": "招行/风控平台: 陈刚私下确认选我方，正式流程还需两周"},
    {"mk": "招行/合规", "pe": "招行", "abs": "招行: 金融合规要求严格，需等保三级和SOC2认证"},
    {"mk": "招行/刘总", "pe": "招行", "abs": "招行/刘总: VP级别，最终审批人，关注系统稳定性"},
    {"mk": "招行/数据迁移", "pe": "招行", "abs": "招行/数据迁移: 历史数据量大，需要专项迁移方案"},
    {"mk": "招行/培训", "pe": "招行", "abs": "招行: 要求上线前做3轮培训，陈刚团队20人"},

    # ── 比亚迪（6 条）──
    {"mk": "比亚迪/赵敏", "pe": "比亚迪", "abs": "比亚迪/赵敏: 数字化负责人，不喜欢吃饭应酬，喜欢打羽毛球"},
    {"mk": "比亚迪/MES项目", "pe": "比亚迪", "abs": "比亚迪/MES项目: 预算砍20%，需重新评估ROI"},
    {"mk": "比亚迪/决策链", "pe": "比亚迪", "abs": "比亚迪: 决策链长，需同时搞定技术线和采购线"},
    {"mk": "比亚迪/工厂", "pe": "比亚迪", "abs": "比亚迪/工厂: 深圳和长沙两个工厂，需要分别部署"},
    {"mk": "比亚迪/竞品", "pe": "比亚迪", "abs": "比亚迪: 之前用过SAP，体验不好，对国产化有偏好"},
    {"mk": "比亚迪/时间表", "pe": "比亚迪", "abs": "比亚迪: 希望Q3完成选型，Q4开始实施"},

    # ── 小米（6 条）──
    {"mk": "小米/林总", "pe": "小米", "abs": "小米/林总: 互联网思维，追求快速迭代，不喜欢传统软件的重流程"},
    {"mk": "小米/IoT平台", "pe": "小米", "abs": "小米/IoT平台: 650万方案阶段，需要和现有系统对接"},
    {"mk": "小米/智能工厂", "pe": "小米", "abs": "小米/智能工厂: 1800万谈判阶段，林总亲自推动"},
    {"mk": "小米/技术栈", "pe": "小米", "abs": "小米: 技术团队偏好微服务架构，要求API优先"},
    {"mk": "小米/预算", "pe": "小米", "abs": "小米: 今年数字化预算充足，但审批流程快需要快速响应"},
    {"mk": "小米/对接人", "pe": "小米", "abs": "小米/周工: 技术对接人，沟通高效，周末也回消息"},

    # ── 字节跳动（6 条）──
    {"mk": "字节/孙丽", "pe": "字节", "abs": "字节/孙丽: 商务负责人，做事雷厉风行，邮件必须当天回复"},
    {"mk": "字节/广告平台", "pe": "字节", "abs": "字节/广告平台: 3000万大项目，竞争对手是Salesforce"},
    {"mk": "字节/文化", "pe": "字节", "abs": "字节: 公司文化扁平，决策快但变化也快，需要灵活应对"},
    {"mk": "字节/技术要求", "pe": "字节", "abs": "字节: 技术要求高，需要支持10万级并发，性能是硬指标"},
    {"mk": "字节/合同", "pe": "字节", "abs": "字节/合同: 法务审核严格，合同条款需要反复沟通"},
    {"mk": "字节/试用", "pe": "字节", "abs": "字节: 要求先免费试用1个月，效果好再签正式合同"},

    # ── 美团（5 条）──
    {"mk": "美团/周明", "pe": "美团", "abs": "美团/周明: 技术VP，关注系统可扩展性，喜欢技术深度交流"},
    {"mk": "美团/外卖SaaS", "pe": "美团", "abs": "美团/外卖SaaS: 900万项目，需要支持多租户架构"},
    {"mk": "美团/数据安全", "pe": "美团", "abs": "美团: 对数据安全要求高，需要私有化部署"},
    {"mk": "美团/竞品", "pe": "美团", "abs": "美团: 之前评估过纷享销客，觉得功能不够强"},
    {"mk": "美团/时间线", "pe": "美团", "abs": "美团: 希望6月前完成POC，7月启动实施"},

    # ── 京东（5 条）──
    {"mk": "京东/刘洋", "pe": "京东", "abs": "京东/刘洋: IT总监，务实风格，关注落地效果不看概念"},
    {"mk": "京东/电商平台", "pe": "京东", "abs": "京东/电商平台: 1500万项目，需要和京东云深度集成"},
    {"mk": "京东/物流系统", "pe": "京东", "abs": "京东/物流系统: 800万项目，方案阶段，需要实时数据同步"},
    {"mk": "京东/预算", "pe": "京东", "abs": "京东: 预算审批需要过三级，CTO→CFO→CEO"},
    {"mk": "京东/POC", "pe": "京东", "abs": "京东/POC: 要求POC期间不能影响生产环境"},

    # ── 阿里巴巴（5 条）──
    {"mk": "阿里/马总", "pe": "阿里", "abs": "阿里/马总: 采购VP，谈判经验丰富，擅长压价"},
    {"mk": "阿里/云计算", "pe": "阿里", "abs": "阿里/云计算: 3000万项目，要求和阿里云原生集成"},
    {"mk": "阿里/内部竞争", "pe": "阿里", "abs": "阿里: 内部有自研CRM团队，外采需要证明比自研更好"},
    {"mk": "阿里/合同周期", "pe": "阿里", "abs": "阿里: 合同审批周期长，法务+采购+业务三方会签"},
    {"mk": "阿里/技术评审", "pe": "阿里", "abs": "阿里: 技术评审严格，需要过架构评审委员会"},

    # ── 百度（5 条）──
    {"mk": "百度/王总", "pe": "百度", "abs": "百度/王总: CTO办公室主任，喜欢数据说话，要求每次汇报带ROI分析"},
    {"mk": "百度/AI搜索", "pe": "百度", "abs": "百度/AI搜索: 2000万项目，谈判阶段，竞争对手是微软"},
    {"mk": "百度/自动驾驶", "pe": "百度", "abs": "百度/自动驾驶: 5000万项目，方案阶段，技术要求极高"},
    {"mk": "百度/预算", "pe": "百度", "abs": "百度: 今年AI方向预算充足，但传统IT预算在缩减"},
    {"mk": "百度/决策流程", "pe": "百度", "abs": "百度: 技术决策快但商务决策慢，需要耐心跟进"},

    # ── 通用经验（10 条）──
    {"mk": "金融行业方案", "pe": "", "abs": "金融行业方案: 安全资质前置，等保三级和SOC2是标配"},
    {"mk": "互联网行业方案", "pe": "", "abs": "互联网行业方案: 强调性能和可扩展性，支持快速迭代"},
    {"mk": "制造业方案", "pe": "", "abs": "制造业方案: 关注工厂部署和数据同步，需要离线能力"},
    {"mk": "客户分析流程", "pe": "", "abs": "客户分析流程: 基本信息→商机→联系人→活动→汇总"},
    {"mk": "报价通用策略", "pe": "", "abs": "报价策略: 先了解客户预算范围，再给出阶梯报价"},
    {"mk": "POC通用流程", "pe": "", "abs": "POC流程: 需求确认→环境准备→数据导入→演示→评估"},
    {"mk": "竞品应对策略", "pe": "", "abs": "竞品应对: 不要贬低竞品，突出自身差异化优势"},
    {"mk": "合同谈判经验", "pe": "", "abs": "合同谈判: 关注付款条件和SLA条款，避免无限责任"},
    {"mk": "查询报错经验", "pe": "", "abs": "查询报错: 字段名stage写成status，用query_schema确认可避免"},
    {"mk": "大客户跟进节奏", "pe": "", "abs": "大客户跟进: 每周至少一次有效触达，节假日前后重点关注"},
]


# ═══════════════════════════════════════════════════════════
# 200 条查询 — 20 种场景 × 10 个客户
# ═══════════════════════════════════════════════════════════

def generate_queries():
    """生成 200 条真实业务查询"""
    customers = [
        ("华为", ["张伟", "李娜", "ERP", "采购", "报价", "预算", "CRM", "安全审计"]),
        ("腾讯", ["王强", "数据中台", "POC", "用友", "报价", "赵经理", "AI平台"]),
        ("招行", ["陈刚", "风控", "合规", "刘总", "数据迁移", "培训", "安全"]),
        ("比亚迪", ["赵敏", "MES", "决策链", "工厂", "SAP", "Q3"]),
        ("小米", ["林总", "IoT", "智能工厂", "微服务", "周工"]),
        ("字节", ["孙丽", "广告平台", "Salesforce", "并发", "合同", "试用"]),
        ("美团", ["周明", "外卖SaaS", "数据安全", "纷享销客", "POC"]),
        ("京东", ["刘洋", "电商平台", "物流", "预算", "POC"]),
        ("阿里", ["马总", "云计算", "自研", "合同", "架构评审"]),
        ("百度", ["王总", "AI搜索", "自动驾驶", "预算", "决策"]),
    ]

    templates = [
        # 开会前准备（20 条）
        ("明天要去{c}开会，有什么需要注意的", "{c}", []),
        ("{c}那边开会前我要准备什么", "{c}", []),
        # 联系人风格（20 条）
        ("{c}的{p}是什么风格的人", "{c}", ["{p}"]),
        ("{p}这个人好沟通吗", "{c}", ["{p}"]),
        # 项目进展（20 条）
        ("{c}的项目现在什么情况", "{c}", []),
        ("{c}那边进展怎么样了", "{c}", []),
        # 报价策略（20 条）
        ("给{c}报价要注意什么", "{c}", ["报价"]),
        ("{c}对价格敏感吗", "{c}", ["价格"]),
        # 竞品信息（20 条）
        ("{c}那边有竞品吗", "{c}", []),
        ("哪些客户在评估竞品", None, []),
        # 签约流程（20 条）
        ("{c}签合同一般要多久", "{c}", []),
        ("{c}的审批流程是什么样的", "{c}", ["审批"]),
        # 模糊回忆（20 条）
        ("之前哪个客户说预算不够", None, ["预算"]),
        ("谁的决策链比较长", None, ["决策"]),
        # 行业经验（20 条）
        ("做金融客户要注意什么", None, ["安全"]),
        ("互联网客户有什么特点", None, ["性能"]),
        # POC 相关（20 条）
        ("{c}的POC结果怎么样", "{c}", ["POC"]),
        ("最近做过哪些POC", None, ["POC"]),
        # 时间窗口（20 条）
        ("{c}什么时候方便跟进", "{c}", []),
        ("最近哪些客户需要跟进", None, []),
    ]

    queries = []
    for ci, (cname, people) in enumerate(customers):
        for ti, (tpl, expect_parent, expect_kws) in enumerate(templates):
            p = people[ti % len(people)] if "{p}" in tpl else ""
            q = tpl.replace("{c}", cname).replace("{p}", p)
            ep = cname if expect_parent == "{c}" else expect_parent
            ek = [kw.replace("{p}", p) for kw in expect_kws]
            queries.append({"query": q, "expect_parent": ep, "expect_keywords": ek, "customer": cname})

    return queries[:200]


# ═══════════════════════════════════════════════════════════
# 检索方法
# ═══════════════════════════════════════════════════════════

async def flat_search(vdb, vec, query, uid, top_k=3):
    start = time.monotonic()
    try:
        r = vdb.hybrid_search(vec, query, top_k, f'user_id = "{uid}"')
    except Exception:
        r = vdb.search(vec, top_k, f'user_id = "{uid}"')
    return r, (time.monotonic() - start) * 1000


async def recursive_search(vdb, vec, query, uid, top_k=3):
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
            ch = vdb.search(vec, 10, f'user_id = "{uid}" and parent_uri = "{cu}"')
        except Exception:
            ch = []
        for c in ch:
            cid = c.get("id", "")
            if cid in seen: continue
            seen.add(cid)
            cs = float(c.get("score", 0))
            fs = 0.5 * cs + 0.5 * ps
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


def evaluate(results, q):
    all_text = " ".join(r.get("abstract", "") + " " + r.get("content", "") for r in results[:3])
    parent_hit = q["expect_parent"] in all_text if q["expect_parent"] else True
    kw_hits = sum(1 for kw in q["expect_keywords"] if kw in all_text) if q["expect_keywords"] else 0
    kw_total = len(q["expect_keywords"]) if q["expect_keywords"] else 0
    return parent_hit, kw_hits, kw_total


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════

async def main():
    from src.memory.viking_engine import VikingMemoryEngine
    emb = _emb()
    uid = "bench_user"

    e = VikingMemoryEngine(
        vdb_url="http://10.60.2.17", vdb_key="bRG3NETg13tv5Fn68VTdkxaJXH9tMQzhKeT3unck",
        database_name="viking_benchmark", collection_name="bench_v1",
        llm=None, use_pg=False,
    )

    # 写入数据
    print(f"写入 {len(MEMORIES)} 条记忆...")
    parents = set()
    for m in MEMORIES:
        vec = emb.embed_query(m["abs"])
        rid = str(uuid4())
        cat = "entities" if m["pe"] else ("patterns" if "流程" in m["mk"] or "策略" in m["mk"] else "cases")
        lu = e._build_uri(cat, m["mk"], m["pe"])
        pu = e._build_parent_uri(cat, m["pe"])
        e._vdb.upsert([{
            "id": rid, "vector": vec, "text": m["abs"],
            "abstract": m["abs"], "content": m["abs"],
            "category": cat, "merge_key": m["mk"],
            "parent_entity": m["pe"], "user_id": uid,
            "uri": lu, "parent_uri": pu, "is_leaf": "true",
        }])
        if m["pe"]:
            parents.add(m["pe"])

    # 创建目录节点
    print(f"创建 {len(parents)} 个目录节点...")
    for pe in parents:
        await e._ensure_directory_node("entities", pe, uid)

    print("等待索引构建...")
    time.sleep(10)

    # 生成查询
    queries = generate_queries()
    print(f"生成 {len(queries)} 条查询")

    # 预计算所有查询的向量（避免重复调用 embedding）
    print("预计算查询向量...")
    query_vecs = {}
    for q in queries:
        if q["query"] not in query_vecs:
            query_vecs[q["query"]] = emb.embed_query(q["query"])

    # 跑测试
    print(f"\n{'='*70}")
    print(f"  200 条查询基准测试")
    print(f"{'='*70}")

    flat_stats = {"parent_hit": 0, "kw_hit": 0, "kw_total": 0, "time": 0, "top1_hit": 0}
    rec_stats = {"parent_hit": 0, "kw_hit": 0, "kw_total": 0, "time": 0, "top1_hit": 0}
    n = len(queries)

    # 按场景分组统计
    scene_stats = {}  # scene_type → {flat_hit, rec_hit, total}

    for i, q in enumerate(queries):
        vec = query_vecs[q["query"]]
        scene = q["query"].split("，")[0][:10] if "，" in q["query"] else q["query"][:10]

        fr, ft = await flat_search(e._vdb, vec, q["query"], uid)
        rr, rt = await recursive_search(e._vdb, vec, q["query"], uid)

        fp, fkh, fkt = evaluate(fr, q)
        rp, rkh, rkt = evaluate(rr, q)

        flat_stats["parent_hit"] += int(fp)
        flat_stats["kw_hit"] += fkh
        flat_stats["kw_total"] += fkt
        flat_stats["time"] += ft
        if fr and q["expect_parent"] and q["expect_parent"] in fr[0].get("abstract", ""):
            flat_stats["top1_hit"] += 1

        rec_stats["parent_hit"] += int(rp)
        rec_stats["kw_hit"] += rkh
        rec_stats["kw_total"] += rkt
        rec_stats["time"] += rt
        if rr and q["expect_parent"] and q["expect_parent"] in rr[0].get("abstract", ""):
            rec_stats["top1_hit"] += 1

        # 场景统计
        customer = q["customer"]
        if customer not in scene_stats:
            scene_stats[customer] = {"flat_hit": 0, "rec_hit": 0, "total": 0}
        scene_stats[customer]["total"] += 1
        scene_stats[customer]["flat_hit"] += int(fp)
        scene_stats[customer]["rec_hit"] += int(rp)

        if (i + 1) % 50 == 0:
            print(f"  进度: {i+1}/{n}")

    # 输出结果
    queries_with_parent = sum(1 for q in queries if q["expect_parent"])
    queries_with_kw = sum(1 for q in queries if q["expect_keywords"])

    print(f"\n{'='*70}")
    print(f"  总体结果 ({n} 条查询)")
    print(f"{'='*70}")
    print(f"")
    print(f"  {'指标':<25} {'扁平检索':>12} {'递归检索':>12} {'差异':>10}")
    print(f"  {'─'*60}")
    print(f"  {'客户命中率 (Top-3)':<25} {flat_stats['parent_hit']/queries_with_parent:>11.1%} {rec_stats['parent_hit']/queries_with_parent:>11.1%} {(rec_stats['parent_hit']-flat_stats['parent_hit'])/max(queries_with_parent,1):>+9.1%}")
    print(f"  {'Top-1 精确命中':<25} {flat_stats['top1_hit']/queries_with_parent:>11.1%} {rec_stats['top1_hit']/queries_with_parent:>11.1%} {(rec_stats['top1_hit']-flat_stats['top1_hit'])/max(queries_with_parent,1):>+9.1%}")
    if flat_stats["kw_total"] > 0:
        print(f"  {'关键词召回率':<25} {flat_stats['kw_hit']/flat_stats['kw_total']:>11.1%} {rec_stats['kw_hit']/rec_stats['kw_total']:>11.1%} {(rec_stats['kw_hit']/rec_stats['kw_total']-flat_stats['kw_hit']/flat_stats['kw_total']):>+9.1%}")
    print(f"  {'平均耗时':<25} {flat_stats['time']/n:>10.0f}ms {rec_stats['time']/n:>10.0f}ms {rec_stats['time']/n-flat_stats['time']/n:>+8.0f}ms")
    print(f"  {'总耗时':<25} {flat_stats['time']:>10.0f}ms {rec_stats['time']:>10.0f}ms")

    print(f"\n  按客户分组:")
    print(f"  {'客户':<10} {'查询数':>5} {'扁平命中':>8} {'递归命中':>8} {'差异':>6}")
    print(f"  {'─'*40}")
    for customer in sorted(scene_stats.keys()):
        s = scene_stats[customer]
        print(f"  {customer:<10} {s['total']:>5} {s['flat_hit']:>8} {s['rec_hit']:>8} {s['rec_hit']-s['flat_hit']:>+5}")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
