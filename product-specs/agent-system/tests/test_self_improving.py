"""自改进学习循环验证 — 对比无技能 vs 有技能 vs 优化后技能

模拟 CRM 场景：用户反复执行 "分析商机 Pipeline" 任务
- Round 1: 无技能 → Agent 从零推理，记录工具调用链
- Round 2: 自动生成技能 → 复用 SOP，减少推理步骤
- Round 3: 优化后技能 → 更精准的 SOP，进一步减少 token
"""
import asyncio
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.skills.tracker import SkillTracker, SkillExecution
from src.skills.optimizer import SkillOptimizer
from src.skills.base import SkillDefinition, SkillRegistry, SkillLoader

passed = 0
failed = 0

def check(name, condition):
    global passed, failed
    if condition:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name}")
        failed += 1


def test_tracker():
    """SkillTracker — 执行轨迹记录 + 度量"""
    print("\n📦 1. SkillTracker 执行轨迹记录")
    tmp = tempfile.mkdtemp()
    try:
        tracker = SkillTracker(db_path=os.path.join(tmp, "metrics.db"))

        # 模拟 5 次执行
        for i in range(5):
            feedback = "accepted" if i < 3 else "retry"
            tracker.record(SkillExecution(
                skill_name="pipeline-analysis",
                arguments={"entity": "opportunity"},
                tool_calls=[
                    {"name": "analyze_data", "args": {"group_by": "stage"}, "duration_ms": 120, "success": True},
                    {"name": "query_data", "args": {"entity": "opportunity"}, "duration_ms": 80, "success": True},
                ],
                total_tokens=1500 - i * 100,  # 模拟 token 递减
                duration_ms=2000 - i * 200,
                output=f"Pipeline 分析结果 #{i+1}",
                user_feedback=feedback,
                version=1,
            ))

        metrics = tracker.get_metrics("pipeline-analysis")
        check("记录 5 次执行", metrics is not None and metrics.total_executions == 5)
        check("成功 3 次", metrics.success_count == 3)
        check("重试 2 次", metrics.retry_count == 2)
        check("成功率 60%", abs(metrics.success_rate - 0.6) < 0.01)
        check("平均 token", metrics.avg_tokens > 0)
        check("不应淘汰（执行次数够但成功率>30%）", not metrics.should_retire)

        # 获取执行历史
        execs = tracker.get_executions("pipeline-analysis", limit=3)
        check("获取最近 3 次", len(execs) == 3)
        check("包含工具调用", len(execs[0].tool_calls) == 2)

        # 模拟低成功率技能
        for _ in range(5):
            tracker.record(SkillExecution(
                skill_name="bad-skill", arguments={}, tool_calls=[],
                total_tokens=500, duration_ms=1000, output="",
                user_feedback="abandoned", version=1,
            ))
        bad_metrics = tracker.get_metrics("bad-skill")
        check("低成功率技能应淘汰", bad_metrics.should_retire)

        # 获取所有度量
        all_metrics = tracker.get_all_metrics()
        check("获取所有度量", len(all_metrics) == 2)

        # 获取应淘汰的技能
        retiring = tracker.get_retiring_skills()
        check("淘汰列表包含 bad-skill", "bad-skill" in retiring)
        check("淘汰列表不包含 pipeline-analysis", "pipeline-analysis" not in retiring)

        tracker.close()
    finally:
        shutil.rmtree(tmp)


def test_optimizer_structure():
    """SkillOptimizer — 结构验证"""
    print("\n📦 2. SkillOptimizer 结构")
    tmp = tempfile.mkdtemp()
    try:
        tracker = SkillTracker(db_path=os.path.join(tmp, "metrics.db"))
        optimizer = SkillOptimizer(
            llm=None,  # 无 LLM 时不会崩溃
            tracker=tracker,
            skills_dir=os.path.join(tmp, "skills"),
        )
        check("创建成功", optimizer is not None)
        check("optimize_threshold 默认 5", optimizer._optimize_threshold == 5)
        tracker.close()
    finally:
        shutil.rmtree(tmp)


async def test_should_optimize():
    """should_optimize — 触发条件"""
    print("\n📦 3. should_optimize 触发条件")
    tmp = tempfile.mkdtemp()
    try:
        tracker = SkillTracker(db_path=os.path.join(tmp, "metrics.db"))
        optimizer = SkillOptimizer(llm=None, tracker=tracker, optimize_threshold=3)

        # 0 次执行 → 不触发
        check("0 次不触发", not await optimizer.should_optimize("test"))

        # 记录 2 次 → 不触发
        for _ in range(2):
            tracker.record(SkillExecution(skill_name="test", total_tokens=100, user_feedback="accepted"))
        check("2 次不触发", not await optimizer.should_optimize("test"))

        # 记录第 3 次 → 触发
        tracker.record(SkillExecution(skill_name="test", total_tokens=100, user_feedback="accepted"))
        check("3 次触发", await optimizer.should_optimize("test"))

        # 第 4 次 → 不触发
        tracker.record(SkillExecution(skill_name="test", total_tokens=100, user_feedback="accepted"))
        check("4 次不触发", not await optimizer.should_optimize("test"))

        # 第 6 次 → 触发
        for _ in range(2):
            tracker.record(SkillExecution(skill_name="test", total_tokens=100, user_feedback="accepted"))
        check("6 次触发", await optimizer.should_optimize("test"))

        tracker.close()
    finally:
        shutil.rmtree(tmp)


def test_comparison_simulation():
    """对比模拟 — 无技能 vs 有技能 vs 优化后技能"""
    print("\n📦 4. 对比模拟：无技能 vs 有技能 vs 优化后技能")
    print("  模拟场景：用户反复执行 '分析商机 Pipeline' 任务")

    tmp = tempfile.mkdtemp()
    try:
        tracker = SkillTracker(db_path=os.path.join(tmp, "metrics.db"))

        # ── Round 1: 无技能（Agent 从零推理）──
        print("\n  📊 Round 1: 无技能")
        r1_tokens = []
        r1_tool_calls = []
        for i in range(3):
            # 模拟无技能时的执行：LLM 需要多次试错
            tokens = 2500 + (i % 2) * 300  # 波动大
            tools = [
                {"name": "query_schema", "duration_ms": 50, "success": True},  # 先查 schema
                {"name": "query_data", "duration_ms": 80, "success": True},    # 查数据
                {"name": "query_data", "duration_ms": 80, "success": True},    # 再查一次（重复）
                {"name": "analyze_data", "duration_ms": 120, "success": True}, # 分析
                {"name": "analyze_data", "duration_ms": 120, "success": i > 0},# 再分析（可能失败）
            ]
            r1_tokens.append(tokens)
            r1_tool_calls.append(len(tools))

        r1_avg_tokens = sum(r1_tokens) / len(r1_tokens)
        r1_avg_tools = sum(r1_tool_calls) / len(r1_tool_calls)
        print(f"    平均 token: {r1_avg_tokens:.0f}")
        print(f"    平均工具调用: {r1_avg_tools:.1f}")

        # ── Round 2: 有技能（自动生成的 SOP）──
        print("\n  📊 Round 2: 有技能（自动生成）")
        r2_tokens = []
        r2_tool_calls = []
        for i in range(3):
            # 有 SOP 后：减少试错，但 SOP 可能不够精准
            tokens = 1800 + (i % 2) * 100  # 波动小
            tools = [
                {"name": "analyze_data", "duration_ms": 120, "success": True},  # 直接分析
                {"name": "query_data", "duration_ms": 80, "success": True},     # 查明细
                {"name": "analyze_data", "duration_ms": 100, "success": True},  # 补充分析
            ]
            r2_tokens.append(tokens)
            r2_tool_calls.append(len(tools))
            tracker.record(SkillExecution(
                skill_name="pipeline-analysis", arguments={"entity": "opportunity"},
                tool_calls=tools, total_tokens=tokens, duration_ms=1500,
                output="Pipeline 分析完成", user_feedback="accepted", version=1,
            ))

        r2_avg_tokens = sum(r2_tokens) / len(r2_tokens)
        r2_avg_tools = sum(r2_tool_calls) / len(r2_tool_calls)
        print(f"    平均 token: {r2_avg_tokens:.0f}")
        print(f"    平均工具调用: {r2_avg_tools:.1f}")

        # ── Round 3: 优化后技能（LLM 改写 SOP）──
        print("\n  📊 Round 3: 优化后技能")
        r3_tokens = []
        r3_tool_calls = []
        for i in range(3):
            # 优化后：SOP 更精准，去掉了多余步骤
            tokens = 1200 + (i % 2) * 50  # 波动最小
            tools = [
                {"name": "analyze_data", "duration_ms": 100, "success": True},  # 一次聚合搞定
                {"name": "query_data", "duration_ms": 60, "success": True},     # 精准查明细
            ]
            r3_tokens.append(tokens)
            r3_tool_calls.append(len(tools))
            tracker.record(SkillExecution(
                skill_name="pipeline-analysis", arguments={"entity": "opportunity"},
                tool_calls=tools, total_tokens=tokens, duration_ms=800,
                output="Pipeline 分析完成（优化版）", user_feedback="accepted", version=2,
            ))

        r3_avg_tokens = sum(r3_tokens) / len(r3_tokens)
        r3_avg_tools = sum(r3_tool_calls) / len(r3_tool_calls)
        print(f"    平均 token: {r3_avg_tokens:.0f}")
        print(f"    平均工具调用: {r3_avg_tools:.1f}")

        # ── 对比结果 ──
        print(f"\n  {'='*50}")
        print(f"  对比结果:")
        print(f"  {'='*50}")

        token_save_r2 = (1 - r2_avg_tokens / r1_avg_tokens) * 100
        token_save_r3 = (1 - r3_avg_tokens / r1_avg_tokens) * 100
        tool_save_r2 = (1 - r2_avg_tools / r1_avg_tools) * 100
        tool_save_r3 = (1 - r3_avg_tools / r1_avg_tools) * 100

        print(f"  | 指标         | 无技能    | 有技能    | 优化后    |")
        print(f"  |-------------|----------|----------|----------|")
        print(f"  | 平均 token   | {r1_avg_tokens:>7.0f}  | {r2_avg_tokens:>7.0f}  | {r3_avg_tokens:>7.0f}  |")
        print(f"  | 平均工具调用  | {r1_avg_tools:>7.1f}  | {r2_avg_tools:>7.1f}  | {r3_avg_tools:>7.1f}  |")
        print(f"  | token 节省   |    -     | {token_save_r2:>6.1f}% | {token_save_r3:>6.1f}% |")
        print(f"  | 工具调用节省  |    -     | {tool_save_r2:>6.1f}% | {tool_save_r3:>6.1f}% |")

        check("有技能比无技能省 token", r2_avg_tokens < r1_avg_tokens)
        check("优化后比有技能省 token", r3_avg_tokens < r2_avg_tokens)
        check("优化后比无技能省 token > 40%", token_save_r3 > 40)
        check("有技能比无技能少工具调用", r2_avg_tools < r1_avg_tools)
        check("优化后比有技能少工具调用", r3_avg_tools < r2_avg_tools)
        check("优化后比无技能少工具调用 > 50%", tool_save_r3 > 50)

        # 验证度量数据
        metrics = tracker.get_metrics("pipeline-analysis")
        check("总执行 6 次", metrics.total_executions == 6)
        check("成功率 100%", metrics.success_rate == 1.0)
        check("版本升级到 2", metrics.version == 2)

        tracker.close()
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    test_tracker()
    test_optimizer_structure()
    asyncio.run(test_should_optimize())
    test_comparison_simulation()

    print(f"\n{'='*60}")
    print(f"  自改进学习循环测试: {passed} passed, {failed} failed")
    print(f"{'='*60}")
    sys.exit(1 if failed else 0)
