"""输出完整评估报告"""
import json

with open("eval_results_llmlingua2.json", "r") as f:
    data = json.load(f)

results = data["results"]
summary = data["summary"]

print("=" * 80)
print("LLMLingua-2 中文上下文压缩 — 200 条用例完整评估报告")
print("=" * 80)
print(f"\n模型: llmlingua-2-bert-base-multilingual-cased-meetingbank")
print(f"设备: Mac Apple Silicon (MPS)")
print(f"总耗时: {summary['total_time_s']}s")

print(f"\n{'─' * 80}")
print("总体统计")
print(f"{'─' * 80}")
print(f"  通过: {summary['passed']}/{summary['total']} ({summary['passed']/summary['total']*100:.1f}%)")
print(f"  失败: {summary['failed']}/{summary['total']}")
print(f"  平均压缩节省: {summary['avg_savings_pct']}%")
print(f"  平均关键信息保留率: {summary['avg_key_info_rate']*100:.1f}%")
print(f"  平均延迟: {summary['avg_latency_ms']}ms")
print(f"  P95 延迟: {summary['p95_latency_ms']}ms")

# 按分类汇总
print(f"\n{'─' * 80}")
print(f"{'类别':<14} {'数量':>4} {'通过':>4} {'通过率':>7} {'压缩%':>7} {'保留率':>7} {'延迟ms':>7}")
print(f"{'─' * 80}")

categories = {}
for r in results:
    cat = r["category"]
    if cat not in categories:
        categories[cat] = []
    categories[cat].append(r)

for cat in sorted(categories.keys()):
    items = categories[cat]
    n = len(items)
    passed = sum(1 for r in items if r["passed"])
    avg_sav = sum(r["savings_pct"] for r in items) / n
    avg_key = sum(r["key_info_rate"] for r in items) / n
    avg_lat = sum(r["latency_ms"] for r in items) / n
    mark = "✓" if passed == n else "△" if passed > n*0.5 else "✗"
    print(f"  {mark} {cat:<12} {n:>3}  {passed:>3}   {passed/n*100:>5.1f}%  {avg_sav:>5.1f}%  {avg_key*100:>5.1f}%  {avg_lat:>6.1f}")

# 全部 200 条逐条结果
print(f"\n{'─' * 80}")
print("全部 200 条用例逐条结果")
print(f"{'─' * 80}")
print(f"{'ID':<16} {'类别':<10} {'原文':>5} {'压缩':>5} {'比率':<6} {'节省%':>5} {'保留':>5} {'延迟ms':>7} {'状态'}")
print(f"{'─' * 80}")

for r in results:
    status = "✓" if r["passed"] else f"✗ {r['failure_reason']}"
    print(f"  {r['case_id']:<14} {r['category']:<8} "
          f"{r['original_tokens']:>4}  {r['compressed_tokens']:>4}  {r['compression_ratio']:<5} "
          f"{r['savings_pct']:>5.1f} "
          f"{r['key_info_retained']}/{r['key_info_total']:>1}   "
          f"{r['latency_ms']:>6.1f}  {status}")

# 失败用例明细
print(f"\n{'─' * 80}")
print("失败用例明细")
print(f"{'─' * 80}")
failed = [r for r in results if not r["passed"]]
if not failed:
    print("  (无)")
else:
    for r in failed:
        print(f"  {r['case_id']}: {r['failure_reason']} "
              f"(tokens {r['original_tokens']}→{r['compressed_tokens']}, "
              f"保留 {r['key_info_retained']}/{r['key_info_total']})")

print(f"\n{'=' * 80}")
print("评估完成")
print(f"{'=' * 80}")
