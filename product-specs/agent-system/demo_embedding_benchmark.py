"""Embedding 性能对比 — Qwen3-0.6B 本地 vs doubao 远程 API

200 条验证数据，覆盖短文本（10-50字）、中文本（50-200字）、长文本（200-800字）。
逐条计时，输出延迟分布、按文本长度分组对比。

运行：python demo_embedding_benchmark.py
"""
from __future__ import annotations

import json
import logging
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

_REMOTE_EMBED_MODEL = os.environ.get("EMBEDDING_MODEL", "doubao-embedding-text-240715")
_REMOTE_EMBED_KEY = os.environ.get("EMBEDDING_API_KEY") or os.environ.get(
    "DOUBAO_API_KEY", "651621e7-e495-4728-93ef-ed380e9ddcd1")
_REMOTE_EMBED_BASE = os.environ.get("EMBEDDING_API_BASE", "https://ark.cn-beijing.volces.com/api/v3/")


# ═══════════════════════════════════════════════════════════
# 构建 200 条测试文本（短/中/长各段覆盖）
# ═══════════════════════════════════════════════════════════

def build_test_texts() -> list[dict]:
    """生成 200 条测试文本，按长度分 4 档"""
    texts = []

    # ── A. 短文本 10-50 字（50 条）── 模拟 query / 记忆摘要
    short_samples = [
        "华为ERP项目报价",
        "PT Sentosa 客户信息",
        "腾讯云技术方案¥68万",
        "比亚迪签约¥150万",
        "pipeline总览分析",
        "CV XYZ合同续约",
        "SAP竞品定价对比",
        "张总是VP级决策者",
        "商机negotiation阶段",
        "POC通过效率提升42%",
        "Odoo定价$24.90/user/month",
        "报价Q-001已更新$40K",
        "BANT分析预算¥500万",
        "风险商机PT Sentosa",
        "3年锁定$20K/year",
        "GraphQL协议保留",
        "实施周期8周",
        "里程碑付款20%+40%+20%+20%",
        "多租户Schema级隔离",
        "日志审计ELK方案",
        "供应链管理模块",
        "opp_BYD_001已成交",
        "REQ-TC-001 API对接需求",
        "华为POC方案4周",
        "腾讯云砍价到¥60万",
        "本月forecast ¥320万",
        "制造业客户Jakarta",
        "9万人年营收¥6023亿",
        "决策链张总李工王助理",
        "付款条件签约30%上线40%验收30%",
        "活动记录3/10会议",
        "合同con_005到期2025-06-30",
        "报价有效期30天",
        "P0需求API对接",
        "技术评估IT总监",
        "自动续约关闭",
        "Salesforce竞品威胁",
        "年费$22K涨价10%",
        "SLA升级去掉",
        "数字化转型ERP替换",
        "处理效率提升30%目标",
        "2SA+1PM资源配置",
        "Schema级隔离+行级权限",
        "RESTful+GraphQL双协议",
        "客户砍价要求降到$40K",
        "折扣15%最终$38250",
        "成功标准效率提升",
        "预计2025-05-15关闭",
        "A级客户汽车制造",
        "S级客户ICT行业",
    ]

    # ── B. 中文本 50-200 字（70 条）── 模拟对话存档摘要
    medium_samples = [
        "PT Sentosa Jaya是一家位于Jakarta的制造业公司，200人规模，年营收$5M。当前有商机opp_001金额$45K处于proposal阶段，预计2025-05-15关闭，负责人Andi。",
        "华为科技ICT行业20.7万人年营收¥8809亿S级客户。BANT分析：Budget ¥500万以上，Authority 张总VP级决策者，Need 数字化转型ERP替换，Timeline Q3启动POC。",
        "腾讯云需求清单：P0级API对接REQ-TC-001、P0级多租户隔离REQ-TC-002、P1级日志审计REQ-TC-003。技术方案TP-TC-001包含RESTful+GraphQL双协议和Schema级隔离。",
        "比亚迪汽车制造业9万人年营收¥6023亿A级客户。商机opp_BYD_001金额¥150万negotiation阶段预计2025-04-30成交产品供应链管理模块。最终全款签约合同CON-BYD-001。",
        "CV XYZ合同con_005将于2025-06-30到期年费$20K不自动续约。续约方案涨价10%至$22K但客户不接受，最终选择3年锁定$20K/year方案，新到期日2028-06-30。",
        "报价Q-001总价$45K年付15%折扣=$38250。付款签约30%+上线40%+验收30%。含8周实施+3个月免费支持。客户要求降到$40K，确认更新后折扣后$34000。",
        "华为POC方案POC-HW-001为期4周范围采购模块+审批流成功标准处理效率提升30%资源2SA+1PM。最终POC通过效率提升42%超过目标，张总满意李工提出集成需求。",
        "SAP S/4HANA Cloud报价$150-300/user/month华为规模年费约¥3000万。Odoo标准$24.90/user/month加Manufacturing $18总计$42.90，200人年费约$103K比我们贵一倍。",
        "腾讯云报价Q-TC-001总额¥80万里程碑付款需求确认20%开发完成40%验收20%上线20%有效期30天。客户要求¥60万需砍掉GraphQL和实时告警，最终¥68万保留GraphQL降级日志。",
        "Pipeline总览总额¥850万12个商机。本月成交¥150万比亚迪，预测未来30天¥320万。高风险商机PT Sentosa报价反复决策周期长，腾讯云预算压缩技术选型未定。",
        "上周华为互动3/10会议张总李工POC汇报讨论商务条款，3/12邮件发王助理正式报价¥480万。张总说太高要求¥420万需减少实施周期或去掉定制模块。",
        "华为最终报价Q-HW-001金额¥450万实施8周全部模块保留。从¥480万降到¥450万的折中方案是减少实施周期从12周到8周保留全部功能模块不做裁剪。",
        "本周进展PT Sentosa报价$40K已确认，CV XYZ三年锁定$20K续约完成，华为¥450万待审批，腾讯云¥68万已确认，比亚迪¥150万已签约成交。",
        "客户决策链分析华为科技张总VP数字化决策者李工IT总监技术评估王助理采购经理流程推进。需要分别对接不同角色满足技术和商务双重要求。",
        "竞品分析报告Salesforce在接触CV XYZ续约客户存在竞争压力中等，SAP在华为市场报价¥3000万远高于我们¥500万方案，Odoo在PT Sentosa市场年费$103K高于我们$45K。",
    ]

    # ── C. 长文本 200-500 字（50 条）── 模拟完整工具返回结果
    long_samples = [
        "华为科技ERP项目完整分析报告：客户画像ICT行业20.7万人年营收¥8809亿S级客户客户经理张磊。BANT分析Budget ¥500万以上Authority张总VP级决策者Need数字化转型ERP替换Timeline Q3启动POC。决策链张总VP数字化决策者→李工IT总监技术评估→王助理采购经理流程推进。POC方案POC-HW-001为期4周范围采购模块+审批流成功标准处理效率提升30%资源2SA+1PM。POC结果通过效率提升42%超过30%目标张总满意李工提出系统集成需求下一步进入商务谈判。竞品SAP S/4HANA Cloud报价$150-300/user/month华为规模年费约¥3000万我们方案可以做到¥500万以内价格优势明显。",
        "PT Sentosa商机全流程记录：查询客户信息PT Sentosa Jaya制造业200人年营收$5M位于Jakarta。商机opp_001金额$45K proposal阶段预计2025-05-15关闭负责人Andi。生成报价Q-001总价$45K年付15%折扣=$38250付款签约30%上线40%验收30%含8周实施+3个月免费支持。竞品Odoo标准$24.90/user/month加Manufacturing $18总计$42.90，200人年费约$103K比我们贵一倍多竞争优势明显。客户反馈报价太贵要求降到$40K。确认更新报价Q-001总价$40K折扣后$34000付款条件不变。整个流程从查询到报价确认共6轮对话。",
        "腾讯云技术方案与报价谈判全记录：需求调研P0级API对接REQ-TC-001和P0级多租户隔离REQ-TC-002以及P1级日志审计REQ-TC-003。技术方案TP-TC-001包含RESTful+GraphQL双协议Schema级隔离+行级权限ELK日志审计+实时告警交付周期8周费用¥80万。报价Q-TC-001总额¥80万里程碑付款需求确认20%开发完成40%验收20%上线20%有效期30天。客户反馈¥80万太贵最多¥60万需要砍掉GraphQL和实时告警只保留RESTful+Schema隔离+基础日志。最终折中方案¥68万GraphQL必须保留日志审计降级不含实时告警。",
        "CV XYZ合同续约分析与决策过程：合同con_005将于2025-06-30到期年费$20K不自动续约。续约方案一涨价10%至$22K/year理由新增AI功能+SLA升级。风险评估Salesforce在接触客户竞争压力中等。客户反馈不接受涨价要求维持$20K原价。方案调整建议一去掉SLA升级保留AI功能维持原价，建议二签3年锁定当前价格$20K/year。客户最终选择3年锁定方案已更新合同con_005三年期锁定$20K/year新到期日2028-06-30。关键决策点客户看重价格稳定性愿意用长期承诺换取不涨价。",
        "Pipeline与风险分析汇总报告：总额¥850万共12个商机分布prospecting 3个qualification 2个proposal 3个negotiation 2个closing 2个。本月成交¥150万来自比亚迪opp_BYD_001供应链管理模块全款签约合同CON-BYD-001。预测未来30天成交¥320万。高风险商机列表第一PT Sentosa opp_001报价反复决策周期长金额$40K已确认但尚未进入签约流程，第二腾讯云预算压缩技术选型未定报价¥68万已确认但正式合同未签。建议对高风险商机加强跟进频率每周至少一次有效触达避免被竞品抢走。",
    ]

    # ── D. 超长文本 500-800 字（30 条）── 模拟完整对话上下文压缩
    extra_long_base = (
        "以下是一段完整的CRM销售对话上下文存档，包含客户信息查询、商机分析、报价生成、竞品调研、砍价谈判和最终确认等多个环节。"
        "销售人员通过Agent系统依次调用了query_data查询客户基本信息和商机状态，analyze_data生成BANT分析和报价方案，"
        "web_search调研竞品SAP和Odoo的定价策略，execute_task执行报价更新和合同签约操作。"
        "整个对话涉及多个业务实体包括客户华为科技、联系人张总李工王助理、商机opp_HW_001、报价Q-HW-001、POC方案POC-HW-001等。"
        "关键决策节点包括POC通过后进入商务谈判、张总要求从¥480万降价、最终折中¥450万保留全部模块但缩短实施周期从12周到8周。"
        "该存档需要支持后续的变更追踪查询如报价金额变化历史、决策过程追踪如为什么降价、时间线查询如从POC到报价确认的完整过程、"
        "以及跨客户对比分析如华为和腾讯云的报价策略差异等多种检索场景。"
    )

    # 生成 200 条
    idx = 0
    # 短文本 50 条
    for s in short_samples[:50]:
        texts.append({"id": idx, "text": s, "length": len(s), "group": "short"})
        idx += 1

    # 中文本 70 条（15 个样本循环 + 变体）
    for i in range(70):
        base = medium_samples[i % len(medium_samples)]
        if i >= len(medium_samples):
            base = base + f"（变体{i}）"
        texts.append({"id": idx, "text": base[:200], "length": len(base[:200]), "group": "medium"})
        idx += 1

    # 长文本 50 条
    for i in range(50):
        base = long_samples[i % len(long_samples)]
        if i >= len(long_samples):
            base = base + f"补充信息变体{i}：额外的业务上下文描述，包含更多客户交互细节和决策过程记录。"
        texts.append({"id": idx, "text": base[:500], "length": len(base[:500]), "group": "long"})
        idx += 1

    # 超长文本 30 条
    for i in range(30):
        variant = extra_long_base + f" 变体{i}：第{i+1}轮对话中还讨论了实施计划的具体时间节点和资源分配方案，涉及项目经理SA和技术支持人员的排期协调。"
        texts.append({"id": idx, "text": variant[:800], "length": len(variant[:800]), "group": "extra_long"})
        idx += 1

    return texts


# ═══════════════════════════════════════════════════════════
# Benchmark 执行
# ═══════════════════════════════════════════════════════════

def benchmark_local(texts: list[dict]) -> list[dict]:
    """Qwen3-Embedding-0.6B 本地逐条测试"""
    from src.embedding import LocalEmbedding
    emb = LocalEmbedding()
    # 额外 warmup
    emb.embed_query("warmup text for stable timing")
    emb.embed_query("second warmup to stabilize MPS")

    results = []
    for i, item in enumerate(texts):
        if i % 50 == 0:
            logger.info("[Qwen3] Progress: %d/%d", i, len(texts))
        t0 = time.time()
        vec = emb.embed_query_np(item["text"])
        ms = (time.time() - t0) * 1000
        results.append({"id": item["id"], "group": item["group"], "length": item["length"],
                        "ms": ms, "dim": len(vec)})
    return results


def benchmark_remote(texts: list[dict]) -> list[dict]:
    """doubao-embedding 远程 API 逐条测试"""
    from langchain_openai import OpenAIEmbeddings
    emb = OpenAIEmbeddings(
        model=_REMOTE_EMBED_MODEL, api_key=_REMOTE_EMBED_KEY,
        base_url=_REMOTE_EMBED_BASE, check_embedding_ctx_length=False,
    )
    # Warmup
    emb.embed_query("warmup")
    emb.embed_query("second warmup")

    results = []
    for i, item in enumerate(texts):
        if i % 50 == 0:
            logger.info("[doubao] Progress: %d/%d", i, len(texts))
        t0 = time.time()
        vec = emb.embed_query(item["text"])
        ms = (time.time() - t0) * 1000
        results.append({"id": item["id"], "group": item["group"], "length": item["length"],
                        "ms": ms, "dim": len(vec)})
    return results


# ═══════════════════════════════════════════════════════════
# 统计 + 报告
# ═══════════════════════════════════════════════════════════

def stats(times: list[float]) -> dict:
    s = sorted(times)
    n = len(s)
    return {
        "count": n,
        "avg": round(statistics.mean(s), 1),
        "p50": round(s[n // 2], 1),
        "p95": round(s[int(n * 0.95)], 1),
        "p99": round(s[int(n * 0.99)], 1),
        "min": round(s[0], 1),
        "max": round(s[-1], 1),
        "std": round(statistics.stdev(s), 1) if n > 1 else 0,
    }


def print_report(local_results, remote_results, texts):
    local_ms = [r["ms"] for r in local_results]
    remote_ms = [r["ms"] for r in remote_results]
    local_stats = stats(local_ms)
    remote_stats = stats(remote_ms)

    print(f"\n{'═'*72}")
    print(f"  Embedding 性能对比 — Qwen3-0.6B (本地) vs doubao (远程 API)")
    print(f"  测试数据: {len(texts)} 条 | 短(≤50字) {sum(1 for t in texts if t['group']=='short')}"
          f" + 中(50-200字) {sum(1 for t in texts if t['group']=='medium')}"
          f" + 长(200-500字) {sum(1 for t in texts if t['group']=='long')}"
          f" + 超长(500-800字) {sum(1 for t in texts if t['group']=='extra_long')}")
    print(f"{'═'*72}")

    # 总体对比
    print(f"\n── 总体延迟对比（{len(texts)} 条逐条计时）────────────────")
    print(f"  ┌─────────────┬──────────────────┬──────────────────┐")
    print(f"  │ 指标        │ Qwen3 本地 (MPS) │ doubao 远程 API  │")
    print(f"  ├─────────────┼──────────────────┼──────────────────┤")
    print(f"  │ 平均        │ {local_stats['avg']:>8.1f}ms       │ {remote_stats['avg']:>8.1f}ms       │")
    print(f"  │ P50         │ {local_stats['p50']:>8.1f}ms       │ {remote_stats['p50']:>8.1f}ms       │")
    print(f"  │ P95         │ {local_stats['p95']:>8.1f}ms       │ {remote_stats['p95']:>8.1f}ms       │")
    print(f"  │ P99         │ {local_stats['p99']:>8.1f}ms       │ {remote_stats['p99']:>8.1f}ms       │")
    print(f"  │ Min         │ {local_stats['min']:>8.1f}ms       │ {remote_stats['min']:>8.1f}ms       │")
    print(f"  │ Max         │ {local_stats['max']:>8.1f}ms       │ {remote_stats['max']:>8.1f}ms       │")
    print(f"  │ 标准差      │ {local_stats['std']:>8.1f}ms       │ {remote_stats['std']:>8.1f}ms       │")
    print(f"  │ 维度        │ {local_results[0]['dim']:>8d}         │ {remote_results[0]['dim']:>8d}         │")
    ratio = remote_stats['avg'] / max(local_stats['avg'], 0.1)
    print(f"  │ 倍数        │      1x          │    {ratio:>5.2f}x        │")
    print(f"  └─────────────┴──────────────────┴──────────────────┘")

    # 按文本长度分组
    groups = ["short", "medium", "long", "extra_long"]
    group_names = {"short": "短(≤50字)", "medium": "中(50-200字)", "long": "长(200-500字)", "extra_long": "超长(500-800字)"}

    print(f"\n── 按文本长度分组对比 ────────────────────────────────")
    print(f"  ┌──────────────────┬──────────┬──────────┬──────────┐")
    print(f"  │ 文本长度         │ Qwen3 P50│ doubao P50│ 倍数    │")
    print(f"  ├──────────────────┼──────────┼──────────┼──────────┤")

    for g in groups:
        l_times = [r["ms"] for r in local_results if r["group"] == g]
        r_times = [r["ms"] for r in remote_results if r["group"] == g]
        if not l_times or not r_times:
            continue
        l_p50 = sorted(l_times)[len(l_times) // 2]
        r_p50 = sorted(r_times)[len(r_times) // 2]
        r_ratio = r_p50 / max(l_p50, 0.1)
        name = group_names.get(g, g)
        print(f"  │ {name:<16} │ {l_p50:>6.1f}ms │ {r_p50:>6.1f}ms │  {r_ratio:>4.2f}x  │")

    print(f"  └──────────────────┴──────────┴──────────┴──────────┘")

    # 文本长度 vs 延迟散点分析
    print(f"\n── 文本长度与延迟关系 ────────────────────────────────")
    print(f"  Qwen3 (本地): 文本长度对延迟影响{'大' if local_stats['std'] > 50 else '小'}（std={local_stats['std']:.1f}ms）")
    print(f"  doubao (远程): 文本长度对延迟影响{'大' if remote_stats['std'] > 50 else '小'}（std={remote_stats['std']:.1f}ms）")

    # 稳定性对比
    local_cv = local_stats['std'] / max(local_stats['avg'], 0.1)
    remote_cv = remote_stats['std'] / max(remote_stats['avg'], 0.1)
    print(f"\n── 稳定性（变异系数 CV = std/avg）────────────────────")
    print(f"  Qwen3:  CV = {local_cv:.2f} {'(稳定)' if local_cv < 0.3 else '(波动较大)'}")
    print(f"  doubao: CV = {remote_cv:.2f} {'(稳定)' if remote_cv < 0.3 else '(波动较大)'}")

    print(f"\n{'═'*72}\n")


def main():
    texts = build_test_texts()
    logger.info("Generated %d test texts", len(texts))
    logger.info("Distribution: short=%d medium=%d long=%d extra_long=%d",
                sum(1 for t in texts if t["group"] == "short"),
                sum(1 for t in texts if t["group"] == "medium"),
                sum(1 for t in texts if t["group"] == "long"),
                sum(1 for t in texts if t["group"] == "extra_long"))

    print(f"\n🚀 Embedding 性能对比 Benchmark（200 条逐条计时）\n")

    # Qwen3 本地
    logger.info("=== Qwen3-Embedding-0.6B (本地) ===")
    local_results = benchmark_local(texts)

    # doubao 远程
    logger.info("=== doubao-embedding (远程 API) ===")
    remote_results = benchmark_remote(texts)

    # 输出报告
    print_report(local_results, remote_results, texts)

    # 保存
    output = {
        "test_config": {"count": len(texts), "groups": {"short": 50, "medium": 70, "long": 50, "extra_long": 30}},
        "qwen3_local": {"device": "mps", "model": "Qwen3-Embedding-0.6B", "dim": 1024,
                        "stats": stats([r["ms"] for r in local_results]),
                        "by_group": {g: stats([r["ms"] for r in local_results if r["group"] == g])
                                     for g in ["short", "medium", "long", "extra_long"]}},
        "doubao_remote": {"model": "doubao-embedding-text-240715", "dim": 2560,
                          "stats": stats([r["ms"] for r in remote_results]),
                          "by_group": {g: stats([r["ms"] for r in remote_results if r["group"] == g])
                                       for g in ["short", "medium", "long", "extra_long"]}},
        "raw_results": {"local": local_results, "remote": remote_results},
    }
    out_path = "data/eval/runs/embedding_benchmark.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(output, fp, ensure_ascii=False, indent=2)
    print(f"  📊 详细数据: {out_path}\n")


if __name__ == "__main__":
    main()
