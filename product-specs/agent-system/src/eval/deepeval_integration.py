"""DeepEval 集成模块 — 将 DeepAgent (LangGraph) 与 deepeval 评测框架对接

集成方式：
    deepeval 通过 CallbackHandler 原生支持 LangGraph，
    只需在 graph.invoke() 时注入 callback 即可自动采集 trace。

三种使用模式：
    1. 脚本模式（evals_iterator）— 批量评测，结果上传 Confident AI
    2. CI/CD 模式（pytest）— 集成到持续集成流水线
    3. 在线评测模式 — 嵌入到 EvalRunner，与现有断言引擎协作

使用示例：
    # 最简单的评测
    from src.eval.deepeval_integration import run_agent_eval

    results = await run_agent_eval(
        inputs=["帮我查一下订单 ORD-001 的状态", "取消订单 ORD-002"],
        metrics=["task_completion", "tool_correctness"],
    )
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 核心：构建 Agent + CallbackHandler 并执行评测
# ═══════════════════════════════════════════════════════════

def _get_default_model_config() -> dict:
    """获取默认模型配置（与 server.py 一致）"""
    return {
        "model": os.environ.get("AGENT_MODEL", "deepseek-v4-flash"),
        "api_key": (os.environ.get("AGENT_API_KEY")
                    or os.environ.get("DEEPSEEK_API_KEY",
                                      "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw")),
        "api_base": os.environ.get("AGENT_API_BASE",
                                   "https://tokenhub.tencentmaas.com/v1"),
    }


async def build_eval_agent():
    """构建评测专用 Agent（复用 AgentFactory 完整链路）

    与 server.py 中的 _get_agent() 逻辑一致，但：
    - 使用独立的 MemorySaver（评测隔离）
    - 可选注入 MockToolGateway
    """
    from src.agents.langchain_agent import create_deep_agent, LangChainAgentConfig
    from src.tools.base import ToolRegistry
    from src.tools.crm_backend import CrmSimulatedBackend
    from src.tools.crm_tools import register_crm_tools
    from src.tools.metarepo_backend import MetarepoSimulatedBackend
    from src.tools.metarepo_tools import register_metarepo_tools
    from src.skills.base import SkillRegistry
    from src.core.prompt_builder import build_system_prompt
    from src.middleware.builder import build_middleware
    from langgraph.checkpoint.memory import MemorySaver

    cfg = _get_default_model_config()

    # 模拟后端（评测环境始终用模拟数据，保证可重复）
    crm_backend = CrmSimulatedBackend()
    metarepo_backend = MetarepoSimulatedBackend()

    reg = ToolRegistry()
    register_crm_tools(reg, crm_backend)
    register_metarepo_tools(reg, metarepo_backend)

    skill_reg = SkillRegistry()
    try:
        skill_reg.load_from_db(tenant_id=0)
    except Exception:
        pass

    system_prompt = build_system_prompt(
        agent_name="CRM-Agent-Eval",
        skills=skill_reg.list_all(),
        tools=reg.all_tools,
    )
    middlewares = build_middleware(
        system_prompt=system_prompt,
        agent_name="CRM-Agent-Eval",
    )

    config = LangChainAgentConfig(
        model=cfg["model"],
        api_key=cfg["api_key"],
        api_base=cfg["api_base"],
        tool_registry=reg,
        skill_registry=skill_reg,
        system_prompt=system_prompt,
        middlewares=middlewares,
        checkpointer=MemorySaver(),
    )

    return create_deep_agent(config)


# ═══════════════════════════════════════════════════════════
# 模式 1: 脚本模式 — 直接运行评测
# ═══════════════════════════════════════════════════════════

async def run_agent_eval(
    inputs: list[str],
    metrics: list[str] | None = None,
    expected_tools: dict[str, list[str]] | None = None,
) -> dict:
    """运行 Agent 评测（脚本模式）

    Args:
        inputs: 用户输入列表
        metrics: 要使用的 metric 名称列表，可选:
            - "task_completion": 任务完成度
            - "tool_correctness": 工具选择正确性
            - "answer_relevancy": 回复相关性
            - "g_eval": 自定义 G-Eval
        expected_tools: 每个 input 对应的期望工具列表（用于 tool_correctness）

    Returns:
        评测结果字典
    """
    from deepeval.integrations.langchain import CallbackHandler
    from deepeval.dataset import EvaluationDataset, Golden
    from deepeval.metrics import TaskCompletionMetric, AnswerRelevancyMetric, GEval
    from deepeval.test_case import SingleTurnParams

    # 构建 metrics
    metric_instances = _build_metrics(metrics or ["task_completion"])

    # 构建 dataset
    goldens = [Golden(input=inp) for inp in inputs]
    dataset = EvaluationDataset(goldens=goldens)

    # 构建 Agent
    graph = await build_eval_agent()

    # 执行评测
    for golden in dataset.evals_iterator(metrics=metric_instances):
        graph.invoke(
            {"messages": [{"role": "user", "content": golden.input}]},
            config={
                "callbacks": [CallbackHandler()],
                "configurable": {"thread_id": f"eval_{id(golden)}"},
            },
        )

    logger.info("Agent 评测完成: %d 个用例", len(inputs))
    return {"total": len(inputs), "status": "completed"}


def _build_metrics(metric_names: list[str]) -> list:
    """根据名称构建 deepeval metric 实例"""
    from deepeval.metrics import (
        TaskCompletionMetric,
        AnswerRelevancyMetric,
        GEval,
        ToolCorrectnessMetric,
    )
    from deepeval.test_case import SingleTurnParams

    metrics = []
    for name in metric_names:
        if name == "task_completion":
            metrics.append(TaskCompletionMetric(threshold=0.7))
        elif name == "answer_relevancy":
            metrics.append(AnswerRelevancyMetric(threshold=0.7))
        elif name == "tool_correctness":
            metrics.append(ToolCorrectnessMetric(threshold=0.7))
        elif name == "g_eval" or name == "correctness":
            metrics.append(GEval(
                name="Correctness",
                criteria="判断 Agent 的回复是否正确完成了用户的请求，包括工具调用是否合理、回复内容是否准确",
                evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
                threshold=0.5,
            ))
    return metrics


# ═══════════════════════════════════════════════════════════
# 模式 2: pytest CI/CD 模式
# ═══════════════════════════════════════════════════════════

# 使用方式: 在 tests/ 目录下创建 test_agent_deepeval.py
# 运行: poetry run deepeval test run tests/test_agent_deepeval.py

"""
示例 test 文件内容 (tests/test_agent_deepeval.py):

import pytest
import asyncio
from deepeval import assert_test
from deepeval.integrations.langchain import CallbackHandler
from deepeval.dataset import EvaluationDataset, Golden
from deepeval.metrics import TaskCompletionMetric
from src.eval.deepeval_integration import build_eval_agent

# 构建 Agent（模块级缓存）
_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = asyncio.run(build_eval_agent())
    return _graph

dataset = EvaluationDataset(goldens=[
    Golden(input="帮我查一下订单 ORD-001 的状态"),
    Golden(input="帮我取消订单 ORD-001"),
    Golden(input="查询客户张三的信息"),
])

@pytest.mark.parametrize("golden", dataset.goldens)
def test_agent_task_completion(golden: Golden):
    graph = get_graph()
    graph.invoke(
        {"messages": [{"role": "user", "content": golden.input}]},
        config={
            "callbacks": [CallbackHandler()],
            "configurable": {"thread_id": f"eval_{id(golden)}"},
        },
    )
    assert_test(golden=golden, metrics=[TaskCompletionMetric(threshold=0.7)])
"""


# ═══════════════════════════════════════════════════════════
# 模式 3: 与现有 EvalRunner 集成
# ═══════════════════════════════════════════════════════════

class DeepEvalCallbackInjector:
    """在现有 EvalRunner 执行流程中注入 deepeval CallbackHandler

    使用方式：
        injector = DeepEvalCallbackInjector(metrics=["task_completion"])
        # 在 EvalRunner.execute() 中构建 config 时调用:
        config = injector.inject_callback(config, eval_case)
        # Agent 执行完毕后获取 deepeval 评分:
        deepeval_results = injector.get_results()
    """

    def __init__(self, metrics: list[str] | None = None):
        from deepeval.integrations.langchain import CallbackHandler
        self._metrics = _build_metrics(metrics or ["task_completion"])
        self._callback = CallbackHandler(metrics=self._metrics)
        self._results = []

    def inject_callback(self, config: dict, eval_case: Any = None) -> dict:
        """将 CallbackHandler 注入到 Agent invoke 的 config 中"""
        callbacks = config.get("callbacks", [])
        callbacks.append(self._callback)
        config["callbacks"] = callbacks

        # 设置 trace metadata
        if eval_case and hasattr(eval_case, "id"):
            self._callback.name = f"eval_{eval_case.id}"

        return config

    def get_results(self) -> list[dict]:
        """获取 deepeval metric 评分结果"""
        results = []
        for metric in self._metrics:
            results.append({
                "metric": metric.__class__.__name__,
                "score": getattr(metric, "score", None),
                "reason": getattr(metric, "reason", None),
                "passed": getattr(metric, "is_successful", lambda: None)(),
            })
        return results
