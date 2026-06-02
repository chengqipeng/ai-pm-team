#!/usr/bin/env python3
"""Tool 评测 CLI — 命令行运行工具评测

用法:
    # 运行全量评测
    python scripts/run_tool_eval.py

    # 只评测指定工具
    python scripts/run_tool_eval.py --tools query_data modify_data

    # 只评测指定分类
    python scripts/run_tool_eval.py --categories normal error

    # 指定用例 ID
    python scripts/run_tool_eval.py --cases qd_01 qd_02 md_01
"""
import asyncio
import argparse
import os
import sys

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    parser = argparse.ArgumentParser(description="Tool 评测 CLI")
    parser.add_argument("--tools", nargs="*", help="只评测指定工具")
    parser.add_argument("--categories", nargs="*", help="只评测指定分类 (normal/error/boundary/side_effect)")
    parser.add_argument("--cases", nargs="*", help="只执行指定用例 ID")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    from src.eval.tool_eval_runner import ToolEvalRunner, ToolEvalSuite, print_report
    from src.eval.tool_eval_presets import build_default_suite

    # 构建评测集
    suite = build_default_suite()

    # 筛选
    cases = suite.cases
    if args.tools:
        cases = [c for c in cases if c.tool_name in args.tools]
    if args.categories:
        cases = [c for c in cases if c.category in args.categories]
    if args.cases:
        cases = [c for c in cases if c.id in args.cases]

    if not cases:
        print("❌ 筛选后无可执行的用例")
        sys.exit(1)

    filtered_suite = ToolEvalSuite(
        id=suite.id,
        name=suite.name,
        description=suite.description,
        cases=cases,
    )

    print(f"🚀 开始执行 Tool 评测 — {len(cases)} 个用例")
    print()

    # 执行
    runner = ToolEvalRunner()
    report = await runner.run_suite(filtered_suite)

    if args.json:
        import json
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print_report(report)

    # 退出码
    sys.exit(0 if report.failed == 0 and report.error == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
