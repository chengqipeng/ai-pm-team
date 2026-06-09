"""DeepEval 集成模块 — 将 DeepAgent (LangGraph) 与 deepeval 评测框架对接

集成原理：
    DeepAgent 使用 LangGraph (CompiledStateGraph)，执行通过:
      - agent.astream_events({"messages": msgs}, config=config)  # 流式
      - agent.ainvoke({"messages": msgs}, config=config)          # 同步

    deepeval 通过 LangChain CallbackHandler 原生支持 LangGraph:
      config["callbacks"] = [CallbackHandler(metrics=[...])]
    传入后自动追踪整条链路（Graph Node → LLM Call → Tool Call）。

集成方式（按侵入度从低到高）：
    方式 1: 独立评测脚本 — 不修改 server.py，独立构建 Agent 跑评测
    方式 2: 评测模式开关 — 在 config 中注入 callback（仅评测时生效）
    方式 3: 在线 Tracing — 所有请求都注入 callback（Observability）

推荐：方式 1 用于 CI/CD 回归测试，方式 2 用于按需触发的评测 API。
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 核心工具函数
# ═══════════════════════════════════════════════════════════

def create_eval_callback(
    metrics: list[str] | None = None,
    trace_name: str = "CRM-Agent-Eval",
    thread_id: str | None = None,
    user_id: str | None = None,
):
    """创建 deepeval CallbackHandler（核心集成点）

    将此 callback 加入 config["callbacks"] 列表即可自动追踪 Agent 链路。

    Args:
        metrics: metric 名称列表 ["task_completion", "answer_relevancy", "correctness"]
        trace_name: Trace 显示名称
        thread_id: 会话 ID（用于关联）
        user_id: 用户 ID

    Returns:
        CallbackHandler 实例

    使用示例:
        callback = create_eval_callback(metrics=["task_completion"])
        config["callbacks"] = [callback]
        await agent.ainvoke({"messages": msgs}, config=config)
    """
    from deepeval.integrations.langchain import CallbackHandler

    metric_instances = _build_metrics(metrics or [])

    kwargs = {"name": trace_name}
    if metric_instances:
        kwargs["metrics"] = metric_instances
    if thread_id:
        kwargs["thread_id"] = thread_id
    if user_id:
        kwargs["user_id"] = user_id

    return CallbackHandler(**kwargs)


def _build_metrics(metric_names: list[str]) -> list:
    """根据名称构建 deepeval metric 实例"""
    from deepeval.metrics import (
        TaskCompletionMetric,
        AnswerRelevancyMetric,
        GEval,
    )
    from deepeval.test_case import SingleTurnParams

    metrics = []
    for name in metric_names:
        if name == "task_completion":
            metrics.append(TaskCompletionMetric(threshold=0.7))
        elif name == "answer_relevancy":
            metrics.append(AnswerRelevancyMetric(threshold=0.7))
        elif name in ("correctness", "g_eval"):
            metrics.append(GEval(
                name="Correctness",
                criteria="判断 Agent 是否正确理解了用户意图、调用了合理的工具、回复内容准确",
                evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
                threshold=0.5,
            ))
        elif name == "tool_correctness":
            from deepeval.metrics import ToolCorrectnessMetric
            metrics.append(ToolCorrectnessMetric(threshold=0.7))
    return metrics


# ═══════════════════════════════════════════════════════════
# 方式 1: 独立评测脚本（推荐用于 CI/CD）
# ═══════════════════════════════════════════════════════════

async def build_eval_agent():
    """构建评测专用 Agent（与 server.py 逻辑一致但隔离）

    使用模拟后端，保证评测可重复。
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

    api_key = (os.environ.get("AGENT_API_KEY")
               or os.environ.get("DEEPSEEK_API_KEY",
                                 "sk-HdY98AcN68JhtXLp8oeIATEL4PWq9rzRcCAhI8G4SOtBbtSw"))
    api_base = os.environ.get("AGENT_API_BASE", "https://tokenhub.tencentmaas.com/v1")
    model = os.environ.get("AGENT_MODEL", "deepseek-v4-flash")

    reg = ToolRegistry()
    register_crm_tools(reg, CrmSimulatedBackend())
    register_metarepo_tools(reg, MetarepoSimulatedBackend())

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
        model=model,
        api_key=api_key,
        api_base=api_base,
        tool_registry=reg,
        skill_registry=skill_reg,
        system_prompt=system_prompt,
        middlewares=middlewares,
        checkpointer=MemorySaver(),
    )
    return create_deep_agent(config)


async def run_eval(
    inputs: list[str],
    metrics: list[str] | None = None,
) -> list[dict]:
    """独立评测入口 — 构建 Agent + 逐条执行 + 返回评分

    Args:
        inputs: 用户输入列表
        metrics: 评测指标 ["task_completion", "answer_relevancy", "correctness"]

    Returns:
        每条用例的评测结果

    使用:
        results = await run_eval(
            inputs=["帮我查订单 ORD-001", "取消订单 ORD-002"],
            metrics=["task_completion"],
        )
    """
    from deepeval.integrations.langchain import CallbackHandler
    from deepeval.dataset import EvaluationDataset, Golden

    metric_instances = _build_metrics(metrics or ["task_completion"])
    goldens = [Golden(input=inp) for inp in inputs]
    dataset = EvaluationDataset(goldens=goldens)

    graph = await build_eval_agent()

    for golden in dataset.evals_iterator(metrics=metric_instances):
        thread_id = f"eval_{uuid.uuid4().hex[:8]}"
        graph.invoke(
            {"messages": [{"role": "user", "content": golden.input}]},
            config={
                "callbacks": [CallbackHandler(name="CRM-Agent-Eval")],
                "configurable": {"thread_id": thread_id},
            },
        )

    return [{"input": g.input, "status": "completed"} for g in goldens]


# ═══════════════════════════════════════════════════════════
# 方式 2: 注入到现有 server.py 的 config 中
# ═══════════════════════════════════════════════════════════

def inject_eval_callback(config: dict, eval_metrics: list[str] | None = None) -> dict:
    """将 deepeval callback 注入到现有 Agent config 中

    在 server.py 的 event_generator() 中，config 构建完成后调用此函数:

        # server.py 中的集成点
        config = {"configurable": {"thread_id": thread_id, ...}, "recursion_limit": 500}

        # 评测模式时注入（通过请求参数或环境变量控制）
        if os.environ.get("DEEPEVAL_ENABLED") == "1" or req.eval_mode:
            from src.eval.deepeval_integration import inject_eval_callback
            config = inject_eval_callback(config, eval_metrics=["task_completion"])

        async for event in agent.astream_events({"messages": messages}, config=config, version="v2"):
            ...

    Args:
        config: 现有的 Agent invoke config
        eval_metrics: 要附加的评测指标

    Returns:
        注入了 callback 的 config（原地修改并返回）
    """
    callback = create_eval_callback(
        metrics=eval_metrics,
        trace_name="CRM-Agent-Online",
        thread_id=config.get("configurable", {}).get("thread_id"),
        user_id=config.get("configurable", {}).get("user_id"),
    )

    if "callbacks" not in config:
        config["callbacks"] = []
    config["callbacks"].append(callback)

    return config


# ═══════════════════════════════════════════════════════════
# 方式 3: 与现有 EvalRunner 断言引擎协作
# ═══════════════════════════════════════════════════════════

class DeepEvalBridge:
    """桥接 deepeval 到现有 AssertionEngine 的 llm_judge 断言类型

    在 agent-eval-system-design.md 的 AssertionEngine 中：
        assertions:
          - type: llm_judge
            target: final_response
            config:
              criteria: [...]

    此 Bridge 替换自研的 LLM Judge 逻辑为 deepeval GEval：

        bridge = DeepEvalBridge()
        result = await bridge.judge(
            input_message="帮我查订单",
            actual_output="订单 ORD-001 状态为已发货",
            criteria="回复是否准确回答了用户问题",
        )
    """

    async def judge(
        self,
        input_message: str,
        actual_output: str,
        criteria: str,
        expected_output: str | None = None,
        threshold: float = 0.5,
    ) -> dict:
        """使用 deepeval GEval 进行语义评分"""
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCase, SingleTurnParams

        params = [SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT]
        if expected_output:
            params.append(SingleTurnParams.EXPECTED_OUTPUT)

        metric = GEval(
            name="LLM-Judge",
            criteria=criteria,
            evaluation_params=params,
            threshold=threshold,
        )

        test_case = LLMTestCase(
            input=input_message,
            actual_output=actual_output,
            expected_output=expected_output,
        )

        await asyncio.to_thread(metric.measure, test_case)

        return {
            "score": metric.score,
            "reason": metric.reason,
            "passed": metric.is_successful(),
            "threshold": threshold,
        }
