"""
Skill 脚本执行端到端测试 — 模拟完整链路（不依赖 LLM）

测试流程:
  1. 从 DB 加载 csv-trend-analysis skill
  2. SkillExecutor 自动同步脚本到沙盒
  3. 在沙盒中创建测试 CSV 文件
  4. 在沙盒中安装依赖 (pip install)
  5. 在沙盒中执行分析脚本
  6. 验证输出结果

使用方式:
    SANDBOX_SSH_HOST=172.17.2.118 SANDBOX_SSH_USER=hermes \
    SANDBOX_SSH_KEY=~/.ssh/hermes_vm_key python3 scripts/test_skill_script_e2e.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.skills.base import SkillDefinition, SkillExecutor, SkillRegistry
from src.tools.sandbox import SSHBackend, create_ssh_backend_from_env, ScriptSyncer, SKILL_BASE_DIR


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


async def main():
    print("=" * 70)
    print("  Skill 脚本执行 — 端到端测试（不依赖 LLM）")
    print("=" * 70)

    # ── 1. 从 DB 加载 Skill ──
    print("\n── 1. 从 DB 加载 csv-trend-analysis ──")
    from src.store.pg_pool import get_conn

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

    if not row:
        print("❌ DB 中未找到 csv-trend-analysis，请先执行 init_skill_script_execution_demo.sql")
        return

    skill = SkillDefinition(
        name=row[0], description="CSV 数据趋势分析",
        prompt=row[2], context=row[3],
        allowed_tools=json.loads(row[4]), arguments=json.loads(row[5]),
        version=row[1], tenant_id=0,
    )
    skill.ext_info = row[6]
    print(f"  ✅ 加载成功: {skill.name} v{skill.version}")

    # ── 2. 连接沙盒 ──
    print("\n── 2. 连接沙盒 ──")
    backend = create_ssh_backend_from_env()
    await backend.connect()
    print(f"  ✅ 已连接: {backend.config.ssh_user}@{backend.config.ssh_host}")

    # ── 3. SkillExecutor 执行（自动同步脚本 + 模板替换） ──
    print("\n── 3. SkillExecutor.execute() — 自动同步 + 模板替换 ──")

    class Ctx:
        sandbox_backend = backend

    registry = SkillRegistry()
    registry.register(skill)
    executor = SkillExecutor(registry=registry, context=Ctx())

    formatted_prompt = await executor.execute(
        "csv-trend-analysis",
        {"input_file": "/tmp/test_sales.csv", "analysis_type": "trend"},
    )
    print(f"  ✅ prompt 已格式化 ({len(formatted_prompt)} 字符)")

    # 验证模板变量已替换
    skill_dir = f"{SKILL_BASE_DIR}/csv-trend-analysis"
    assert skill_dir in formatted_prompt, "❌ ${SKILL_DIR} 未替换"
    assert "/tmp/test_sales.csv" in formatted_prompt, "❌ {input_file} 未替换"
    print(f"  ✅ 模板变量替换正确: ${{SKILL_DIR}} → {skill_dir}")

    # ── 4. 创建测试 CSV ──
    print("\n── 4. 在沙盒中创建测试 CSV ──")
    await backend.write_file("/tmp/test_sales.csv", TEST_CSV)
    exists = await backend.file_exists("/tmp/test_sales.csv")
    print(f"  ✅ /tmp/test_sales.csv 已创建" if exists else "  ❌ 创建失败")

    # ── 5. 安装依赖 ──
    print("\n── 5. 安装 Python 依赖 ──")
    install_result = await backend.execute(
        f"pip install -r {skill_dir}/scripts/requirements.txt -q", timeout=60
    )
    if install_result.is_error:
        print(f"  ⚠️  安装可能有问题: {install_result.output[:200]}")
    else:
        print("  ✅ 依赖安装完成")

    # ── 6. 执行分析脚本 ──
    print("\n── 6. 执行分析脚本 ──")
    exec_cmd = (
        f"python3 {skill_dir}/scripts/analyze.py "
        f"--input /tmp/test_sales.csv --type trend --output /tmp/analysis_result.json"
    )
    print(f"  命令: {exec_cmd}")
    exec_result = await backend.execute(exec_cmd, timeout=30)

    if exec_result.is_error:
        print(f"  ❌ 执行失败:\n  {exec_result.output}")
    else:
        print(f"  ✅ 执行成功:\n  {exec_result.stdout.strip()}")

    # ── 7. 读取并验证结果 ──
    print("\n── 7. 验证分析结果 ──")
    read_result = await backend.read_file("/tmp/analysis_result.json")

    if read_result.is_error:
        print(f"  ❌ 读取结果失败: {read_result.output}")
    else:
        try:
            result_data = json.loads(read_result.stdout)
            print(f"  分析类型: {result_data.get('type')}")
            print(f"  数据行数: {result_data.get('meta', {}).get('rows')}")
            print(f"  趋势数量: {len(result_data.get('trends', []))}")

            # 验证趋势结果
            for t in result_data.get("trends", []):
                print(f"    📈 {t['column']}: {t['direction']} "
                      f"(slope={t['slope']}, 变化={t['pct_change']}%)")

            if result_data.get("type") == "trend" and len(result_data.get("trends", [])) > 0:
                print("\n  ✅ 分析结果正确！")
            else:
                print("\n  ❌ 结果格式异常")
        except json.JSONDecodeError as e:
            print(f"  ❌ JSON 解析失败: {e}")
            print(f"  原始内容: {read_result.stdout[:200]}")

    # ── 8. 测试 summary 模式 ──
    print("\n── 8. 测试 summary 分析模式 ──")
    exec_result2 = await backend.execute(
        f"python3 {skill_dir}/scripts/analyze.py "
        f"--input /tmp/test_sales.csv --type summary --output /tmp/summary_result.json",
        timeout=30,
    )
    if not exec_result2.is_error:
        read2 = await backend.read_file("/tmp/summary_result.json")
        if not read2.is_error:
            summary = json.loads(read2.stdout)
            print(f"  行数: {summary.get('rows')}, 列数: {summary.get('columns')}")
            print(f"  列名: {summary.get('column_names')}")
            print(f"  缺失值: {summary.get('missing_values')}")
            print("  ✅ summary 模式正常")
        else:
            print(f"  ❌ 读取失败: {read2.output}")
    else:
        print(f"  ❌ 执行失败: {exec_result2.output}")

    # ── 清理 ──
    print("\n── 清理 ──")
    await backend.execute("rm -f /tmp/test_sales.csv /tmp/analysis_result.json /tmp/summary_result.json")
    syncer = ScriptSyncer(backend=backend, tenant_id=0)
    await syncer.cleanup("csv-trend-analysis")
    await backend.disconnect()
    print("  ✅ 清理完成")

    print("\n" + "=" * 70)
    print("  🎉 端到端测试完成！")
    print("  完整链路: DB → ScriptSyncer → 沙盒 → 脚本执行 → JSON 结果")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
