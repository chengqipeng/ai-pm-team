"""Agent 端到端评测 — deepeval + LangGraph

运行方式:
    # deepeval CLI（结果上传 Confident AI dashboard）
    poetry run deepeval test run tests/test_agent_deepeval.py

    # 纯 pytest
    poetry run pytest tests/test_agent_deepeval.py -v
"""
import asyncio
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw")

from deepeval import assert_test
from deepeval.integrations.langchain import CallbackHandler
from deepeval.dataset import EvaluationDataset, Golden
from deepeval.metrics import TaskCompletionMetric, GEval
from deepeval.test_case import SingleTurnParams


# ── 评测用例 ──

dataset = EvaluationDataset(goldens=[
    Golden(input="帮我查一下订单 ORD-001 的状态"),
    Golden(input="查询客户张三的联系方式"),
    Golden(input="最近一周有多少新增订单"),
])


# ── Agent 缓存 ──

_graph = None

def _get_graph():
    global _graph
    if _graph is None:
        from src.eval.deepeval_integration import build_eval_agent
        _graph = asyncio.run(build_eval_agent())
    return _graph


# ── 测试 ──

@pytest.mark.parametrize("golden", dataset.goldens, ids=[g.input[:20] for g in dataset.goldens])
def test_agent_task_completion(golden: Golden):
    """Agent 任务完成度评测"""
    graph = _get_graph()
    graph.invoke(
        {"messages": [{"role": "user", "content": golden.input}]},
        config={
            "callbacks": [CallbackHandler(
                name="CRM-Agent-Eval",
                metrics=[TaskCompletionMetric(threshold=0.7)],
            )],
            "configurable": {"thread_id": f"eval_{hash(golden.input) % 10000}"},
        },
    )
    assert_test(golden=golden, metrics=[TaskCompletionMetric(threshold=0.7)])
