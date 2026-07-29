"""
LLMLingua-2 并发压测

目标：找到 GPU 服务在长短文本混合负载下的并发拐点（平均延迟开始明显上升的并发数）。

方法：
  - 构造混合负载：70% 短文本(~200字) + 20% 中文本(~3000字) + 10% 长文本(~10000字)
  - 使用线程池模拟并发，逐步提升并发数：1, 2, 4, 8, 12, 16, 20, 24, 32
  - 每个并发级别发送 30 个请求，统计 avg/P50/P95/P99 延迟
  - 观察延迟拐点

用法:
  python run_concurrency_bench.py
"""

import json
import time
import random
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

random.seed(42)

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

BASE_URL = "https://llmlingua.ingageapp.com"
FORCE_TOKENS = ["\u3002", "\uff1f", "\uff01", "\uff1b", "\uff0c", "\uff1a", "\n", "=", "_", "-"]
CHUNK_END = ["\u3002", "\uff1f", "\uff01", "\uff1b", "\n"]

CONCURRENCY_LEVELS = [1, 2, 4, 8, 12, 16, 20, 24, 32]
REQUESTS_PER_LEVEL = 30

# ═══════════════════════════════════════════════════════════
# 负载生成
# ═══════════════════════════════════════════════════════════


def gen_short_text():
    """~200字短文本"""
    industries = ["金融", "制造", "医疗", "教育", "零售", "互联网"]
    return (
        f"{random.choice(['2023','2024'])}年第{random.choice(['一','二','三','四'])}季度"
        f"{random.choice(industries)}行业CRM报告。"
        f"新增客户{random.randint(100,5000)}家，合同金额¥{random.randint(100,9999)}万，"
        f"同比增长{random.randint(5,60)}%。流失率{round(random.uniform(1,8),1)}%。"
        f"NPS评分{random.randint(30,70)}分。建议关注{random.choice(['大客户','渠道','产品'])}策略。"
    )


def gen_medium_text():
    """~3000字中文本"""
    paras = []
    for i in range(15):
        paras.append(
            f"第{i+1}部分：{random.choice(['华东','华南','华北','西南'])}地区分析。"
            f"新增客户{random.randint(50,500)}家，金额¥{random.randint(100,5000)}万，增长{random.randint(-10,60)}%。"
            f"流失率{round(random.uniform(1,8),1)}%，NPS={random.randint(30,70)}。"
            f"重点客户{random.choice(['华为','腾讯','阿里','字节'])}贡献{random.randint(10,50)}%收入。"
            f"竞品{random.choice(['Salesforce','SAP','Oracle'])}有新动作。"
        )
    return "\n".join(paras)


def gen_long_text():
    """~10000字长文本"""
    sections = []
    services = ["APIGateway", "AuthService", "CRMCore", "Billing", "Analytics"]
    for _ in range(3):
        for svc in services:
            sections.append(
                f"## {svc}\n"
                f"规格：{random.choice(['8C16G','16C32G'])} x {random.randint(3,10)}节点，"
                f"QPS={random.randint(100,5000)}，P99={random.randint(10,500)}ms，"
                f"错误率={round(random.uniform(0.01,2),2)}%。\n"
                f"依赖：{random.choice(services)}。告警：{random.choice(['内存超85%','连接池耗尽','无告警'])}。"
                f"SLA=99.{random.randint(9,99)}%。\n"
            )
    logs = []
    for i in range(100):
        level = random.choices(["INFO", "WARN", "ERROR"], weights=[60, 25, 15])[0]
        logs.append(
            f"2024-10-{random.randint(1,30):02d} {random.randint(0,23):02d}:{random.randint(0,59):02d} "
            f"[{level}] [{random.choice(services)}] "
            f"latency={random.randint(10,5000)}ms status={random.choice(['ok','timeout','error'])}"
        )
    return "# 架构评审\n\n" + "\n".join(sections) + "\n\n# 日志\n" + "\n".join(logs)


def gen_mixed_workload(n: int) -> list:
    """生成混合负载: 70% 短 + 20% 中 + 10% 长"""
    workload = []
    for i in range(n):
        r = random.random()
        if r < 0.7:
            workload.append(("short", gen_short_text()))
        elif r < 0.9:
            workload.append(("medium", gen_medium_text()))
        else:
            workload.append(("long", gen_long_text()))
    return workload


# ═══════════════════════════════════════════════════════════
# 请求发送
# ═══════════════════════════════════════════════════════════


def send_request(text: str, rate: float = 0.5) -> dict:
    """发送单个压缩请求，返回 {srv_ms, e2e_ms, tokens, error}"""
    payload = json.dumps({
        "prompt": text,
        "rate": rate,
        "force_tokens": FORCE_TOKENS,
        "chunk_end_tokens": CHUNK_END,
        "drop_consecutive": True,
    })
    t0 = time.perf_counter()
    try:
        r = subprocess.run(
            ["curl", "-s", "-X", "POST", f"{BASE_URL}/compress/fp16",
             "-H", "Content-Type: application/json", "-d", payload],
            capture_output=True, text=True, timeout=60,
        )
        e2e_ms = (time.perf_counter() - t0) * 1000
        result = json.loads(r.stdout)
        return {
            "srv_ms": result.get("latency_ms", 0),
            "e2e_ms": e2e_ms,
            "tokens": result.get("origin_tokens", 0),
            "error": False,
        }
    except Exception as e:
        e2e_ms = (time.perf_counter() - t0) * 1000
        return {"srv_ms": 0, "e2e_ms": e2e_ms, "tokens": 0, "error": True}


# ═══════════════════════════════════════════════════════════
# 压测主流程
# ═══════════════════════════════════════════════════════════


def run_level(concurrency: int, workload: list) -> dict:
    """在指定并发度下执行负载，返回统计结果"""
    results = []

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = []
        for _, text in workload:
            futures.append(executor.submit(send_request, text))

        for future in as_completed(futures):
            results.append(future.result())

    # 统计
    valid = [r for r in results if not r["error"]]
    errors = len(results) - len(valid)

    if not valid:
        return {"concurrency": concurrency, "error": True}

    srv_times = sorted([r["srv_ms"] for r in valid])
    e2e_times = sorted([r["e2e_ms"] for r in valid])
    n = len(srv_times)

    return {
        "concurrency": concurrency,
        "n_requests": len(results),
        "n_success": n,
        "n_errors": errors,
        "srv_avg": sum(srv_times) / n,
        "srv_p50": srv_times[n // 2],
        "srv_p95": srv_times[int(n * 0.95)],
        "srv_p99": srv_times[min(int(n * 0.99), n - 1)],
        "srv_max": srv_times[-1],
        "e2e_avg": sum(e2e_times) / n,
        "e2e_p95": e2e_times[int(n * 0.95)],
        "throughput": n / (max(e2e_times) / 1000) if e2e_times else 0,
    }


def main():
    print("=" * 90)
    print("  LLMLingua-2 并发压测 (FP16 GPU, 长短文本混合)")
    print("=" * 90)

    # 生成负载
    workload_pool = gen_mixed_workload(200)
    short_count = sum(1 for t, _ in workload_pool if t == "short")
    medium_count = sum(1 for t, _ in workload_pool if t == "medium")
    long_count = sum(1 for t, _ in workload_pool if t == "long")

    print(f"\n  负载池: {len(workload_pool)} 请求")
    print(f"    短文本 (~200字): {short_count} 条 ({short_count/len(workload_pool)*100:.0f}%)")
    print(f"    中文本 (~3000字): {medium_count} 条 ({medium_count/len(workload_pool)*100:.0f}%)")
    print(f"    长文本 (~10000字): {long_count} 条 ({long_count/len(workload_pool)*100:.0f}%)")
    print(f"\n  并发级别: {CONCURRENCY_LEVELS}")
    print(f"  每级请求数: {REQUESTS_PER_LEVEL}")

    # Warmup
    print("\n  Warmup (3 requests)...")
    for i in range(3):
        send_request(workload_pool[i][1])
    print("  done\n")

    # 执行压测
    print(f"  {'Conc':<6}{'Reqs':<6}{'OK':<5}{'Err':<5}{'SrvAvg':<9}{'SrvP50':<9}{'SrvP95':<9}{'SrvP99':<9}{'SrvMax':<9}{'E2EAvg':<9}{'Thpt'}")
    print(f"  {'-' * 84}")

    all_stats = []
    baseline_avg = None

    for level in CONCURRENCY_LEVELS:
        # 从负载池随机取 REQUESTS_PER_LEVEL 个请求
        batch = random.sample(workload_pool, min(REQUESTS_PER_LEVEL, len(workload_pool)))

        stats = run_level(level, batch)
        all_stats.append(stats)

        if stats.get("error"):
            print(f"  {level:<6} ALL ERRORS")
            continue

        if baseline_avg is None:
            baseline_avg = stats["srv_avg"]

        degradation = stats["srv_avg"] / baseline_avg if baseline_avg else 1

        print(
            f"  {level:<6}"
            f"{stats['n_requests']:<6}"
            f"{stats['n_success']:<5}"
            f"{stats['n_errors']:<5}"
            f"{stats['srv_avg']:<9.1f}"
            f"{stats['srv_p50']:<9.1f}"
            f"{stats['srv_p95']:<9.1f}"
            f"{stats['srv_p99']:<9.1f}"
            f"{stats['srv_max']:<9.1f}"
            f"{stats['e2e_avg']:<9.0f}"
            f"{stats['throughput']:<6.1f} req/s"
            f"{'  ⚠️' if degradation > 1.5 else '  ❌' if degradation > 2.0 else ''}"
        )

    # 分析拐点
    print(f"\n\n{'=' * 90}")
    print("  性能拐点分析")
    print(f"{'=' * 90}")

    if baseline_avg:
        print(f"\n  基线 (并发=1): 平均 {baseline_avg:.1f}ms")
        print(f"\n  {'并发':<8}{'平均延迟':<12}{'相对基线':<12}{'吞吐量':<12}{'状态'}")
        print(f"  {'-' * 52}")

        for stats in all_stats:
            if stats.get("error"):
                continue
            ratio = stats["srv_avg"] / baseline_avg
            if ratio <= 1.2:
                status = "✅ 正常"
            elif ratio <= 1.5:
                status = "⚠️ 轻微退化"
            elif ratio <= 2.0:
                status = "🔶 明显退化"
            else:
                status = "❌ 严重退化"
            print(f"  {stats['concurrency']:<8}{stats['srv_avg']:<12.1f}{ratio:<12.2f}x{stats['throughput']:<12.1f}{status}")

    print(f"""
  结论:
    - 基线延迟 (并发=1): {baseline_avg:.1f}ms
    - 拐点判断: 平均延迟增长 >50% 时视为拐点
    - GPU 利用率: 并发增加时延迟是否线性增长取决于 GPU 饱和度
    - 推荐最大并发: 延迟 <2x 基线的最高并发数
""")


if __name__ == "__main__":
    main()
