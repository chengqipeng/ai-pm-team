"""更新 analyze.py 为纯标准库版本并端到端测试"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NEW_ANALYZE_PY = r'''#!/usr/bin/env python3
"""CSV 数据趋势分析脚本（纯标准库，兼容 Python 3.6+）

用法:
    python3 analyze.py --input data.csv --type trend --output result.json
"""
import argparse
import csv
import json
import math
import sys


def mean(values):
    return sum(values) / len(values) if values else 0

def std(values):
    if len(values) < 2:
        return 0
    m = mean(values)
    return math.sqrt(sum((x - m) ** 2 for x in values) / (len(values) - 1))

def linear_slope(values):
    n = len(values)
    if n < 2:
        return 0
    x_mean = (n - 1) / 2.0
    y_mean = mean(values)
    num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    den = sum((i - x_mean) ** 2 for i in range(n))
    return num / den if den != 0 else 0

def to_float(val):
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

def read_csv_file(filepath):
    rows = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        for row in reader:
            rows.append(row)
    return headers, rows

def analyze_trend(headers, rows):
    result = {"type": "trend", "trends": []}
    for col in headers:
        values = [to_float(r[col]) for r in rows]
        values = [v for v in values if v is not None]
        if len(values) < 3:
            continue
        slope = linear_slope(values)
        m = mean(values)
        s = std(values)
        pct = ((values[-1] - values[0]) / values[0] * 100) if values[0] != 0 else 0
        anomalies = [i for i, v in enumerate(values) if s > 0 and abs(v - m) > 2 * s]
        direction = "上升" if slope > 0.01 else ("下降" if slope < -0.01 else "平稳")
        result["trends"].append({
            "column": col, "direction": direction,
            "slope": round(slope, 4), "pct_change": round(pct, 2),
            "mean": round(m, 2), "std": round(s, 2),
            "min": round(min(values), 2), "max": round(max(values), 2),
            "anomaly_count": len(anomalies),
        })
    return result

def analyze_summary(headers, rows):
    result = {"type": "summary", "rows": len(rows), "columns": len(headers),
              "column_names": headers, "statistics": {}}
    for col in headers:
        values = [to_float(r[col]) for r in rows]
        numeric = [v for v in values if v is not None]
        if numeric:
            result["statistics"][col] = {
                "count": len(numeric), "mean": round(mean(numeric), 2),
                "std": round(std(numeric), 2),
                "min": round(min(numeric), 2), "max": round(max(numeric), 2),
            }
        else:
            unique = list(set(r[col] for r in rows))
            result["statistics"][col] = {"count": len(rows), "unique": len(unique), "type": "text"}
    return result

def analyze_correlation(headers, rows):
    numeric_cols = []
    col_values = {}
    for col in headers:
        values = [to_float(r[col]) for r in rows]
        if all(v is not None for v in values):
            numeric_cols.append(col)
            col_values[col] = values
    if len(numeric_cols) < 2:
        return {"type": "correlation", "error": "数值列不足"}
    pairs = []
    for i, a in enumerate(numeric_cols):
        for b in numeric_cols[i+1:]:
            va, vb = col_values[a], col_values[b]
            ma, mb = mean(va), mean(vb)
            sa, sb = std(va), std(vb)
            if sa == 0 or sb == 0:
                continue
            n = len(va)
            r_val = sum((va[k]-ma)*(vb[k]-mb) for k in range(n)) / ((n-1)*sa*sb)
            if abs(r_val) > 0.7:
                pairs.append({"col_a": a, "col_b": b, "correlation": round(r_val, 4)})
    return {"type": "correlation", "strong_pairs": pairs}

def main():
    parser = argparse.ArgumentParser(description="CSV 数据趋势分析")
    parser.add_argument("--input", required=True)
    parser.add_argument("--type", default="trend", choices=["trend", "summary", "correlation"])
    parser.add_argument("--output", default="/tmp/analysis_result.json")
    args = parser.parse_args()
    headers, rows = read_csv_file(args.input)
    print("已加载: {} 行 x {} 列".format(len(rows), len(headers)))
    analyzers = {"trend": analyze_trend, "summary": analyze_summary, "correlation": analyze_correlation}
    result = analyzers[args.type](headers, rows)
    result["meta"] = {"input_file": args.input, "rows": len(rows), "columns": len(headers), "analysis_type": args.type}
    with open(args.output, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("分析完成: {}".format(args.type))
    print("结果已写入: {}".format(args.output))

if __name__ == "__main__":
    main()
'''

TEST_CSV = """date,revenue,orders,avg_price
2024-01,120000,450,266.67
2024-02,135000,520,259.62
2024-03,128000,480,266.67
2024-04,142000,550,258.18
2024-05,155000,600,258.33
2024-06,148000,570,259.65
2024-07,162000,630,257.14
2024-08,170000,660,257.58
2024-09,158000,610,259.02
2024-10,175000,680,257.35
2024-11,182000,710,256.34
2024-12,195000,750,260.00
"""

async def run():
    from src.store.pg_pool import get_conn
    from src.tools.sandbox import create_ssh_backend_from_env, ScriptSyncer
    from src.skills.base import SkillDefinition, SkillExecutor, SkillRegistry

    print("=" * 70)
    print("  Skill 脚本执行完整端到端测试")
    print("=" * 70)

    # 1. 更新 DB
    print("\n── 1. 更新 DB 中 analyze.py 为纯标准库版本 ──")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE ai_skill_resource SET content = %s, content_size = %s, updated_at = 1748189000000 "
            "WHERE skill_api_key = %s AND path = %s AND tenant_id = 0 AND delete_flg = 0",
            (NEW_ANALYZE_PY, len(NEW_ANALYZE_PY), 'csv-trend-analysis', 'scripts/analyze.py')
        )
        cur.execute(
            "UPDATE ai_skill_resource SET content = %s, content_size = 30, updated_at = 1748189000000 "
            "WHERE skill_api_key = %s AND path = %s AND tenant_id = 0 AND delete_flg = 0",
            ("# 纯标准库，无需额外依赖\n", 'csv-trend-analysis', 'scripts/requirements.txt')
        )
        conn.commit()
    print("  ✅ DB 已更新")

    # 2. 加载 Skill
    print("\n── 2. 从 DB 加载 Skill ──")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT d.skill_api_key, d.version, d.prompt, d.context,
                   d.allowed_tools, d.arguments, s.ext_info
            FROM ai_skill_definition d
            JOIN ai_skill s ON s.api_key = d.skill_api_key AND s.tenant_id = d.tenant_id
            WHERE d.skill_api_key = 'csv-trend-analysis' AND d.tenant_id = 0 AND d.delete_flg = 0
        """)
        row = cur.fetchone()

    skill = SkillDefinition(
        name=row[0], description="CSV 数据趋势分析",
        prompt=row[2], context=row[3],
        allowed_tools=json.loads(row[4]), arguments=json.loads(row[5]),
        version=row[1], tenant_id=0,
    )
    skill.ext_info = row[6]
    print(f"  ✅ {skill.name} v{skill.version}")

    # 3. SkillExecutor 执行（同步 + 模板替换）
    print("\n── 3. SkillExecutor.execute() ──")
    backend = create_ssh_backend_from_env()

    class Ctx:
        sandbox_backend = backend

    registry = SkillRegistry()
    registry.register(skill)
    executor = SkillExecutor(registry=registry, context=Ctx())

    # 先清理确保全量同步
    await backend.connect()
    syncer = ScriptSyncer(backend=backend, tenant_id=0)
    await syncer.cleanup("csv-trend-analysis")

    prompt = await executor.execute(
        "csv-trend-analysis",
        {"input_file": "/tmp/test_sales.csv", "analysis_type": "trend"},
    )
    print(f"  ✅ prompt 格式化完成 ({len(prompt)} 字符)")

    # 4. 模拟 LLM 执行步骤
    print("\n── 4. 模拟 LLM 按 prompt 步骤执行 ──")
    skill_dir = "/sandbox/.skills/csv-trend-analysis"

    # 步骤 1: 创建测试数据
    print("  [LLM] 创建测试 CSV...")
    await backend.write_file("/tmp/test_sales.csv", TEST_CSV)

    # 步骤 2: 执行脚本 (trend)
    cmd = f"python3 {skill_dir}/scripts/analyze.py --input /tmp/test_sales.csv --type trend --output /tmp/result.json"
    print(f"  [LLM] terminal: {cmd}")
    r = await backend.execute(cmd, timeout=15)
    print(f"  [沙盒] {r.stdout.strip()}")

    if r.is_error:
        print(f"  ❌ 执行失败: {r.output}")
        await backend.disconnect()
        return

    # 步骤 3: 读取结果
    print("  [LLM] read_file: /tmp/result.json")
    r2 = await backend.read_file("/tmp/result.json")
    data = json.loads(r2.stdout)

    print(f"\n── 5. 分析结果 ──")
    print(f"  类型: {data['type']}")
    print(f"  数据: {data['meta']['rows']} 行 × {data['meta']['columns']} 列")
    print(f"  趋势:")
    for t in data.get("trends", []):
        emoji = "📈" if t["direction"] == "上升" else ("📉" if t["direction"] == "下降" else "➡️")
        print(f"    {emoji} {t['column']}: {t['direction']} (变化 {t['pct_change']}%, slope={t['slope']})")

    # 6. 测试 summary 模式
    print(f"\n── 6. 测试 summary 模式 ──")
    r3 = await backend.execute(
        f"python3 {skill_dir}/scripts/analyze.py --input /tmp/test_sales.csv --type summary --output /tmp/summary.json",
        timeout=15,
    )
    r4 = await backend.read_file("/tmp/summary.json")
    summary = json.loads(r4.stdout)
    print(f"  行数: {summary['rows']}, 列: {summary['column_names']}")
    for col, stats in summary.get("statistics", {}).items():
        if "mean" in stats:
            print(f"    {col}: mean={stats['mean']}, min={stats['min']}, max={stats['max']}")

    # 清理
    print(f"\n── 清理 ──")
    await backend.execute("rm -f /tmp/test_sales.csv /tmp/result.json /tmp/summary.json")
    await syncer.cleanup("csv-trend-analysis")
    await backend.disconnect()
    print("  ✅ 完成")

    print("\n" + "=" * 70)
    print("  🎉 全链路测试通过！")
    print("  DB → ScriptSyncer → 沙盒 → python3 analyze.py → JSON 结果")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run())
