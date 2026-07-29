"""修复 csv-trend-analysis 的 prompt：使用 ${SKILL_DIR} 模板变量，用户只写相对路径"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.store.pg_pool import get_conn

NEW_PROMPT = r"""# CSV 数据趋势分析

你是一位数据分析专家。请使用预装在沙盒中的 Python 分析脚本，对用户指定的 CSV 文件进行趋势分析。

## 重要：脚本已预装，直接使用

分析脚本已自动同步到沙盒 `${SKILL_DIR}/` 目录下：
- 主脚本: `${SKILL_DIR}/scripts/analyze.py`
- 辅助模块: `${SKILL_DIR}/scripts/utils.py`

脚本使用纯 Python 标准库（csv/json/math），**无需 pip install 任何依赖**。

## 执行步骤（严格按顺序，不要探索文件系统）

### 步骤 1: 确认输入文件路径
如果用户已指定 CSV 文件路径，直接使用。否则询问用户文件在哪里。

### 步骤 2: 运行分析脚本
```bash
python3 ${SKILL_DIR}/scripts/analyze.py --input <CSV路径> --type <类型> --output /tmp/analysis_result.json
```

`--type` 参数选择：
| 类型 | 说明 | 适用场景 |
|------|------|---------|
| trend | 时间序列趋势 | 看数据涨跌、变化率 |
| summary | 统计摘要 | 看均值、极值、分布 |
| correlation | 相关性 | 看列间关联 |

默认使用 `trend`。根据用户意图选择合适的类型。

### 步骤 3: 读取结果
用 `read_file` 读取 `/tmp/analysis_result.json`

### 步骤 4: 生成报告
根据 JSON 结果生成结构化报告：
- 📊 **数据概览**: 行数、列数
- 📈 **趋势发现**: 每列的方向（上升/下降/平稳）、变化百分比
- ⚠️ **异常点**: anomaly_count > 0 的列
- 💡 **建议**: 基于趋势给出业务建议

## 错误处理
- `FileNotFoundError` → 告知用户文件路径不正确
- 其他错误 → 展示错误信息

## 禁止事项（违反会导致超时）
- ❌ 不要用 search_files 搜索脚本（路径已告知）
- ❌ 不要用 terminal 探索目录结构
- ❌ 不要用 write_file 重写分析逻辑
- ❌ 不要重复调用相同命令
- ❌ 命令执行后不要自行重试，直接基于结果回复"""

with get_conn() as conn:
    cur = conn.cursor()
    cur.execute(
        "UPDATE ai_skill_definition SET prompt = %s, updated_at = 1748189300000 "
        "WHERE skill_api_key = %s AND tenant_id = 0 AND delete_flg = 0",
        (NEW_PROMPT, 'csv-trend-analysis')
    )
    print(f"Updated {cur.rowcount} row(s)")
    conn.commit()

print("✅ Prompt 已更新")
print(f"   长度: {len(NEW_PROMPT)} 字符")
print(f"   使用 ${{SKILL_DIR}} 模板变量（运行时由 format_prompt 替换为实际路径）")
print(f"   用户定义 Skill 时只需写 scripts/analyze.py 相对路径")
