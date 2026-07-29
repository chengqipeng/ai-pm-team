"""
LLMLingua-2 GPU API 全场景验证 (200 条用例)

使用系统中 eval_llmlingua2_200cases.py 的 8 类场景，通过 REST API 验证：
  1. FP32 vs FP16 一致性
  2. 各场景准确率（关键信息保留率）
  3. 延迟性能统计

场景分布:
  - CRM 业务报告 (40条)
  - 技术故障分析 (30条)
  - 会议纪要 (30条)
  - 中英混合 Agent 对话 (30条)
  - 长文档段落 (20条)
  - 客户沟通记录 (20条)
  - 数据分析结果 (15条)
  - 系统配置/参数 (15条)
"""

import json
import time
import subprocess
import random
import sys
import ast
sys.path.insert(0, ".")

# 复用系统中的用例生成器（仅导入函数，不触发 llmlingua 依赖）
import importlib.util
spec = importlib.util.spec_from_file_location("eval_cases", "./eval_llmlingua2_200cases.py")
# 由于 eval 文件顶部 import llmlingua，我们直接复制 generate_test_cases 逻辑
# 使用 exec 跳过顶层 import
import random
random.seed(42)

def _load_generate_test_cases():
    """从源文件提取 generate_test_cases 函数（避免触发 llmlingua import）"""
    import ast
    with open("./eval_llmlingua2_200cases.py", "r") as f:
        source = f.read()
    tree = ast.parse(source)
    # 找到函数定义
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "generate_test_cases":
            func_source = ast.get_source_segment(source, node)
            # 编译执行
            local_ns = {"random": random}
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<eval>", "exec"), local_ns)
            return local_ns["generate_test_cases"]
    raise RuntimeError("generate_test_cases not found")

generate_test_cases = _load_generate_test_cases()

# ═══════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════

BASE_URL = "https://llmlingua.ingageapp.com"
FORCE_TOKENS = ["\u3002", "\uff1f", "\uff01", "\uff1b", "\uff0c", "\uff1a", "\n", "=", "_", "-"]
CHUNK_END_TOKENS = ["\u3002", "\uff1f", "\uff01", "\uff1b", "\n"]


# ═══════════════════════════════════════════════════════════
# HTTP 调用
# ═══════════════════════════════════════════════════════════


def call_api(backend: str, text: str, rate: float) -> dict:
    """调用压缩 API"""
    url = f"{BASE_URL}/compress/{backend}"
    payload = json.dumps({
        "prompt": text,
        "rate": rate,
        "force_tokens": FORCE_TOKENS,
        "chunk_end_tokens": CHUNK_END_TOKENS,
        "drop_consecutive": True,
    })
    result = subprocess.run(
        ["curl", "-s", "-X", "POST", url, "-H", "Content-Type: application/json", "-d", payload],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return {"error": result.stderr or "empty response", "compressed_prompt": "", "latency_ms": 0}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "json decode error", "compressed_prompt": "", "latency_ms": 0}


def calc_recall(text: str, compressed: str, key_info: list) -> tuple:
    """计算关键信息保留率"""
    found_orig = {k for k in key_info if k in text}
    found_comp = {k for k in key_info if k in compressed}
    recall = len(found_comp) / len(found_orig) if found_orig else 1.0
    lost = sorted(found_orig - found_comp)
    return recall, lost


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════


def main():
    print("=" * 90)
    print("  LLMLingua-2 GPU API 全场景验证 (200 条用例, 8 类场景)")
    print("=" * 90)

    # 健康检查
    health_raw = subprocess.run(["curl", "-s", f"{BASE_URL}/health"], capture_output=True, text=True, timeout=5)
    health = json.loads(health_raw.stdout)
    print(f"\n  Server: {BASE_URL}")
    print(f"  Status: {health['status']} | Backends: {health['backends']} | Device: {health['device']}")

    # 生成用例
    print("\n  生成 200 条测试用例...")
    cases = generate_test_cases()
    print(f"  done. 场景分布:")
    categories = {}
    for c in cases:
        categories[c["category"]] = categories.get(c["category"], 0) + 1
    for cat, count in categories.items():
        print(f"    {cat}: {count} 条")

    # Warmup
    print("\n  Warmup...")
    call_api("fp32", "warmup test", 0.5)
    call_api("fp16", "warmup test", 0.5)
    print("  done\n")

    # ═══════════════════════════════════════════════════════════
    # 执行验证
    # ═══════════════════════════════════════════════════════════

    results = []
    errors = 0
    n = len(cases)

    print(f"  执行中... (共 {n} 条)")
    t_start = time.perf_counter()

    for i, case in enumerate(cases):
        if (i + 1) % 20 == 0:
            elapsed = time.perf_counter() - t_start
            eta = elapsed / (i + 1) * (n - i - 1)
            print(f"    [{i+1}/{n}] elapsed={elapsed:.0f}s, ETA={eta:.0f}s")

        fp32_r = call_api("fp32", case["text"], case["rate"])
        fp16_r = call_api("fp16", case["text"], case["rate"])

        if "error" in fp32_r or "error" in fp16_r:
            errors += 1
            results.append({"case": case, "error": True})
            continue

        fp32_text = fp32_r.get("compressed_prompt", "")
        fp16_text = fp16_r.get("compressed_prompt", "")
        match = fp32_text == fp16_text

        recall_32, lost_32 = calc_recall(case["text"], fp32_text, case["key_info"])
        recall_16, lost_16 = calc_recall(case["text"], fp16_text, case["key_info"])

        results.append({
            "case": case,
            "error": False,
            "match": match,
            "fp32_srv_ms": fp32_r.get("latency_ms", 0),
            "fp16_srv_ms": fp16_r.get("latency_ms", 0),
            "fp32_tokens": fp32_r.get("compressed_tokens", 0),
            "fp16_tokens": fp16_r.get("compressed_tokens", 0),
            "fp32_orig_tokens": fp32_r.get("origin_tokens", 0),
            "recall_32": recall_32,
            "recall_16": recall_16,
            "lost_32": lost_32,
        })

    total_time = time.perf_counter() - t_start
    valid = [r for r in results if not r["error"]]

    # ═══════════════════════════════════════════════════════════
    # 输出报告
    # ═══════════════════════════════════════════════════════════

    print(f"\n\n{'=' * 90}")
    print(f"  验证完成: {len(valid)}/{n} 成功, {errors} 错误, 总耗时 {total_time:.0f}s")
    print(f"{'=' * 90}")

    # FP32 vs FP16 一致性
    n_match = sum(1 for r in valid if r["match"])
    print(f"\n\n{'=' * 90}")
    print(f"  FP32 vs FP16 一致性")
    print(f"{'=' * 90}")
    print(f"\n  一致: {n_match}/{len(valid)} ({n_match/len(valid)*100:.1f}%)")
    if n_match < len(valid):
        diffs = [r for r in valid if not r["match"]]
        print(f"  差异用例 ({len(diffs)} 条):")
        for r in diffs[:5]:
            print(f"    {r['case']['id']} ({r['case']['category']}): FP32={r['fp32_tokens']}tok vs FP16={r['fp16_tokens']}tok")

    # 按场景统计准确率
    print(f"\n\n{'=' * 90}")
    print(f"  按场景准确率 (关键信息保留率)")
    print(f"{'=' * 90}")
    print(f"\n  {'场景':<14} {'用例数':<8} {'FP32 recall':<14} {'FP16 recall':<14} {'一致率'}")
    print(f"  {'-' * 62}")

    for cat in categories:
        cat_results = [r for r in valid if r["case"]["category"] == cat]
        if not cat_results:
            continue
        avg_32 = sum(r["recall_32"] for r in cat_results) / len(cat_results)
        avg_16 = sum(r["recall_16"] for r in cat_results) / len(cat_results)
        cat_match = sum(1 for r in cat_results if r["match"]) / len(cat_results) * 100
        print(f"  {cat:<14} {len(cat_results):<8} {avg_32*100:<14.1f} {avg_16*100:<14.1f} {cat_match:.0f}%")

    overall_recall_32 = sum(r["recall_32"] for r in valid) / len(valid)
    overall_recall_16 = sum(r["recall_16"] for r in valid) / len(valid)
    print(f"  {'-' * 62}")
    print(f"  {'总计':<14} {len(valid):<8} {overall_recall_32*100:<14.1f} {overall_recall_16*100:<14.1f} {n_match/len(valid)*100:.0f}%")

    # 性能统计
    print(f"\n\n{'=' * 90}")
    print(f"  性能统计 (server-side latency)")
    print(f"{'=' * 90}")

    fp32_times = [r["fp32_srv_ms"] for r in valid if r["fp32_srv_ms"] > 0]
    fp16_times = [r["fp16_srv_ms"] for r in valid if r["fp16_srv_ms"] > 0]

    if fp32_times and fp16_times:
        fp32_times.sort()
        fp16_times.sort()
        n_t = len(fp32_times)

        print(f"\n  {'指标':<16} {'FP32':<12} {'FP16':<12} {'加速比'}")
        print(f"  {'-' * 48}")
        print(f"  {'平均':<16} {sum(fp32_times)/n_t:<12.1f} {sum(fp16_times)/n_t:<12.1f} {sum(fp32_times)/sum(fp16_times):.1f}x")
        print(f"  {'P50':<16} {fp32_times[n_t//2]:<12.1f} {fp16_times[n_t//2]:<12.1f}")
        print(f"  {'P95':<16} {fp32_times[int(n_t*0.95)]:<12.1f} {fp16_times[int(n_t*0.95)]:<12.1f}")
        print(f"  {'P99':<16} {fp32_times[int(n_t*0.99)]:<12.1f} {fp16_times[int(n_t*0.99)]:<12.1f}")
        print(f"  {'Min':<16} {fp32_times[0]:<12.1f} {fp16_times[0]:<12.1f}")
        print(f"  {'Max':<16} {fp32_times[-1]:<12.1f} {fp16_times[-1]:<12.1f}")

    # 按场景延迟
    print(f"\n  按场景延迟 (FP16 avg):")
    for cat in categories:
        cat_times = [r["fp16_srv_ms"] for r in valid if r["case"]["category"] == cat and r["fp16_srv_ms"] > 0]
        if cat_times:
            print(f"    {cat:<14} {sum(cat_times)/len(cat_times):.1f}ms")

    # 结论
    print(f"\n\n{'=' * 90}")
    print(f"  结论")
    print(f"{'=' * 90}")
    print(f"""
  测试规模: {len(valid)} 条用例, 8 类场景
  FP32 vs FP16 一致性: {n_match}/{len(valid)} ({n_match/len(valid)*100:.1f}%)
  FP32 关键信息保留率: {overall_recall_32*100:.1f}%
  FP16 关键信息保留率: {overall_recall_16*100:.1f}%
  FP32 平均延迟: {sum(fp32_times)/len(fp32_times):.1f}ms
  FP16 平均延迟: {sum(fp16_times)/len(fp16_times):.1f}ms
  FP16 加速比: {sum(fp32_times)/sum(fp16_times):.1f}x

  验证结论:
    {'✅' if n_match/len(valid) > 0.95 else '⚠️'} FP16 精度安全 (一致率 {n_match/len(valid)*100:.0f}%)
    {'✅' if sum(fp16_times)/len(fp16_times) < 50 else '⚠️'} FP16 延迟满足在线要求 ({sum(fp16_times)/len(fp16_times):.0f}ms < 100ms)
    {'✅' if overall_recall_32 > 0.5 else '⚠️'} 关键信息保留率可接受 ({overall_recall_32*100:.0f}%)
""")


if __name__ == "__main__":
    main()
