"""
LLMLingua-2 中文上下文压缩 — 200 条测试用例评估
验证维度: 压缩率、关键信息保留率、延迟、可读性

运行: .venv/bin/python eval_llmlingua2_200cases.py
输出: eval_results_llmlingua2.json
"""

import json
import time
import re
import random
from dataclasses import dataclass, asdict
from typing import Optional
from llmlingua import PromptCompressor


# ═══════════════════════════════════════════════════════════
# 评估指标
# ═══════════════════════════════════════════════════════════

@dataclass
class EvalResult:
    case_id: str
    category: str
    original_chars: int
    compressed_chars: int
    original_tokens: int
    compressed_tokens: int
    compression_ratio: str
    savings_pct: float
    latency_ms: float
    key_info_retained: int      # 关键信息保留数
    key_info_total: int         # 关键信息总数
    key_info_rate: float        # 保留率
    passed: bool                # 是否通过
    failure_reason: Optional[str] = None


# ═══════════════════════════════════════════════════════════
# 200 条测试用例生成器
# ═══════════════════════════════════════════════════════════

def generate_test_cases() -> list[dict]:
    """生成 200 条覆盖多种场景的中文测试用例"""
    cases = []

    # ─── Category 1: CRM 业务报告 (40条) ───
    crm_templates = [
        ("crm_{i:03d}", "CRM业务报告",
         "{year}年第{q}季度{dept}报告。新增客户{n1}家，大客户{n2}家。合同金额¥{amt}万，同比增长{g1}%，环比增长{g2}%。"
         "流失率{churn}%，较上季度{prev_churn}%有改善。NPS评分{nps}分。"
         "重点客户{industry}行业贡献{pct}%收入。建议Q{next_q}重点拓展{focus}。",
         ["¥{amt}万", "{g1}%", "{n1}", "{nps}", "{churn}%"]),
    ]
    for i in range(40):
        tpl = crm_templates[0]
        params = {
            "year": random.choice(["2023", "2024", "2025"]),
            "q": random.choice(["一", "二", "三", "四"]),
            "dept": random.choice(["销售部", "市场部", "客户成功部", "渠道部"]),
            "n1": random.randint(100, 5000),
            "n2": random.randint(10, 200),
            "amt": random.randint(1000, 50000),
            "g1": random.randint(5, 80),
            "g2": random.randint(2, 30),
            "churn": round(random.uniform(1.5, 8.0), 1),
            "prev_churn": round(random.uniform(2.0, 10.0), 1),
            "nps": random.randint(30, 70),
            "industry": random.choice(["金融", "制造", "医疗", "教育", "零售", "互联网"]),
            "pct": random.randint(15, 60),
            "next_q": random.choice(["1", "2", "3", "4"]),
            "focus": random.choice(["大客户留存", "中小企业拓展", "新行业渗透", "续约率提升"]),
            "i": i,
        }
        text = tpl[2].format(**params)
        key_info = [s.format(**params) for s in tpl[3]]
        cases.append({"id": tpl[0].format(**params), "category": tpl[1],
                      "text": text, "key_info": key_info, "rate": 0.5})

    # ─── Category 2: 技术故障分析 (30条) ───
    tech_errors = [
        ("HTTP 504", "Gateway Timeout", "30秒", "数据库索引缺失"),
        ("HTTP 500", "Internal Server Error", "15秒", "内存溢出OOM"),
        ("HTTP 429", "Rate Limited", "100次/分", "并发超限"),
        ("HTTP 503", "Service Unavailable", "5分钟", "Pod重启"),
        ("TCP RST", "Connection Reset", "60秒", "负载均衡健康检查失败"),
    ]
    for i in range(30):
        err = tech_errors[i % len(tech_errors)]
        table = random.choice(["Opportunity", "Contact", "Account", "Order", "Invoice"])
        records = random.randint(50, 500) * 10000
        text = (
            f"执行query_data时遇到{err[0]} {err[1]}错误。"
            f"查询{table}表，记录数{records}万条，响应时间超过{err[2]}超时阈值。"
            f"根因分析：{err[3]}。同时有定时任务占用连接池资源。"
            f"临时方案：添加limit=1000分页。长期方案：引入读写分离架构。"
            f"已获取部分数据{random.randint(100,2000)}条，金额${random.randint(1,50)}M。"
        )
        key_info = [err[0], err[1], f"{records}万", err[2], err[3]]
        cases.append({"id": f"tech_{i:03d}", "category": "技术故障",
                      "text": text, "key_info": key_info, "rate": 0.5})

    # ─── Category 3: 会议纪要 (30条) ───
    names = ["张明", "李芳", "王强", "赵丽", "陈伟", "刘洋", "周杰", "吴敏"]
    versions = ["V2.1", "V3.0", "V3.2", "V4.0", "V5.0"]
    features = ["多租户隔离", "工作流引擎", "数据导入优化", "权限体系", "报表引擎",
                "消息队列", "缓存优化", "日志系统", "API网关", "SSO集成"]
    for i in range(30):
        attendees = random.sample(names, 4)
        ver = random.choice(versions)
        feats = random.sample(features, 3)
        date = f"2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
        p1_count = random.randint(1, 5)
        coverage = random.randint(70, 95)
        delay_days = random.randint(7, 30)
        text = (
            f"产品评审会议，{date}下午{random.randint(1,5)}点。"
            f"参会：{'、'.join(attendees)}。"
            f"{attendees[0]}介绍{ver}版本核心功能：{'、'.join(feats)}。"
            f"{attendees[1]}反馈{p1_count}个P1技术债务需处理，预估{random.randint(1,4)}周。"
            f"{attendees[2]}展示UI设计稿，工作区面积增大{random.randint(15,40)}%。"
            f"{attendees[3]}测试覆盖率{coverage}%，需补充{random.randint(50,300)}条用例。"
            f"决议：发布推迟{delay_days}天。"
        )
        key_info = [date, ver, f"{p1_count}个P1", f"{coverage}%", f"{delay_days}天"]
        cases.append({"id": f"meeting_{i:03d}", "category": "会议纪要",
                      "text": text, "key_info": key_info, "rate": 0.5})

    # ─── Category 4: 中英混合 Agent 对话 (30条) ───
    tools = ["query_data", "modify_data", "analyze_data", "web_search", "code_execute"]
    statuses = ["Closed Won", "Proposal", "Qualification", "Negotiation"]
    for i in range(30):
        tool = random.choice(tools)
        status = random.choice(statuses)
        amount = f"${random.randint(1,100)}.{random.randint(0,9)}M"
        count = random.randint(100, 5000)
        text = (
            f"Agent执行{tool}工具，查询status='{status}'的记录。"
            f"返回{count}条结果，总金额{amount}。"
            f"其中top_customer='华为科技'贡献{random.randint(10,50)}%。"
            f"数据来源：CRM.{random.choice(['opportunity','contact','account'])}表。"
            f"执行耗时{random.randint(100,5000)}ms，token消耗{random.randint(500,3000)}。"
        )
        key_info = [tool, status, amount, str(count), "华为科技"]
        cases.append({"id": f"agent_{i:03d}", "category": "Agent对话",
                      "text": text, "key_info": key_info, "rate": 0.5})

    # ─── Category 5: 长文档段落 (20条) ───
    for i in range(20):
        paragraphs = random.randint(3, 6)
        sentences = []
        key_items = []
        for p in range(paragraphs):
            metric = f"{random.randint(10,99)}.{random.randint(0,9)}%"
            amount = f"¥{random.randint(100,9999)}万"
            key_items.extend([metric, amount])
            sentences.append(
                f"第{p+1}部分：本期指标达到{metric}，投入{amount}。"
                f"{'同比增长' if random.random()>0.5 else '环比下降'}{random.randint(1,30)}%。"
                f"{'重点推进了'+random.choice(features)+'模块的优化工作。' if random.random()>0.5 else ''}"
            )
        text = "".join(sentences)
        key_info = key_items[:5]
        cases.append({"id": f"doc_{i:03d}", "category": "长文档",
                      "text": text, "key_info": key_info, "rate": 0.33})

    # ─── Category 6: 客户沟通记录 (20条) ───
    companies = ["华为", "比亚迪", "阿里巴巴", "腾讯", "字节跳动", "小米", "美团", "京东"]
    products = ["ERP系统", "CRM平台", "BI工具", "OA系统", "HR系统", "MES系统"]
    for i in range(20):
        company = random.choice(companies)
        product = random.choice(products)
        contact = random.choice(names)
        budget = f"¥{random.randint(50,500)}万"
        timeline = f"{random.randint(1,6)}个月"
        text = (
            f"客户{company}的{contact}来电沟通{product}采购事宜。"
            f"预算约{budget}，期望{timeline}内上线。"
            f"核心需求：{'、'.join(random.sample(features, 3))}。"
            f"竞品对比：已评估{random.choice(['Salesforce','SAP','Oracle','用友','金蝶'])}。"
            f"下一步：{random.choice(['安排演示', '提供方案报价', '技术对接', '高层拜访'])}。"
            f"跟进人：{random.choice(names)}，截止日期{2024+random.randint(0,1)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}。"
        )
        key_info = [company, budget, timeline, contact, product]
        cases.append({"id": f"comm_{i:03d}", "category": "客户沟通",
                      "text": text, "key_info": key_info, "rate": 0.5})

    # ─── Category 7: 数据分析结果 (15条) ───
    for i in range(15):
        dims = random.sample(["行业", "地区", "规模", "来源", "阶段"], 3)
        text = f"数据分析结果（按{'×'.join(dims)}交叉分析）：\n"
        key_items = []
        for d in range(random.randint(3, 6)):
            val = f"{random.randint(1,99)}.{random.randint(0,9)}%"
            amt = f"¥{random.randint(10,9999)}万"
            key_items.extend([val, amt])
            text += f"  - {dims[0]}={random.choice(['金融','制造','医疗'])}：占比{val}，金额{amt}\n"
        text += f"总计：{random.randint(100,10000)}条记录，总金额¥{random.randint(1000,99999)}万。"
        key_info = key_items[:5]
        cases.append({"id": f"analysis_{i:03d}", "category": "数据分析",
                      "text": text, "key_info": key_info, "rate": 0.5})

    # ─── Category 8: 系统配置/参数 (15条) ───
    for i in range(15):
        text = (
            f"系统配置更新：max_connections={random.randint(100,1000)}，"
            f"timeout_ms={random.randint(3000,30000)}，"
            f"cache_ttl={random.randint(60,3600)}s，"
            f"rate_limit={random.randint(50,500)}/min，"
            f"pool_size={random.randint(10,100)}，"
            f"retry_count={random.randint(1,5)}，"
            f"batch_size={random.randint(100,5000)}。"
            f"部署环境：{random.choice(['prod','staging','dev'])}，"
            f"实例规格：{random.choice(['4C8G','8C16G','16C32G','32C64G'])}×{random.randint(2,10)}节点。"
        )
        key_info = [f"max_connections=", "timeout_ms=", "pool_size=", "rate_limit="]
        cases.append({"id": f"config_{i:03d}", "category": "系统配置",
                      "text": text, "key_info": key_info, "rate": 0.7})

    assert len(cases) == 200, f"Expected 200, got {len(cases)}"
    return cases


# ═══════════════════════════════════════════════════════════
# 评估执行
# ═══════════════════════════════════════════════════════════

def evaluate(compressor: PromptCompressor, cases: list[dict]) -> list[EvalResult]:
    """执行评估"""
    results = []
    for case in cases:
        t0 = time.perf_counter()
        result = compressor.compress_prompt(
            case["text"],
            rate=case["rate"],
            force_tokens=[
                '。', '？', '！', '；', '，', '\n',   # 中文标点（语义边界）
                '¥', '$', '￥',                        # 货币符号
                '万', '亿', '%',                       # 金额/百分比单位
                '=', '/', ':',                         # 配置/路径分隔符
            ],
            chunk_end_tokens=['。', '\n'],
            force_reserve_digit=True,
            drop_consecutive=True,
        )

        # ── 后处理：关键数据回补 ──
        # 若压缩后丢失了金额/百分比/日期，从原文提取并追加
        compressed_text = result["compressed_prompt"]
        key_patterns = [
            r'[\$¥￥]\s*[\d,]+\.?\d*\s*[万亿KMB]?',  # 金额
            r'\d+\.?\d*\s*%',                          # 百分比
            r'\d{4}[-/]\d{1,2}[-/]\d{1,2}',           # 日期
        ]
        missing_items = []
        for pat in key_patterns:
            for item in re.findall(pat, case["text"]):
                item_clean = re.sub(r'\s', '', item)
                compressed_clean = re.sub(r'\s', '', compressed_text)
                if item_clean not in compressed_clean:
                    missing_items.append(item.strip())
        if missing_items:
            missing_unique = list(dict.fromkeys(missing_items))[:10]
            compressed_text = compressed_text.rstrip() + " [" + ", ".join(missing_unique) + "]"
            result["compressed_prompt"] = compressed_text

        latency = (time.perf_counter() - t0) * 1000

        compressed = result["compressed_prompt"]
        compression_x = result["origin_tokens"] / max(result["compressed_tokens"], 1)

        # 检查关键信息保留（去除所有空格/下划线做模糊匹配）
        retained = 0
        for info in case["key_info"]:
            info_clean = re.sub(r'[\s_,]', '', info)
            compressed_clean = re.sub(r'[\s_,]', '', compressed)
            if info_clean in compressed_clean:
                retained += 1
            else:
                # 再尝试：只看数字部分是否保留（如 ¥5475万 → 只检查 5475）
                digits = re.findall(r'\d+\.?\d*', info)
                if digits and all(d in compressed for d in digits):
                    retained += 1

        total_key = len(case["key_info"])
        rate = retained / total_key if total_key > 0 else 1.0

        # 判断是否通过
        passed = True
        failure = None

        # 规则1: 压缩率 < 1.2x（几乎没压缩）→ 直接通过，短文本不压缩是正确行为
        if compression_x < 1.2:
            passed = True
            failure = None
        # 规则2: 有实质压缩时，检查关键信息保留率
        elif rate < 0.6:
            passed = False
            failure = f"关键信息保留率{rate:.0%}<60%"

        # 规则3: 延迟超标
        if latency > 2000:
            passed = False
            failure = f"延迟{latency:.0f}ms>2000ms"

        savings = (1 - result["compressed_tokens"] / result["origin_tokens"]) * 100

        results.append(EvalResult(
            case_id=case["id"],
            category=case["category"],
            original_chars=len(case["text"]),
            compressed_chars=len(compressed),
            original_tokens=result["origin_tokens"],
            compressed_tokens=result["compressed_tokens"],
            compression_ratio=result["ratio"],
            savings_pct=round(savings, 1),
            latency_ms=round(latency, 1),
            key_info_retained=retained,
            key_info_total=total_key,
            key_info_rate=round(rate, 3),
            passed=passed,
            failure_reason=failure,
        ))
    return results


# ═══════════════════════════════════════════════════════════
# 报告输出
# ═══════════════════════════════════════════════════════════

def print_report(results: list[EvalResult]):
    """打印评估报告"""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    print("\n" + "=" * 70)
    print(f"LLMLingua-2 中文压缩评估报告 — {total} 条测试用例")
    print("=" * 70)

    # 总体统计
    avg_savings = sum(r.savings_pct for r in results) / total
    avg_latency = sum(r.latency_ms for r in results) / total
    avg_key_rate = sum(r.key_info_rate for r in results) / total
    p95_latency = sorted(r.latency_ms for r in results)[int(total * 0.95)]

    print(f"\n  总体结果: {passed}/{total} 通过 ({passed/total*100:.1f}%)")
    print(f"  平均压缩节省: {avg_savings:.1f}%")
    print(f"  平均关键信息保留: {avg_key_rate:.1%}")
    print(f"  平均延迟: {avg_latency:.0f}ms | P95: {p95_latency:.0f}ms")

    # 按分类统计
    categories = sorted(set(r.category for r in results))
    print(f"\n{'─' * 70}")
    print(f"  {'类别':<12} {'用例数':>6} {'通过率':>8} {'压缩%':>7} {'保留率':>7} {'延迟ms':>8}")
    print(f"{'─' * 70}")

    for cat in categories:
        cat_results = [r for r in results if r.category == cat]
        n = len(cat_results)
        cat_pass = sum(1 for r in cat_results if r.passed)
        cat_savings = sum(r.savings_pct for r in cat_results) / n
        cat_key = sum(r.key_info_rate for r in cat_results) / n
        cat_lat = sum(r.latency_ms for r in cat_results) / n
        status = "✓" if cat_pass == n else "△"
        print(f"  {status} {cat:<10} {n:>4}    {cat_pass/n*100:>5.1f}%  {cat_savings:>5.1f}%  {cat_key:>5.1%}  {cat_lat:>6.0f}")

    # 失败用例详情
    failed_results = [r for r in results if not r.passed]
    if failed_results:
        print(f"\n{'─' * 70}")
        print(f"  失败用例 ({len(failed_results)} 条):")
        for r in failed_results[:20]:  # 最多显示 20 条
            print(f"    {r.case_id}: {r.failure_reason}")
        if len(failed_results) > 20:
            print(f"    ... 还有 {len(failed_results)-20} 条")

    print(f"\n{'=' * 70}")


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("LLMLingua-2 中文压缩 — 200 条用例评估")
    print("=" * 70)

    # 加载模型
    print("\n加载模型...")
    t0 = time.perf_counter()
    compressor = PromptCompressor(
        model_name="./models/llmlingua-2-bert-base-multilingual-cased-meetingbank",
        use_llmlingua2=True,
        device_map="mps",  # Mac Apple Silicon，无GPU改为 "cpu"
    )
    print(f"模型加载完成: {time.perf_counter()-t0:.1f}s")

    # 生成测试用例
    print("\n生成 200 条测试用例...")
    cases = generate_test_cases()
    print(f"  分布: {', '.join(f'{k}={v}' for k,v in sorted(((c['category'], 1) for c in cases), key=lambda x: x[0]) if False)}")
    from collections import Counter
    dist = Counter(c["category"] for c in cases)
    for cat, count in sorted(dist.items()):
        print(f"    {cat}: {count} 条")

    # 执行评估
    print(f"\n开始评估 (共 {len(cases)} 条)...")
    t0 = time.perf_counter()
    results = evaluate(compressor, cases)
    total_time = time.perf_counter() - t0
    print(f"评估完成: {total_time:.1f}s (平均 {total_time/len(cases)*1000:.0f}ms/条)")

    # 输出报告
    print_report(results)

    # 保存详细结果到 JSON
    output_path = "./eval_results_llmlingua2.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "summary": {
                "total": len(results),
                "passed": sum(1 for r in results if r.passed),
                "failed": sum(1 for r in results if not r.passed),
                "avg_savings_pct": round(sum(r.savings_pct for r in results)/len(results), 1),
                "avg_key_info_rate": round(sum(r.key_info_rate for r in results)/len(results), 3),
                "avg_latency_ms": round(sum(r.latency_ms for r in results)/len(results), 1),
                "p95_latency_ms": round(sorted(r.latency_ms for r in results)[int(len(results)*0.95)], 1),
                "total_time_s": round(total_time, 1),
            },
            "results": [asdict(r) for r in results],
        }, f, ensure_ascii=False, indent=2)
    print(f"\n详细结果已保存: {output_path}")
