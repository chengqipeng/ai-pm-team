"""修复 customer_growth_analysis 技能的缺失资源文件

该技能在创建时 LLM 未提供 resources 字段，导致 prompt 引用了
${SKILL_DIR}/scripts/main.py 但数据库中没有对应的脚本文件。

本脚本直接向 ai_skill_resource 表写入:
  - scripts/main.py (客户增长分析 Python 脚本)
  - scripts/requirements.txt (依赖声明)

运行方式:
    python scripts/_fix_customer_growth_resources.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SKILL_API_KEY = "customer_growth_analysis"
VERSION = "1.1.0"

# ══════════════════════════════════════════════════════════════
# scripts/main.py
# ══════════════════════════════════════════════════════════════
MAIN_PY = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""客户增长分析脚本

功能：
  1. 读取 CRM 客户数据 JSON
  2. 按月/季/年维度统计新增客户数
  3. 计算环比增长率、同比增长率、CAGR
  4. 输出结构化分析结果 JSON

用法：
  python3 main.py --input /tmp/customer_data.json --output /tmp/growth_result.json
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime


def parse_date(date_str: str):
    """尝试多种格式解析日期字符串"""
    if not date_str:
        return None
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S+08:00",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    # 尝试毫秒时间戳
    try:
        ts = int(date_str)
        if ts > 1e12:
            ts = ts / 1000
        return datetime.fromtimestamp(ts)
    except (ValueError, TypeError):
        return None


def calc_growth_rate(current: int, previous: int):
    """计算增长率，previous 为 0 时返回 None"""
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 2)


def calc_cagr(start_value: int, end_value: int, years: float):
    """计算复合年增长率"""
    if start_value <= 0 or end_value <= 0 or years <= 0:
        return None
    return round(((end_value / start_value) ** (1 / years) - 1) * 100, 2)


def get_quarter(month: int) -> int:
    """获取季度编号 (1-4)"""
    return (month - 1) // 3 + 1


def analyze_growth(records: list) -> dict:
    """核心分析逻辑"""
    # 1. 提取日期
    dated_records = []
    date_fields = ["createTime", "createdAt", "created_at", "create_time", "createDate"]

    for rec in records:
        dt = None
        for field in date_fields:
            if field in rec and rec[field]:
                dt = parse_date(str(rec[field]))
                if dt:
                    break
        if dt:
            dated_records.append({"date": dt, "record": rec})

    if not dated_records:
        return {
            "error": "无法从数据中提取有效日期，请确认客户数据包含 createTime 或等效日期字段",
            "total_records": len(records),
            "valid_dates": 0,
        }

    # 按日期排序
    dated_records.sort(key=lambda x: x["date"])

    # 2. 月度统计
    monthly = defaultdict(int)
    for item in dated_records:
        key = item["date"].strftime("%Y-%m")
        monthly[key] += 1

    sorted_months = sorted(monthly.keys())

    # 3. 季度统计
    quarterly = defaultdict(int)
    for item in dated_records:
        dt = item["date"]
        key = f"{dt.year}-Q{get_quarter(dt.month)}"
        quarterly[key] += 1

    sorted_quarters = sorted(quarterly.keys())

    # 4. 年度统计
    yearly = defaultdict(int)
    for item in dated_records:
        yearly[item["date"].year] += 1

    sorted_years = sorted(yearly.keys())

    # 5. 计算月度环比和同比
    monthly_detail = []
    for i, month in enumerate(sorted_months):
        entry = {"month": month, "count": monthly[month]}
        # 环比
        if i > 0:
            prev = monthly[sorted_months[i - 1]]
            entry["mom_rate"] = calc_growth_rate(monthly[month], prev)
        else:
            entry["mom_rate"] = None
        # 同比（12个月前）
        year, mon = month.split("-")
        yoy_key = f"{int(year) - 1}-{mon}"
        if yoy_key in monthly:
            entry["yoy_rate"] = calc_growth_rate(monthly[month], monthly[yoy_key])
        else:
            entry["yoy_rate"] = None
        monthly_detail.append(entry)

    # 6. 计算季度环比
    quarterly_detail = []
    for i, quarter in enumerate(sorted_quarters):
        entry = {"quarter": quarter, "count": quarterly[quarter]}
        if i > 0:
            prev = quarterly[sorted_quarters[i - 1]]
            entry["qoq_rate"] = calc_growth_rate(quarterly[quarter], prev)
        else:
            entry["qoq_rate"] = None
        quarterly_detail.append(entry)

    # 7. 计算年度同比
    yearly_detail = []
    for i, year in enumerate(sorted_years):
        entry = {"year": year, "count": yearly[year]}
        if i > 0:
            prev = yearly[sorted_years[i - 1]]
            entry["yoy_rate"] = calc_growth_rate(yearly[year], prev)
        else:
            entry["yoy_rate"] = None
        yearly_detail.append(entry)

    # 8. 计算 CAGR
    cagr = None
    if len(sorted_years) >= 2:
        first_year = sorted_years[0]
        last_year = sorted_years[-1]
        years_span = last_year - first_year
        if years_span > 0:
            cagr = calc_cagr(yearly[first_year], yearly[last_year], years_span)

    # 9. 趋势判断
    trend_direction = "stable"
    if len(monthly_detail) >= 3:
        recent_3 = monthly_detail[-3:]
        recent_rates = [m["mom_rate"] for m in recent_3 if m["mom_rate"] is not None]
        if recent_rates:
            avg_recent = sum(recent_rates) / len(recent_rates)
            if avg_recent > 10:
                trend_direction = "accelerating"
            elif avg_recent < -10:
                trend_direction = "declining"
            else:
                trend_direction = "stable"

    # 10. 汇总
    total_new = len(dated_records)
    months_span = len(sorted_months) if sorted_months else 1
    avg_monthly = round(total_new / months_span, 1)
    date_range_start = dated_records[0]["date"].strftime("%Y-%m-%d")
    date_range_end = dated_records[-1]["date"].strftime("%Y-%m-%d")

    return {
        "summary": {
            "total_records": len(records),
            "valid_date_records": len(dated_records),
            "date_range": f"{date_range_start} ~ {date_range_end}",
            "total_new_customers": total_new,
            "avg_monthly_new": avg_monthly,
            "trend_direction": trend_direction,
            "cagr": cagr,
        },
        "yearly": yearly_detail,
        "quarterly": quarterly_detail,
        "monthly": monthly_detail[-12:] if len(monthly_detail) > 12 else monthly_detail,
        "monthly_full": monthly_detail,
    }


def main():
    parser = argparse.ArgumentParser(description="客户增长分析")
    parser.add_argument("--input", required=True, help="输入 JSON 文件路径")
    parser.add_argument("--output", required=True, help="输出 JSON 文件路径")
    args = parser.parse_args()

    # 读取输入
    try:
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"错误: 输入文件不存在: {args.input}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"错误: JSON 解析失败: {e}", file=sys.stderr)
        sys.exit(1)

    records = data.get("records", [])
    if not records:
        result = {"error": "输入数据为空，无客户记录", "total_records": 0}
    else:
        result = analyze_growth(records)

    # 写入输出
    try:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"分析完成，结果已写入: {args.output}")
        print(f"客户总数: {result.get('summary', {}).get('total_records', 0)}")
        print(f"有效日期记录: {result.get('summary', {}).get('valid_date_records', 0)}")
        print(f"趋势方向: {result.get('summary', {}).get('trend_direction', 'unknown')}")
    except IOError as e:
        print(f"错误: 写入输出文件失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
'''

# ══════════════════════════════════════════════════════════════
# scripts/requirements.txt
# ══════════════════════════════════════════════════════════════
REQUIREMENTS_TXT = """# customer_growth_analysis 依赖
# 本脚本仅使用 Python 标准库，无第三方依赖
# 如需扩展（如图表生成），可添加：
# matplotlib>=3.7
# pandas>=2.0
"""


def main():
    from src.store.pg_pool import get_conn
    from src.store.snowflake import next_id

    now = int(time.time() * 1000)

    with get_conn() as conn:
        cur = conn.cursor()

        # 检查是否已存在
        cur.execute("""
            SELECT COUNT(*) FROM ai_skill_resource
            WHERE skill_api_key = %s AND version = %s AND tenant_id = 0 AND delete_flg = 0
        """, (SKILL_API_KEY, VERSION))
        existing = cur.fetchone()[0]
        if existing > 0:
            print(f"⚠️ 已存在 {existing} 条资源记录，先清理...")
            cur.execute("""
                DELETE FROM ai_skill_resource
                WHERE skill_api_key = %s AND version = %s AND tenant_id = 0
            """, (SKILL_API_KEY, VERSION))

        # 创建 scripts 目录节点
        scripts_dir_id = next_id()
        cur.execute("""
            INSERT INTO ai_skill_resource (
                id, tenant_id, skill_api_key, version, parent_id,
                node_type, name, path, depth,
                content, content_type, content_size, description, icon, sort_num,
                enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
            ) VALUES (
                %s, 0, %s, %s, NULL,
                'dir', 'scripts', 'scripts', 0,
                NULL, '', 0, '分析脚本目录', '📁', 0,
                1, 0, %s, 0, %s, 0
            )
        """, (scripts_dir_id, SKILL_API_KEY, VERSION, now, now))

        # 创建 main.py
        main_py_id = next_id()
        main_py_size = len(MAIN_PY.encode("utf-8"))
        cur.execute("""
            INSERT INTO ai_skill_resource (
                id, tenant_id, skill_api_key, version, parent_id,
                node_type, name, path, depth,
                content, content_type, content_size, description, icon, sort_num,
                enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
            ) VALUES (
                %s, 0, %s, %s, %s,
                'file', 'main.py', 'scripts/main.py', 1,
                %s, 'py', %s, '客户增长分析主脚本', '', 0,
                1, 0, %s, 0, %s, 0
            )
        """, (main_py_id, SKILL_API_KEY, VERSION, scripts_dir_id,
              MAIN_PY, main_py_size, now, now))

        # 创建 requirements.txt
        req_id = next_id()
        req_size = len(REQUIREMENTS_TXT.encode("utf-8"))
        cur.execute("""
            INSERT INTO ai_skill_resource (
                id, tenant_id, skill_api_key, version, parent_id,
                node_type, name, path, depth,
                content, content_type, content_size, description, icon, sort_num,
                enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
            ) VALUES (
                %s, 0, %s, %s, %s,
                'file', 'requirements.txt', 'scripts/requirements.txt', 1,
                %s, 'txt', %s, 'Python 依赖声明', '', 0,
                1, 0, %s, 0, %s, 0
            )
        """, (req_id, SKILL_API_KEY, VERSION, scripts_dir_id,
              REQUIREMENTS_TXT, req_size, now, now))

        conn.commit()

    print(f"✅ 资源文件已写入数据库")
    print(f"   skill: {SKILL_API_KEY} v{VERSION}")
    print(f"   scripts/main.py: {main_py_size} bytes")
    print(f"   scripts/requirements.txt: {req_size} bytes")

    # 同时更新 ext_info 添加 script_execution 配置
    with get_conn() as conn:
        cur = conn.cursor()
        import json
        ext_info = {
            "argument_descriptions": {
                "time_range": "分析时间范围：all（全部）/ last_12_months（近12月）/ 指定年份如2024，默认all"
            },
            "script_execution": {
                "entry": "scripts/main.py",
                "language": "python",
                "required_packages": [],
                "auto_install": False,
                "timeout": 60
            }
        }
        cur.execute("""
            UPDATE ai_skill SET ext_info = %s, updated_at = %s
            WHERE api_key = %s AND tenant_id = 0 AND delete_flg = 0
        """, (json.dumps(ext_info, ensure_ascii=False), now, SKILL_API_KEY))
        conn.commit()

    print(f"   ext_info.script_execution 已更新")


if __name__ == "__main__":
    main()
