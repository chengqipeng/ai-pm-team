#!/usr/bin/env python3
"""DeepEval Agent 评测 — 独立运行脚本

运行方式:
    poetry run python scripts/run_deepeval.py

    # 指定评测指标
    poetry run python scripts/run_deepeval.py --metrics task_completion correctness

    # 指定输入
    poetry run python scripts/run_deepeval.py --input "帮我查订单 ORD-001"
"""
import asyncio
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw")


async def main():
    parser = argparse.ArgumentParser(description="DeepEval Agent 评测")
    parser.add_argument("--metrics", nargs="*", default=["task_completion"],
                        help="评测指标: task_completion, answer_relevancy, correctness, tool_correctness")
    parser.add_argument("--input", nargs="*", default=None,
                        help="自定义输入（不指定则用默认用例）")
    args = parser.parse_args()

    # 默认评测用例
    inputs = args.input or [
        "帮我查一下订单 ORD-001 的状态",
        "查询客户张三的联系方式",
        "最近一周有多少新增订单",
    ]

    print(f"🚀 开始 DeepEval Agent 评测")
    print(f"   指标: {args.metrics}")
    print(f"   用例: {len(inputs)} 条")
    print()

    from src.eval.deepeval_integration import run_eval
    results = await run_eval(inputs=inputs, metrics=args.metrics)

    print(f"\n✅ 评测完成: {len(results)} 条用例")
    for r in results:
        print(f"   • {r['input'][:30]}... → {r['status']}")


if __name__ == "__main__":
    asyncio.run(main())
