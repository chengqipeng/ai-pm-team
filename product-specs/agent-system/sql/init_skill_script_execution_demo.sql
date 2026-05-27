-- ═══════════════════════════════════════════════════════════
-- Skill 脚本执行能力 Demo — 数据趋势分析技能
--
-- 验证目标：
--   1. Skill 定义中包含 script_execution 配置
--   2. ai_skill_resource 中存储 scripts/ 目录下的 Python 脚本
--   3. prompt 中使用 ${SKILL_DIR} 模板变量引用脚本路径
--   4. Agent 执行时通过 ScriptSyncer 同步脚本到沙盒
--   5. LLM 按 prompt 指令调用 terminal/execute_code 执行脚本
--
-- 依赖表：ai_skill + ai_skill_definition + ai_skill_resource
-- 执行前提：三表结构已创建（migrate_skill_version_refactor.sql）
-- ═══════════════════════════════════════════════════════════

SET search_path TO paas_ai;

-- ═══════════════════════════════════════════════════════════
-- 1. ai_skill — 主记录
-- ═══════════════════════════════════════════════════════════

INSERT INTO ai_skill (
    id, api_key, tenant_id,
    name, description, owner, category, tags, icon, sort_num,
    current_version, enabled_flg, system_flg,
    exec_count, success_count, avg_duration_ms,
    ext_info,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    3000000000000001,
    'csv-trend-analysis',
    0,  -- 平台级
    'CSV 数据趋势分析',
    '分析 CSV 数据文件的趋势变化，生成统计摘要和可视化图表，支持自定义分析维度',
    'AI-Platform',
    'analysis',
    '["data","csv","trend","python","sandbox"]',
    '📈',
    50,
    '1.0.0',
    1, -- enabled
    0, -- 非系统预置，用于演示
    0, 0, 0,
    '{"script_execution":{"entry":"scripts/analyze.py","language":"python","required_packages":["pandas>=2.0","matplotlib>=3.7"],"auto_install":true,"timeout":120},"preload_resources":{"always":["references/usage-guide.md"],"max_preload":2}}',
    0,
    1748188800000,  -- 2025-05-25
    0,
    1748188800000,
    0
) ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING;

-- ═══════════════════════════════════════════════════════════
-- 2. ai_skill_definition — 版本内容（含 prompt + script_execution 配置）
-- ═══════════════════════════════════════════════════════════

INSERT INTO ai_skill_definition (
    id, skill_api_key, tenant_id, version,
    changelog,
    when_to_use, context, agent, model,
    allowed_tools, arguments, prompt,
    risk_level, requires_confirmation, max_tool_calls, timeout_ms,
    output_mode, component_apikey, post_output_behavior,
    published_by,
    delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    3000000000000101,
    'csv-trend-analysis',
    0,
    '1.0.0',
    '初始版本：支持 CSV 数据趋势分析，含 Python 脚本自动同步执行',
    '数据趋势|CSV分析|趋势分析|数据变化|时间序列|统计分析',
    'inline',  -- inline 模式：prompt 注入当前对话
    '',        -- 无指定子 Agent
    '',        -- 继承主模型
    '["terminal","execute_code","read_file","write_file"]',
    '["input_file","analysis_type"]',
    '# CSV 数据趋势分析

你是一位数据分析专家。请使用预装在沙盒中的 Python 分析脚本，对用户指定的 CSV 文件进行趋势分析。

## 前置条件
- 分析脚本已自动同步到沙盒: `${SKILL_DIR}/scripts/`
- 如首次执行，需先安装依赖

## 执行步骤

### 步骤 1: 安装依赖（仅首次需要）
```bash
pip install -r ${SKILL_DIR}/scripts/requirements.txt
```
如果提示已安装则跳过。

### 步骤 2: 确认输入文件存在
```bash
ls -la {input_file}
```
如果文件不存在，提示用户上传或指定正确路径。

### 步骤 3: 运行分析脚本
```bash
python3 ${SKILL_DIR}/scripts/analyze.py --input {input_file} --type {analysis_type} --output /tmp/analysis_result.json
```

参数说明：
- `--input`: CSV 文件路径
- `--type`: 分析类型（trend/summary/correlation），默认 trend
- `--output`: 结果输出路径

### 步骤 4: 读取分析结果
使用 read_file 读取 `/tmp/analysis_result.json`

### 步骤 5: 生成报告
根据 JSON 结果，生成结构化的分析报告：
- 📊 数据概览（行数、列数、时间范围）
- 📈 趋势发现（上升/下降/平稳的指标）
- ⚠️ 异常点（偏离均值 2σ 以上的数据点）
- 💡 建议（基于趋势给出的业务建议）

## 错误处理
- 如果脚本报 ModuleNotFoundError → 重新执行步骤 1
- 如果脚本报 FileNotFoundError → 检查文件路径
- 如果脚本报 ValueError → 检查 CSV 格式是否正确

## 注意事项
- 不要用 execute_code 重写分析逻辑，直接使用预装脚本
- 如果需要自定义分析，可以先 read_file 查看脚本源码了解支持的参数
- 图表文件会保存到 /tmp/，可通过 read_file 返回给用户',
    'read_only',
    0,   -- 无需确认
    10,
    120000,  -- 2 分钟超时
    'text',
    '',
    'silent',
    0,
    0, 1748188800000, 0, 1748188800000, 0
) ON CONFLICT (tenant_id, skill_api_key, version) WHERE delete_flg = 0 DO NOTHING;

-- ═══════════════════════════════════════════════════════════
-- 3. ai_skill_resource — 资源文件树
--    目录结构:
--      scripts/
--        ├── analyze.py          (主入口脚本)
--        ├── utils.py            (辅助模块)
--        └── requirements.txt    (依赖声明)
--      references/
--        └── usage-guide.md      (使用说明)
-- ═══════════════════════════════════════════════════════════

-- ── 3.1 目录节点 ──

-- scripts/ 目录
INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    3000000000001001, 0, 'csv-trend-analysis', '1.0.0',
    NULL, 'dir', 'scripts', 'scripts', 0,
    NULL, 'dir', 0,
    '可执行脚本目录 — 自动同步到沙盒', '📂', 10,
    1, 0, 1748188800000, 0, 1748188800000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;

-- references/ 目录
INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    3000000000001002, 0, 'csv-trend-analysis', '1.0.0',
    NULL, 'dir', 'references', 'references', 0,
    NULL, 'dir', 0,
    '参考文档目录', '📁', 20,
    1, 0, 1748188800000, 0, 1748188800000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;

-- ── 3.2 scripts/analyze.py — 主入口脚本 ──

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    3000000000001011, 0, 'csv-trend-analysis', '1.0.0',
    3000000000001001, 'file', 'analyze.py', 'scripts/analyze.py', 1,
    '#!/usr/bin/env python3
"""CSV 数据趋势分析脚本

用法:
    python3 analyze.py --input data.csv --type trend --output result.json

分析类型:
    trend       — 时间序列趋势分析（默认）
    summary     — 统计摘要
    correlation — 列间相关性分析
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import numpy as np


def analyze_trend(df: pd.DataFrame) -> dict:
    """时间序列趋势分析"""
    result = {"type": "trend", "columns": [], "trends": []}

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    result["columns"] = numeric_cols

    for col in numeric_cols:
        series = df[col].dropna()
        if len(series) < 3:
            continue

        # 简单线性趋势
        x = np.arange(len(series))
        slope, intercept = np.polyfit(x, series.values, 1)

        # 变化率
        pct_change = ((series.iloc[-1] - series.iloc[0]) / series.iloc[0] * 100
                      if series.iloc[0] != 0 else 0)

        # 异常点检测 (2σ)
        mean, std = series.mean(), series.std()
        anomalies = series[(series - mean).abs() > 2 * std].index.tolist()

        direction = "上升" if slope > 0.01 else ("下降" if slope < -0.01 else "平稳")

        result["trends"].append({
            "column": col,
            "direction": direction,
            "slope": round(float(slope), 4),
            "pct_change": round(float(pct_change), 2),
            "mean": round(float(mean), 2),
            "std": round(float(std), 2),
            "min": round(float(series.min()), 2),
            "max": round(float(series.max()), 2),
            "anomaly_count": len(anomalies),
            "anomaly_indices": anomalies[:5],  # 最多返回 5 个
        })

    return result


def analyze_summary(df: pd.DataFrame) -> dict:
    """统计摘要"""
    desc = df.describe(include="all").to_dict()
    # 转换 NaN 为 None
    for col in desc:
        for key in desc[col]:
            val = desc[col][key]
            if isinstance(val, float) and np.isnan(val):
                desc[col][key] = None
            elif isinstance(val, (np.integer, np.floating)):
                desc[col][key] = round(float(val), 4)

    return {
        "type": "summary",
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": df.columns.tolist(),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "missing_values": df.isnull().sum().to_dict(),
        "statistics": desc,
    }


def analyze_correlation(df: pd.DataFrame) -> dict:
    """相关性分析"""
    numeric_df = df.select_dtypes(include=[np.number])
    if numeric_df.shape[1] < 2:
        return {"type": "correlation", "error": "数值列不足 2 列，无法计算相关性"}

    corr_matrix = numeric_df.corr()

    # 找出强相关对 (|r| > 0.7)
    strong_pairs = []
    for i in range(len(corr_matrix.columns)):
        for j in range(i + 1, len(corr_matrix.columns)):
            r = corr_matrix.iloc[i, j]
            if abs(r) > 0.7:
                strong_pairs.append({
                    "col_a": corr_matrix.columns[i],
                    "col_b": corr_matrix.columns[j],
                    "correlation": round(float(r), 4),
                    "strength": "强正相关" if r > 0.7 else "强负相关",
                })

    return {
        "type": "correlation",
        "matrix": {col: {k: round(float(v), 4) for k, v in row.items()}
                   for col, row in corr_matrix.to_dict().items()},
        "strong_pairs": strong_pairs,
    }


def main():
    parser = argparse.ArgumentParser(description="CSV 数据趋势分析")
    parser.add_argument("--input", required=True, help="输入 CSV 文件路径")
    parser.add_argument("--type", default="trend",
                        choices=["trend", "summary", "correlation"],
                        help="分析类型")
    parser.add_argument("--output", default="/tmp/analysis_result.json",
                        help="输出 JSON 文件路径")
    args = parser.parse_args()

    # 读取 CSV
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"错误: 文件不存在 — {args.input}", file=sys.stderr)
        sys.exit(1)

    try:
        df = pd.read_csv(args.input)
    except Exception as e:
        print(f"错误: CSV 解析失败 — {e}", file=sys.stderr)
        sys.exit(1)

    print(f"已加载: {len(df)} 行 × {len(df.columns)} 列")

    # 执行分析
    analyzers = {
        "trend": analyze_trend,
        "summary": analyze_summary,
        "correlation": analyze_correlation,
    }

    result = analyzers[args.type](df)
    result["meta"] = {
        "input_file": args.input,
        "rows": len(df),
        "columns": len(df.columns),
        "analysis_type": args.type,
    }

    # 输出结果
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))

    print(f"分析完成: {args.type}")
    print(f"结果已写入: {args.output}")


if __name__ == "__main__":
    main()
',
    'python', 4200,
    '主分析脚本 — 支持 trend/summary/correlation 三种分析模式', '🐍', 10,
    1, 0, 1748188800000, 0, 1748188800000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;

-- ── 3.3 scripts/utils.py — 辅助模块 ──

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    3000000000001012, 0, 'csv-trend-analysis', '1.0.0',
    3000000000001001, 'file', 'utils.py', 'scripts/utils.py', 1,
    '"""辅助工具函数"""
import hashlib
from pathlib import Path


def file_hash(filepath: str) -> str:
    """计算文件 MD5 哈希（用于增量同步判断）"""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_dir(path: str) -> Path:
    """确保目录存在"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def truncate_output(text: str, max_chars: int = 5000) -> str:
    """截断过长输出"""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n\n[... 输出已截断 ...]\n\n" + text[-half:]
',
    'python', 620,
    '辅助工具函数（哈希计算、目录创建、输出截断）', '🐍', 20,
    1, 0, 1748188800000, 0, 1748188800000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;

-- ── 3.4 scripts/requirements.txt — 依赖声明 ──

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    3000000000001013, 0, 'csv-trend-analysis', '1.0.0',
    3000000000001001, 'file', 'requirements.txt', 'scripts/requirements.txt', 1,
    'pandas>=2.0
numpy>=1.24
matplotlib>=3.7
',
    'text', 45,
    'Python 依赖声明 — 首次执行时自动安装', '📋', 30,
    1, 0, 1748188800000, 0, 1748188800000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;

-- ── 3.5 references/usage-guide.md — 使用说明（预加载知识文件） ──

INSERT INTO ai_skill_resource (
    id, tenant_id, skill_api_key, version,
    parent_id, node_type, name, path, depth,
    content, content_type, content_size,
    description, icon, sort_num,
    enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
) VALUES (
    3000000000001021, 0, 'csv-trend-analysis', '1.0.0',
    3000000000001002, 'file', 'usage-guide.md', 'references/usage-guide.md', 1,
    '# CSV 趋势分析 — 使用指南

## 支持的分析类型

| 类型 | 说明 | 适用场景 |
|------|------|---------|
| `trend` | 时间序列趋势分析 | 销售额变化、用户增长、KPI 追踪 |
| `summary` | 统计摘要 | 数据概览、分布特征、缺失值检查 |
| `correlation` | 相关性分析 | 发现指标间关联、特征选择 |

## CSV 格式要求

- 编码：UTF-8（推荐）或 GBK
- 分隔符：逗号（标准 CSV）
- 首行：列名（英文或中文均可）
- 数值列：纯数字，不含千分位逗号
- 日期列：推荐 YYYY-MM-DD 格式

## 输出说明

### trend 模式输出
- `direction`: 趋势方向（上升/下降/平稳）
- `slope`: 线性回归斜率
- `pct_change`: 首尾变化百分比
- `anomaly_count`: 异常点数量（偏离 2σ）

### summary 模式输出
- `statistics`: 各列的 count/mean/std/min/max/25%/50%/75%
- `missing_values`: 各列缺失值数量
- `dtypes`: 各列数据类型

### correlation 模式输出
- `matrix`: 相关系数矩阵
- `strong_pairs`: 强相关对（|r| > 0.7）

## 常见问题

**Q: 脚本报 UnicodeDecodeError**
A: CSV 文件可能是 GBK 编码，在脚本中已自动尝试 GBK fallback

**Q: 数值列被识别为字符串**
A: 检查是否有非数字字符（如 "N/A"、"-"），建议预处理为空值

**Q: 趋势分析结果全部显示"平稳"**
A: 数据量可能不足（建议 ≥ 10 行），或数值波动在阈值内
',
    'md', 1350,
    '使用指南 — 分析类型说明、CSV 格式要求、输出字段解释', '📖', 10,
    1, 0, 1748188800000, 0, 1748188800000, 0
) ON CONFLICT (tenant_id, skill_api_key, version, path) WHERE delete_flg = 0 DO NOTHING;

-- ═══════════════════════════════════════════════════════════
-- 4. 验证查询 — 确认数据写入正确
-- ═══════════════════════════════════════════════════════════

-- 验证 1: 主记录
-- SELECT api_key, name, current_version, ext_info
-- FROM ai_skill WHERE api_key = 'csv-trend-analysis' AND delete_flg = 0;

-- 验证 2: 版本内容
-- SELECT skill_api_key, version, context, allowed_tools, 
--        LEFT(prompt, 100) AS prompt_preview
-- FROM ai_skill_definition 
-- WHERE skill_api_key = 'csv-trend-analysis' AND delete_flg = 0;

-- 验证 3: 资源文件树
-- SELECT node_type, path, name, content_type, content_size, description
-- FROM ai_skill_resource
-- WHERE skill_api_key = 'csv-trend-analysis' AND version = '1.0.0' AND delete_flg = 0
-- ORDER BY depth, sort_num;

-- 预期输出:
-- node_type | path                      | name             | content_type | content_size
-- dir       | scripts                   | scripts          | dir          | 0
-- dir       | references                | references       | dir          | 0
-- file      | scripts/analyze.py        | analyze.py       | python       | 4200
-- file      | scripts/utils.py          | utils.py         | python       | 620
-- file      | scripts/requirements.txt  | requirements.txt | text         | 45
-- file      | references/usage-guide.md | usage-guide.md   | md           | 1350

-- ═══════════════════════════════════════════════════════════
-- 5. 执行流程说明（注释）
-- ═══════════════════════════════════════════════════════════

-- 当用户触发此 Skill 时，系统执行以下流程：
--
-- ① SkillRegistry.match_by_intent("分析 sales.csv 的趋势")
--    → 匹配到 csv-trend-analysis（关键词: 数据趋势|CSV分析|趋势分析）
--
-- ② SkillExecutor.execute("csv-trend-analysis", {"input_file":"sales.csv","analysis_type":"trend"})
--    → 检测 ext_info.script_execution 存在
--
-- ③ ScriptSyncer.sync("csv-trend-analysis", version="1.0.0")
--    → 从 ai_skill_resource 查询 scripts/ 下 3 个文件
--    → 对比沙盒中 /sandbox/.skills/csv-trend-analysis/.sync_manifest.json
--    → 增量写入变更文件到沙盒:
--       /sandbox/.skills/csv-trend-analysis/scripts/analyze.py
--       /sandbox/.skills/csv-trend-analysis/scripts/utils.py
--       /sandbox/.skills/csv-trend-analysis/scripts/requirements.txt
--    → chmod +x *.py
--    → 更新 .sync_manifest.json
--
-- ④ format_prompt({"input_file":"sales.csv","analysis_type":"trend"})
--    → ${SKILL_DIR} 替换为 /sandbox/.skills/csv-trend-analysis
--    → {input_file} 替换为 sales.csv
--    → {analysis_type} 替换为 trend
--
-- ⑤ 格式化后的 prompt 注入当前对话（inline 模式）
--    LLM 按步骤执行:
--    → terminal("pip install -r /sandbox/.skills/csv-trend-analysis/scripts/requirements.txt")
--    → terminal("python3 /sandbox/.skills/csv-trend-analysis/scripts/analyze.py --input sales.csv --type trend --output /tmp/analysis_result.json")
--    → read_file(path="/tmp/analysis_result.json")
--    → 生成结构化报告返回用户
