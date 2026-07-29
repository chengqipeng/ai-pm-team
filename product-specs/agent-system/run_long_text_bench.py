"""长文本性能验证: 6000字 + 20000字 用例"""
import json, time, subprocess, random

random.seed(42)

BASE_URL = "https://llmlingua.ingageapp.com"
FORCE_TOKENS = ["\u3002","\uff1f","\uff01","\uff1b","\uff0c","\uff1a","\n","=","_","-"]
CHUNK_END = ["\u3002","\uff1f","\uff01","\uff1b","\n"]

services = ["API Gateway","Auth Service","CRM Core","Billing","Notification","Analytics","Search","Cache"]
tools = ["query_data","modify_data","analyze_data","web_search","knowledge_search"]

def gen_cases():
    cases = []

    # 6K-1: CRM详细报告
    paras = []
    for i in range(20):
        ind = ["金融","制造","医疗","教育","零售","互联网","能源","物流"][i%8]
        reg = ["华东","华南","华北","西南","东北","西北","华中"][i%7]
        paras.append(
            f"第{i+1}章：{ind}行业{reg}地区分析。"
            f"本季度该区域新增客户{random.randint(50,500)}家，合同金额¥{random.randint(100,5000)}万，同比增长{random.randint(-10,60)}%。"
            f"客户流失率{round(random.uniform(1,8),1)}%，NPS评分{random.randint(30,70)}分。"
            f"重点客户包括{random.choice(['华为','腾讯','阿里','字节','美团','京东'])}等。"
            f"建议下季度重点关注{random.choice(['大客户续约','中小企业拓展','行业解决方案'])}策略。"
            f"竞品动态：{random.choice(['Salesforce','SAP','Oracle','用友','金蝶'])}近期在该区域有新动作，需重点关注其定价策略和产品迭代方向。"
        )
    text_6k_1 = "\n".join(paras)
    cases.append({"name": "6K-1 CRM详细报告", "text": text_6k_1, "key": ["华东","NPS","金融","¥","%"], "rate": 0.5})

    # 6K-2: 技术架构文档
    sections = []
    for svc in services:
        sections.append(
            f"## {svc}服务\n"
            f"部署规格：{random.choice(['4C8G','8C16G','16C32G'])} x {random.randint(2,10)}节点。\n"
            f"当前QPS={random.randint(100,5000)}，P99延迟={random.randint(10,500)}ms，错误率={round(random.uniform(0.01,2),2)}%。\n"
            f"依赖：{random.choice(services)}、{random.choice(services)}。\n"
            f"告警：{random.choice(['内存超85%','连接池耗尽','GC>200ms','无告警'])}。\n"
            f"SLA：99.{random.randint(9,99)}%可用性。\n"
        )
    text_6k_2 = "# 微服务架构评审 2024-Q3\n\n" + "\n".join(sections * 4)
    cases.append({"name": "6K-2 架构评审文档", "text": text_6k_2, "key": ["QPS","P99","SLA","ms","API Gateway"], "rate": 0.5})

    # 6K-3: Agent多轮对话
    turns = []
    for i in range(30):
        turns.append(
            f"[Turn {i+1}] 用户: 请{random.choice(['查询','分析','统计','导出'])}"
            f"{random.choice(['本季度','上月','近7天'])}的{random.choice(['客户数据','销售报表','流失分析'])}。\n"
            f"[Turn {i+1}] Agent: 执行{random.choice(tools)}，"
            f"返回{random.randint(10,1000)}条，金额¥{random.randint(100,9999)}万，"
            f"耗时{random.randint(100,5000)}ms，tokens={random.randint(100,2000)}。\n"
        )
    text_6k_3 = "".join(turns)
    cases.append({"name": "6K-3 Agent对话历史", "text": text_6k_3, "key": ["query_data","¥","ms","tokens"], "rate": 0.5})

    # 20K-1: 年度报告
    text_20k_1 = (text_6k_1 + "\n\n---\n\n") * 4
    cases.append({"name": "20K-1 年度运营报告", "text": text_20k_1, "key": ["华东","NPS","金融","¥","%"], "rate": 0.5})

    # 20K-2: 系统日志
    logs = []
    for i in range(500):
        ts = f"2024-10-{random.randint(1,30):02d} {random.randint(0,23):02d}:{random.randint(0,59):02d}"
        level = random.choices(["INFO","WARN","ERROR"], weights=[60,25,15])[0]
        svc = random.choice(services)
        if level == "ERROR":
            msg = f"HTTP 5{random.randint(0,3)}{random.randint(0,9)} from {svc}: timeout={random.randint(10,60)}s"
        elif level == "WARN":
            msg = f"Slow query: {random.randint(1000,30000)}ms on {random.choice(['opportunity','contact','account'])}"
        else:
            msg = f"OK: {svc} latency={random.randint(10,500)}ms, cache_hit={random.randint(60,99)}%"
        logs.append(f"{ts} [{level}] [{svc}] {msg}")
    text_20k_2 = "\n".join(logs)
    cases.append({"name": "20K-2 系统日志", "text": text_20k_2, "key": ["ERROR","HTTP","timeout","Slow query","ms"], "rate": 0.5})

    # 20K-3: RAG检索结果
    docs = []
    topics = ["审批流程","权限体系","数据模型","API文档","部署手册","性能优化","安全策略","监控配置"]
    for i in range(80):
        t = topics[i % len(topics)]
        docs.append(
            f"[Doc {i+1}] {t} (score: 0.{random.randint(30,99)})\n"
            f"系统支持{random.randint(3,20)}种配置，涉及{random.randint(5,50)}个参数。"
            f"更新于2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}。"
            f"关键参数：max_retries={random.randint(1,5)}，timeout={random.randint(1000,30000)}ms，"
            f"batch_size={random.randint(100,5000)}。适用V{random.randint(2,5)}.{random.randint(0,9)}+。\n\n"
        )
    text_20k_3 = "".join(docs)
    cases.append({"name": "20K-3 RAG检索结果", "text": text_20k_3, "key": ["max_retries","timeout","batch_size","审批流程"], "rate": 0.5})

    return cases


def call_api(text, rate):
    payload = json.dumps({
        "prompt": text, "rate": rate,
        "force_tokens": FORCE_TOKENS,
        "chunk_end_tokens": CHUNK_END,
        "drop_consecutive": True,
    })
    t0 = time.perf_counter()
    r = subprocess.run(
        ["curl", "-s", "-X", "POST", f"{BASE_URL}/compress/fp16",
         "-H", "Content-Type: application/json", "-d", payload],
        capture_output=True, text=True, timeout=120,
    )
    e2e_ms = (time.perf_counter() - t0) * 1000
    try:
        return json.loads(r.stdout), e2e_ms
    except Exception:
        return None, e2e_ms


def calc_recall(text, compressed, keys):
    found = sum(1 for k in keys if k in compressed)
    total = sum(1 for k in keys if k in text)
    return found / total if total > 0 else 1.0


def main():
    cases = gen_cases()

    print("=" * 90)
    print("  LLMLingua-2 长文本性能验证 (FP16 GPU)")
    print("=" * 90)
    print("\n  用例:")
    for c in cases:
        print(f"    {c['name']}: {len(c['text']):,} 字")

    # Warmup
    print("\n  Warmup...")
    call_api("warmup", 0.5)
    print("  done\n")

    # Header
    header = f"  {'Case':<22}{'Chars':<10}{'OrigTok':<10}{'CompTok':<10}{'Save%':<8}{'SrvMs':<10}{'E2EMs':<10}{'Recall'}"
    print(header)
    print("  " + "-" * 86)

    for case in cases:
        result, e2e = call_api(case["text"], case["rate"])
        if not result or "error" in result:
            print(f"  {case['name']:<22} ERROR (e2e={e2e:.0f}ms)")
            continue

        compressed = result.get("compressed_prompt", "")
        orig_tok = result.get("origin_tokens", 0)
        comp_tok = result.get("compressed_tokens", 0)
        srv_ms = result.get("latency_ms", 0)
        savings = (1 - comp_tok / orig_tok) * 100 if orig_tok > 0 else 0
        recall = calc_recall(case["text"], compressed, case["key"])

        print(f"  {case['name']:<22}{len(case['text']):<10,}{orig_tok:<10}{comp_tok:<10}{savings:<8.0f}{srv_ms:<10.1f}{e2e:<10.0f}{recall*100:.0f}%")

    print(f"""
{'=' * 90}
  性能分析
{'=' * 90}
  - 短文本 (~200字): ~20ms (之前 200 条验证基线)
  - 6000字: 预期 ~100-200ms (分 ~12 chunks, 每 chunk ~15ms)
  - 20000字: 预期 ~300-600ms (分 ~40 chunks)
  - 延迟与文本长度近似线性关系 (chunk 数 × 单 chunk 推理时间)
""")


if __name__ == "__main__":
    main()
