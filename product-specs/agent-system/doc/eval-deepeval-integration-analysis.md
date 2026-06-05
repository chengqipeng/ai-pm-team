# Agent-System 集成本地部署 DeepEval 深度分析

> 基于 DeepAgent 现有评测体系（Tool 评测 + Memory 评测 + Agent 评测 Promptfoo 方案），分析如何引入 deepeval 框架进行本地化部署集成，补充 LLM-as-Judge 语义评测能力和合成测试数据生成能力。

---

## 一、现状分析：已有能力 vs deepeval 能力对照

### 1.1 DeepAgent 现有评测基础设施

| 模块 | 位置 | 能力 | 局限 |
|------|------|------|------|
| ToolEvalRunner | `src/eval/tool_eval_runner.py` | 工具功能正确性断言（equals/contains/regex/json_path/side_effect） | 无 LLM-as-Judge 语义评测 |
| MemoryEvalRunner | `src/eval/memory_eval_runner.py` | 五层记忆评测（召回率/时间衰减/上下文匹配） | 评测数据手动维护，无自动生成 |
| MockToolGateway | `src/eval/mock_gateway.py`（设计中） | 工具拦截 + 条件匹配 + 状态模拟 | 尚未集成 LLM Judge 断言 |
| AssertionEngine | `agent-eval-system-design.md`（设计中） | 11 类断言包含 llm_judge | 自研 LLM Judge 缺乏标准化 Metric 积累 |
| Mock 数据生成 | `eval-mock-data-auto-generation.md`（设计中） | 录制回放 + 预置模板 + AI 辅助 | 无标准化 Synthesizer |

### 1.2 deepeval 可补充的能力

| deepeval 能力 | 对应需求 | 集成价值 |
|---------------|---------|---------|
| **LLM-as-Judge Metrics** (G-Eval/DAG/AnswerRelevancy/Faithfulness/TaskCompletion) | Agent 评测中的语义质量验证 | ★★★★★ 替代自研 LLM Judge，标准化评分 |
| **Agentic Metrics** (ToolCorrectness/ToolUse/AgenticReasonability) | Agent 评测中的工具选择/参数/推理链验证 | ★★★★★ 与现有 Agent 评测方案直接互补 |
| **Synthesizer** (从文档/上下文/零起生成测试集) | 评测用例自动生成 | ★★★★ 补充 Mock 数据生成方案 |
| **ConversationSimulator** (多轮对话模拟) | 多轮对话场景评测 | ★★★ 补充端到端评测 |
| **Custom Metrics** (自定义评测指标) | 特殊业务场景评测 | ★★★ 可扩展性好 |
| **Confident AI Platform** (可选) | 评测数据管理 + 可视化 | ★★ 可替代，不强依赖 |

---

## 二、集成架构设计

### 2.1 整体定位：deepeval 作为评测引擎的"语义评测层"

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         Agent-System 评测体系（集成后）                            │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                   │
│  ┌─── 第一层：确定性断言（现有） ─────────────────────────────────────────────┐  │
│  │  ToolEvalRunner — equals / contains / regex / json_path / side_effect       │  │
│  │  MemoryEvalRunner — recall@k / precision@k / MRR / top1_hit               │  │
│  │  Agent AssertionEngine — tool_call_check / sequence_check / state_diff     │  │
│  └─────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                   │
│  ┌─── 第二层：LLM-as-Judge 语义评测（deepeval 集成） ──────────────────────────┐  │
│  │  GEval — 任意自定义 criteria 的 LLM 评分                                    │  │
│  │  AnswerRelevancy — 回复与问题的相关性                                        │  │
│  │  Faithfulness — 回复与上下文的忠实度                                         │  │
│  │  TaskCompletion — Agent 端到端任务完成度                                     │  │
│  │  ToolCorrectness — 工具选择正确性                                            │  │
│  │  ToolUse — 工具使用合理性（参数 + 选择）                                     │  │
│  └─────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                   │
│  ┌─── 第三层：合成数据生成（deepeval Synthesizer） ────────────────────────────┐  │
│  │  generate_goldens_from_docs — 从 Skill prompt/工具文档生成测试用例           │  │
│  │  generate_goldens_from_contexts — 从环境快照数据生成测试场景                  │  │
│  │  generate_goldens_from_scratch — 从场景描述零起生成                           │  │
│  │  ConversationSimulator — 多轮对话自动模拟生成                                │  │
│  └─────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 技术集成架构

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          本地部署架构                                              │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                   │
│  ┌────────────────────────────────────────────────┐                              │
│  │     DeepAgent EvalRunner (现有)                 │                              │
│  │                                                 │                              │
│  │  1. 构建 Agent（AgentFactory）                  │                              │
│  │  2. 注入 MockToolGateway                        │                              │
│  │  3. 执行对话 → 采集 EvalEvidence                │                              │
│  │  4. 确定性断言 → AssertionEngine                │                              │
│  │          │                                      │                              │
│  │          │ EvalEvidence                         │                              │
│  │          ▼                                      │                              │
│  │  5. 语义评测 → DeepEvalAdapter ────────────┐    │                              │
│  └─────────────────────────────────────────────┼───┘                              │
│                                                │                                   │
│                                                ▼                                   │
│  ┌────────────────────────────────────────────────┐                              │
│  │      DeepEvalAdapter (新增桥接层)               │                              │
│  │                                                 │                              │
│  │  • EvalEvidence → LLMTestCase 转换             │                              │
│  │  • EvalEvidence → ConversationalTestCase 转换  │                              │
│  │  • Metric 实例化 + 执行                         │                              │
│  │  • 结果 → EvalVerdict 回写                      │                              │
│  └──────────────────────┬─────────────────────────┘                              │
│                         │                                                         │
│                         ▼                                                         │
│  ┌────────────────────────────────────────────────┐                              │
│  │      deepeval (pip install deepeval)            │                              │
│  │                                                 │                              │
│  │  ┌──────────────┐  ┌──────────────────────┐   │                              │
│  │  │ Metrics      │  │ Synthesizer          │   │                              │
│  │  │ • GEval      │  │ • from_docs          │   │                              │
│  │  │ • ToolUse    │  │ • from_contexts      │   │                              │
│  │  │ • TaskCompl. │  │ • from_scratch       │   │                              │
│  │  │ • Faithful.  │  │ • from_goldens       │   │                              │
│  │  └──────┬───────┘  └──────────────────────┘   │                              │
│  │         │                                       │                              │
│  │         ▼                                       │                              │
│  │  ┌──────────────────────────┐                  │                              │
│  │  │ DeepSeekJudge            │                  │                              │
│  │  │ (DeepEvalBaseLLM 实现)   │                  │                              │
│  │  │                          │                  │                              │
│  │  │ model: DeepSeek V3/R1    │                  │                              │
│  │  │ endpoint: tokenhub       │                  │                              │
│  │  │ 或本地 Ollama 部署       │                  │                              │
│  │  └──────────────────────────┘                  │                              │
│  └────────────────────────────────────────────────┘                              │
│                                                                                   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 三、核心集成点详细设计

### 3.1 自定义 LLM Judge — DeepSeekJudge

DeepAgent 使用 DeepSeek 模型（通过 tokenhub.tencentmaas.com OpenAI-compatible API），需要实现 `DeepEvalBaseLLM` 适配器：

```python
# src/eval/deepeval_adapter/deepseek_judge.py

import json
from typing import Optional
from pydantic import BaseModel
from openai import AsyncOpenAI
from deepeval.models import DeepEvalBaseLLM


class DeepSeekJudge(DeepEvalBaseLLM):
    """基于 DeepSeek 的 deepeval Judge 模型
    
    支持两种部署模式：
    1. 远程 API（tokenhub.tencentmaas.com）— 默认
    2. 本地 Ollama 部署 — 纯离线环境
    """

    def __init__(
        self,
        model_name: str = "deepseek-v3",
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        self._model_name = model_name
        self._api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        self._base_url = base_url or os.environ.get(
            "DEEPEVAL_JUDGE_BASE_URL",
            "https://tokenhub.tencentmaas.com/v1"
        )
        self._client = AsyncOpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
        )

    def load_model(self):
        return self._client

    def get_model_name(self) -> str:
        return f"DeepSeek-Judge ({self._model_name})"

    def generate(self, prompt: str, schema: Optional[BaseModel] = None) -> str | BaseModel:
        """同步生成（deepeval 要求实现）"""
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, self.a_generate(prompt, schema)).result()
        return asyncio.run(self.a_generate(prompt, schema))

    async def a_generate(self, prompt: str, schema: Optional[BaseModel] = None) -> str | BaseModel:
        """异步生成 — deepeval 主要使用此方法"""
        messages = [{"role": "user", "content": prompt}]
        
        kwargs = {
            "model": self._model_name,
            "messages": messages,
            "temperature": 0.0,  # Judge 需要确定性输出
            "max_tokens": 4096,
        }

        # 如果需要结构化输出（JSON Schema 约束）
        if schema is not None:
            kwargs["response_format"] = {
                "type": "json_object"
            }
            # 在 prompt 末尾追加 schema 约束
            schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
            messages[0]["content"] += (
                f"\n\nYou MUST respond with a valid JSON that conforms to this schema:\n"
                f"```json\n{schema_json}\n```"
            )

        response = await self._client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content

        if schema is not None:
            parsed = json.loads(content)
            return schema(**parsed)
        
        return content
```

### 3.2 EvalEvidence → deepeval TestCase 转换

```python
# src/eval/deepeval_adapter/converter.py

from deepeval.test_case import LLMTestCase, ConversationalTestCase, Turn
from deepeval.test_case import ToolCall as DeepEvalToolCall

from src.eval.evidence import EvalEvidence


class EvidenceToTestCaseConverter:
    """将 DeepAgent 的 EvalEvidence 转换为 deepeval 的 TestCase"""

    @staticmethod
    def to_llm_test_case(
        evidence: EvalEvidence,
        input_message: str,
        expected_output: str | None = None,
        context: list[str] | None = None,
        retrieval_context: list[str] | None = None,
    ) -> LLMTestCase:
        """单轮评测 — 转换为 LLMTestCase"""
        
        # 提取工具调用记录，转为 deepeval 格式
        tools_called = []
        for call in evidence.tool_calls:
            tools_called.append(DeepEvalToolCall(
                name=call.tool_name,
                input_parameters=call.arguments,
                output=str(call.response) if call.response else None,
            ))

        return LLMTestCase(
            input=input_message,
            actual_output=evidence.final_response,
            expected_output=expected_output,
            context=context,
            retrieval_context=retrieval_context,
            tools_called=tools_called,
            # 可选：expected_tools 用于 ToolCorrectness metric
        )

    @staticmethod
    def to_conversational_test_case(
        evidence: EvalEvidence,
        conversation_history: list[dict],
    ) -> ConversationalTestCase:
        """多轮评测 — 转换为 ConversationalTestCase"""
        turns = []
        for msg in conversation_history:
            turn = Turn(
                role=msg["role"],
                content=msg["content"],
            )
            # 如果是 assistant 回复且包含工具调用
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                turn.tools_called = [
                    DeepEvalToolCall(
                        name=tc["name"],
                        input_parameters=tc.get("arguments", {}),
                        output=tc.get("result"),
                    )
                    for tc in msg["tool_calls"]
                ]
            turns.append(turn)
        
        return ConversationalTestCase(turns=turns)
```

### 3.3 DeepEvalMetricAdapter — 桥接断言引擎

```python
# src/eval/deepeval_adapter/metric_adapter.py

from deepeval.metrics import (
    GEval,
    AnswerRelevancyMetric,
    FaithfulnessMetric,
    TaskCompletionMetric,
    ToolCorrectnessMetric,
)
from deepeval.test_case import LLMTestCase, SingleTurnParams

from src.eval.evidence import EvalEvidence
from src.eval.deepeval_adapter.deepseek_judge import DeepSeekJudge
from src.eval.deepeval_adapter.converter import EvidenceToTestCaseConverter


class DeepEvalMetricAdapter:
    """将 deepeval metrics 适配到 DeepAgent AssertionEngine 中
    
    使用方式：
        adapter = DeepEvalMetricAdapter()
        result = await adapter.evaluate_semantic_quality(evidence, eval_case)
    """

    def __init__(self, judge_model: DeepSeekJudge | None = None):
        self._judge = judge_model or DeepSeekJudge()

    async def evaluate_answer_relevancy(
        self,
        evidence: EvalEvidence,
        input_message: str,
        threshold: float = 0.7,
    ) -> dict:
        """回复相关性评测"""
        test_case = EvidenceToTestCaseConverter.to_llm_test_case(
            evidence=evidence,
            input_message=input_message,
        )
        metric = AnswerRelevancyMetric(
            model=self._judge,
            threshold=threshold,
        )
        metric.measure(test_case)
        return {
            "metric": "answer_relevancy",
            "score": metric.score,
            "reason": metric.reason,
            "passed": metric.is_successful(),
            "threshold": threshold,
        }

    async def evaluate_task_completion(
        self,
        evidence: EvalEvidence,
        input_message: str,
        expected_tools: list[str] | None = None,
        threshold: float = 0.7,
    ) -> dict:
        """Agent 任务完成度评测"""
        test_case = EvidenceToTestCaseConverter.to_llm_test_case(
            evidence=evidence,
            input_message=input_message,
        )
        if expected_tools:
            test_case.expected_tools = expected_tools
            
        metric = TaskCompletionMetric(
            model=self._judge,
            threshold=threshold,
        )
        metric.measure(test_case)
        return {
            "metric": "task_completion",
            "score": metric.score,
            "reason": metric.reason,
            "passed": metric.is_successful(),
            "threshold": threshold,
        }

    async def evaluate_tool_correctness(
        self,
        evidence: EvalEvidence,
        input_message: str,
        expected_tools: list[str],
        threshold: float = 0.7,
    ) -> dict:
        """工具选择正确性评测"""
        test_case = EvidenceToTestCaseConverter.to_llm_test_case(
            evidence=evidence,
            input_message=input_message,
        )
        test_case.expected_tools = expected_tools
        
        metric = ToolCorrectnessMetric(
            model=self._judge,
            threshold=threshold,
        )
        metric.measure(test_case)
        return {
            "metric": "tool_correctness",
            "score": metric.score,
            "reason": metric.reason,
            "passed": metric.is_successful(),
            "threshold": threshold,
        }

    async def evaluate_custom_criteria(
        self,
        evidence: EvalEvidence,
        input_message: str,
        criteria: str,
        metric_name: str = "custom",
        threshold: float = 0.5,
    ) -> dict:
        """自定义 G-Eval criteria 评测（最灵活）"""
        test_case = EvidenceToTestCaseConverter.to_llm_test_case(
            evidence=evidence,
            input_message=input_message,
        )
        metric = GEval(
            name=metric_name,
            model=self._judge,
            criteria=criteria,
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
            ],
            threshold=threshold,
        )
        metric.measure(test_case)
        return {
            "metric": metric_name,
            "score": metric.score,
            "reason": metric.reason,
            "passed": metric.is_successful(),
            "threshold": threshold,
        }
```

### 3.4 Synthesizer 集成 — 评测用例自动生成

```python
# src/eval/deepeval_adapter/synthesizer_adapter.py

from deepeval.synthesizer import Synthesizer
from deepeval.synthesizer.config import (
    StylingConfig, EvolutionConfig, FiltrationConfig
)
from deepeval.synthesizer import Evolution

from src.eval.deepeval_adapter.deepseek_judge import DeepSeekJudge


class AgentTestSynthesizer:
    """基于 deepeval Synthesizer 为 Agent 评测自动生成测试集
    
    三种生成模式：
    1. 从 Skill prompt + 工具描述文档生成 → generate_from_skill_docs()
    2. 从环境快照数据生成 → generate_from_snapshot()  
    3. 从场景描述零起生成 → generate_from_scenario()
    """

    def __init__(self, judge_model: DeepSeekJudge | None = None):
        self._judge = judge_model or DeepSeekJudge()

    def generate_from_skill_docs(
        self,
        document_paths: list[str],
        num_goldens: int = 20,
        task: str | None = None,
        scenario: str | None = None,
    ) -> list[dict]:
        """从 Skill prompt 文档 + 工具 schema 文档生成测试用例
        
        适合场景：
        - Skill 新建后快速生成回归用例
        - 工具文档变更后刷新测试集
        
        Args:
            document_paths: Skill prompt 文件、工具 schema YAML 等
            num_goldens: 生成数量
            task: Agent 的任务描述（如"CRM 订单管理助手"）
            scenario: 使用场景描述
        """
        styling = StylingConfig(
            input_format="用户向 CRM Agent 提出的自然语言请求",
            expected_output_format="Agent 应该执行的操作描述或回复内容",
            task=task or "处理用户的 CRM 业务请求，选择正确工具执行操作",
            scenario=scenario or "企业 CRM 系统中，用户通过自然语言与 Agent 交互",
        )
        
        evolution_config = EvolutionConfig(
            evolutions={
                Evolution.REASONING: 1/4,       # 需要推理的复杂场景
                Evolution.MULTICONTEXT: 1/4,    # 涉及多个数据源
                Evolution.CONCRETIZING: 1/4,    # 具体化的用户请求
                Evolution.CONSTRAINED: 1/4,     # 有约束条件的场景
            },
            num_evolutions=2,
        )

        filtration_config = FiltrationConfig(
            critic_model=self._judge,
            synthetic_input_quality_threshold=0.6,
            max_quality_retries=2,
        )

        synthesizer = Synthesizer(
            model=self._judge,
            styling_config=styling,
            evolution_config=evolution_config,
            filtration_config=filtration_config,
        )

        goldens = synthesizer.generate_goldens_from_docs(
            document_paths=document_paths,
            include_expected_output=True,
            max_goldens_per_context=num_goldens,
        )

        # 转换为 DeepAgent EvalCase 格式
        return self._goldens_to_eval_cases(goldens)

    def generate_from_scenario(
        self,
        scenario_description: str,
        num_goldens: int = 10,
    ) -> list[dict]:
        """从自然语言场景描述生成（无需文档）
        
        适合场景：
        - 租户快速生成自定义场景测试
        - AI 辅助生成（对接 eval-mock-data-auto-generation.md 的"方式三"）
        """
        styling = StylingConfig(
            input_format="用户向 CRM Agent 发出的自然语言指令",
            expected_output_format="Agent 执行结果的文字描述",
            task="处理 CRM 业务场景中的用户请求",
            scenario=scenario_description,
        )

        synthesizer = Synthesizer(
            model=self._judge,
            styling_config=styling,
        )

        goldens = synthesizer.generate_goldens_from_scratch(
            subject=scenario_description,
            num_goldens=num_goldens,
            include_expected_output=True,
        )

        return self._goldens_to_eval_cases(goldens)

    def _goldens_to_eval_cases(self, goldens) -> list[dict]:
        """将 deepeval Golden 转为 DeepAgent EvalCase 格式"""
        cases = []
        for i, golden in enumerate(goldens):
            case = {
                "id": f"synth_{i:03d}",
                "input": golden.input,
                "expected_output": golden.expected_output,
                "context": golden.context if golden.context else None,
                "source": "deepeval_synthesizer",
                "quality_score": golden.quality_score,
                "complexity_score": golden.complexity_score,
                # 以下字段需用户确认后补充
                "assertions": [],  # 待用户配置
                "execution_mode": "hybrid",  # 默认 hybrid
                "mock_dataset_id": None,  # 待关联
            }
            cases.append(case)
        return cases
```

---

## 四、本地部署方案

### 4.1 部署拓扑

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  本地部署环境                                                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                   │
│  方案 A: 远程 API Judge（推荐，轻量）                                            │
│  ─────────────────────────────────────                                           │
│                                                                                   │
│  ┌─────────────────┐          ┌──────────────────────────────┐                  │
│  │ DeepAgent        │  HTTP    │ tokenhub.tencentmaas.com     │                  │
│  │ + deepeval       │ ───────→ │ DeepSeek V3 / R1             │                  │
│  │ (本机 Python)    │          │ (OpenAI-Compatible API)      │                  │
│  └─────────────────┘          └──────────────────────────────┘                  │
│                                                                                   │
│  优势: 零运维，模型能力强                                                         │
│  限制: 需要网络连通，有 API 调用成本                                              │
│                                                                                   │
│  ═══════════════════════════════════════════════════════════════════════════════  │
│                                                                                   │
│  方案 B: 完全本地离线 Judge（纯内网环境）                                         │
│  ─────────────────────────────────────────                                       │
│                                                                                   │
│  ┌─────────────────┐          ┌──────────────────────────────┐                  │
│  │ DeepAgent        │  HTTP    │ Ollama / vLLM                │                  │
│  │ + deepeval       │ ───────→ │ Qwen2.5-72B / DeepSeek-V3   │                  │
│  │ (本机 Python)    │ localhost│ (本地 GPU 推理)              │                  │
│  └─────────────────┘          └──────────────────────────────┘                  │
│                                                                                   │
│  优势: 完全离线，无数据外泄风险                                                   │
│  限制: 需要 GPU 资源（建议 A100 80G+ 运行 70B 模型）                              │
│  配置: DEEPEVAL_JUDGE_BASE_URL=http://localhost:11434/v1                          │
│                                                                                   │
│  ═══════════════════════════════════════════════════════════════════════════════  │
│                                                                                   │
│  方案 C: 混合模式（推荐生产环境）                                                 │
│  ──────────────────────────────────                                              │
│                                                                                   │
│  ┌─────────────────┐     ┌──────────────────┐     ┌──────────────────────────┐  │
│  │ DeepAgent        │────→│ Model Router     │────→│ DeepSeek API (语义评测)   │  │
│  │ + deepeval       │     │ (按场景路由)      │     │ 本地 Qwen (简单断言)      │  │
│  └─────────────────┘     └──────────────────┘     └──────────────────────────┘  │
│                                                                                   │
│  路由策略:                                                                        │
│    GEval/TaskCompletion → 强模型（DeepSeek V3/R1）                               │
│    AnswerRelevancy/简单判断 → 本地小模型（Qwen2.5-14B）                           │
│                                                                                   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 依赖安装

```toml
# pyproject.toml 新增依赖
[tool.poetry.dependencies]
deepeval = "^4.0"           # deepeval 核心框架
# instructor = "^1.0"      # 可选：JSON 约束增强（DeepSeek 本身支持 JSON Mode 可不装）
```

```bash
# 安装
poetry add deepeval

# 验证
poetry run python -c "from deepeval.metrics import GEval; print('deepeval OK')"
```

### 4.3 环境变量配置

```bash
# .env 文件追加

# ── deepeval Judge 模型配置 ──
# 默认使用与 Agent 相同的 DeepSeek 端点
DEEPEVAL_JUDGE_BASE_URL=https://tokenhub.tencentmaas.com/v1
DEEPEVAL_JUDGE_MODEL=deepseek-v3
# DEEPEVAL_JUDGE_API_KEY 不设置则沿用 DEEPSEEK_API_KEY

# 本地部署时切换为:
# DEEPEVAL_JUDGE_BASE_URL=http://localhost:11434/v1
# DEEPEVAL_JUDGE_MODEL=qwen2.5:72b

# ── deepeval 框架配置 ──
DEEPEVAL_DISABLE_DOTENV=0              # 允许 deepeval 读 .env
DEEPEVAL_TELEMETRY_OPT_OUT=YES         # 禁用遥测（本地部署必须）
# CONFIDENT_AI_API_KEY=               # 不配置 = 纯本地模式，不连 Confident AI 云平台
```

---

## 五、与现有评测模块的集成点

### 5.1 集成到 AssertionEngine（llm_judge 断言类型）

现有 `agent-eval-system-design.md` 中已设计了 `llm_judge` 断言类型，deepeval 可直接替换自研实现：

```python
# src/eval/assertions/llm_judge_strategy.py — 替换实现

class LlmJudgeStrategy(AssertionStrategy):
    """LLM Judge 断言 — 使用 deepeval GEval 实现
    
    替代原方案中自研的 LLM 评分逻辑，获得:
    1. 标准化评分流程（Chain-of-Thought + 评分归一化）
    2. 更好的评分一致性（deepeval 内置的 prompt 工程）
    3. 可复现性（相同输入相同模型产生稳定评分）
    """

    def __init__(self, judge_model: DeepSeekJudge | None = None):
        self._adapter = DeepEvalMetricAdapter(judge_model=judge_model)

    async def evaluate(
        self,
        evidence: EvalEvidence,
        config: dict,
    ) -> AssertionResult:
        """
        config 示例:
        {
            "criteria": [
                {"name": "correctness", "weight": 2.0, "rubric": "..."},
                {"name": "helpfulness", "weight": 1.0, "rubric": "..."},
            ],
            "pass_threshold": 3.5,
            "num_judges": 3,
        }
        """
        scores = []
        reasons = []

        for criterion in config["criteria"]:
            result = await self._adapter.evaluate_custom_criteria(
                evidence=evidence,
                input_message=evidence.input_message,
                criteria=criterion["rubric"],
                metric_name=criterion["name"],
                threshold=0.0,  # 不在单维度阈值，用加权总分判断
            )
            weighted_score = result["score"] * criterion["weight"]
            scores.append(weighted_score)
            reasons.append(f'{criterion["name"]}: {result["score"]:.2f} — {result["reason"]}')

        total_score = sum(scores)
        total_weight = sum(c["weight"] for c in config["criteria"])
        normalized_score = total_score / total_weight * 5  # 归一化到 0-5

        passed = normalized_score >= config.get("pass_threshold", 3.5)
        
        return AssertionResult(
            passed=passed,
            score=normalized_score,
            details="\n".join(reasons),
            confidence=0.85 if passed else 0.75,  # LLM Judge 置信度
        )
```

### 5.2 集成到 Tool 评测（补充语义断言）

```python
# src/eval/tool_eval_runner.py — 扩展断言类型

# 新增断言类型
class AssertionType(str, Enum):
    # ... 现有类型 ...
    SEMANTIC_MATCH = "semantic_match"    # deepeval 语义匹配
    ANSWER_RELEVANCY = "answer_relevancy"  # deepeval 回复相关性


# 在 ToolEvalRunner 中增加 deepeval 断言处理
class ToolEvalRunner:
    def __init__(self):
        self._deepeval_adapter = None  # 懒加载

    @property
    def deepeval_adapter(self):
        if self._deepeval_adapter is None:
            from src.eval.deepeval_adapter.metric_adapter import DeepEvalMetricAdapter
            self._deepeval_adapter = DeepEvalMetricAdapter()
        return self._deepeval_adapter

    async def _check_semantic_assertion(self, assertion, result) -> bool:
        """使用 deepeval GEval 进行语义断言"""
        # 将 ToolResult 包装为 EvalEvidence
        evidence = EvalEvidence(
            final_response=str(result.content),
            tool_calls=[],
        )
        eval_result = await self.deepeval_adapter.evaluate_custom_criteria(
            evidence=evidence,
            input_message=assertion.description or "tool output validation",
            criteria=assertion.expected,  # criteria 作为 expected 字段传入
            threshold=0.7,
        )
        return eval_result["passed"]
```

### 5.3 集成到 Synthesizer — 补充 Mock 数据生成

与现有 `eval-mock-data-auto-generation.md` 的"方式三：AI 辅助生成"对接：

```python
# src/eval/mock_generator.py — 扩展 AI 辅助生成

class MockDatasetGenerator:
    """从录制数据 / 预置模板 / AI 辅助生成 MockDataset"""

    def generate_from_ai_description(
        self,
        scenario_description: str,
        skill_api_key: str,
        num_cases: int = 10,
    ) -> list[dict]:
        """方式三增强版：使用 deepeval Synthesizer 生成更高质量的测试用例
        
        对比原方案（纯 LLM 推导）的优势：
        1. Evolution 机制使生成的用例覆盖更多复杂度层级
        2. Filtration 机制保证用例质量
        3. 可结合文档（Skill prompt）生成有上下文依据的用例
        """
        from src.eval.deepeval_adapter.synthesizer_adapter import AgentTestSynthesizer
        
        synth = AgentTestSynthesizer()
        
        # 尝试获取 Skill 相关文档
        skill_docs = self._get_skill_documents(skill_api_key)
        
        if skill_docs:
            # 有文档 → 从文档生成（更精准）
            return synth.generate_from_skill_docs(
                document_paths=skill_docs,
                num_goldens=num_cases,
                scenario=scenario_description,
            )
        else:
            # 无文档 → 从场景描述生成
            return synth.generate_from_scenario(
                scenario_description=scenario_description,
                num_goldens=num_cases,
            )
```

---

## 六、关键技术难点与解决方案

### 6.1 DeepSeek JSON Mode 兼容性

**问题**: deepeval 的 metrics 需要 LLM 输出结构化 JSON（schema 约束），DeepSeek API 的 `response_format=json_object` 支持程度需验证。

**解决方案**:

```python
# 方案 1: DeepSeek 原生 JSON Mode（首选）
# tokenhub 的 DeepSeek V3 支持 response_format={"type": "json_object"}
# 在 prompt 中追加 schema 描述即可

# 方案 2: 后处理修复（降级方案）
import json
import re

def repair_json(raw_output: str) -> dict:
    """修复 LLM 输出的不完整 JSON"""
    # 提取 JSON 块
    match = re.search(r'\{[\s\S]*\}', raw_output)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            # 尝试修复常见问题
            fixed = match.group()
            fixed = re.sub(r',\s*}', '}', fixed)  # 尾逗号
            fixed = re.sub(r',\s*]', ']', fixed)  # 尾逗号
            return json.loads(fixed)
    raise ValueError(f"Cannot parse JSON from: {raw_output[:200]}")

# 方案 3: 使用 instructor 库强制约束（备选）
# pip install instructor
# instructor.from_openai(client, mode=instructor.Mode.JSON)
```

### 6.2 异步执行兼容性

**问题**: DeepAgent 的 eval 体系是 `asyncio` 驱动的，deepeval 的部分 API（`metric.measure()`）是同步的。

**解决方案**:

```python
# deepeval 支持 async 版本
# 方式 1: 使用 a_measure（deepeval 4.0+ 支持）
await metric.a_measure(test_case)

# 方式 2: 使用 evaluate() 的 async_mode 参数
from deepeval import evaluate
results = evaluate(
    test_cases=[test_case],
    metrics=[metric],
    run_async=True,  # 启用异步执行
)

# 方式 3: 在 asyncio event loop 中安全调用同步 API
import asyncio
result = await asyncio.to_thread(metric.measure, test_case)
```

### 6.3 成本控制

**问题**: LLM-as-Judge 每次评测都调用 LLM，大量评测用例的 API 成本可能很高。

**解决方案**:

| 策略 | 实现方式 | 预期效果 |
|------|---------|---------|
| 分层评测 | 确定性断言优先，只对 UNCERTAIN 用例走 LLM Judge | 减少 60-70% LLM 调用 |
| 批量执行 | `deepeval evaluate()` 批量执行，共享 context 窗口 | 减少 prompt 重复 |
| 缓存 | 相同 input+output+criteria 的评测结果缓存 7 天 | 重复执行零成本 |
| 模型分层 | 简单判断用小模型，复杂语义用大模型 | 降低 50%+ 成本 |
| cost_tracking | `Synthesizer(cost_tracking=True)` 监控生成成本 | 透明可控 |

```python
# 实现评测结果缓存
import hashlib

class CachedDeepEvalAdapter(DeepEvalMetricAdapter):
    """带缓存的评测适配器"""
    
    def _cache_key(self, metric_name, input_msg, output, criteria) -> str:
        content = f"{metric_name}:{input_msg}:{output}:{criteria}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    async def evaluate_custom_criteria(self, evidence, input_message, criteria, **kwargs):
        key = self._cache_key("geval", input_message, evidence.final_response, criteria)
        cached = await self._cache.get(key)
        if cached:
            return cached
        result = await super().evaluate_custom_criteria(
            evidence, input_message, criteria, **kwargs
        )
        await self._cache.set(key, result, ttl=7*86400)
        return result
```

### 6.4 离线/内网部署的 Telemetry 问题

**问题**: deepeval 默认会发送遥测数据到 Confident AI。

**解决方案**:

```bash
# 方法 1: 环境变量禁用
export DEEPEVAL_TELEMETRY_OPT_OUT=YES

# 方法 2: 代码级禁用
import deepeval
deepeval.telemetry.disable()

# 方法 3: 不配置 CONFIDENT_AI_API_KEY（不登录即不连云端）
# deepeval 纯本地模式不需要任何注册或 API Key
```

---

## 七、实施路径

### Phase 1: 基础集成（1-2 周）

```
✅ 安装 deepeval 依赖
✅ 实现 DeepSeekJudge（DeepEvalBaseLLM 适配器）
✅ 实现 EvidenceToTestCaseConverter
✅ 实现 DeepEvalMetricAdapter（3-5 个核心 metric）
✅ 替换 AssertionEngine 中的 llm_judge 策略
✅ 编写集成测试验证端到端链路
```

### Phase 2: Synthesizer 集成（1 周）

```
✅ 实现 AgentTestSynthesizer
✅ 与 eval-mock-data-auto-generation.md 的"AI 辅助生成"对接
✅ Skill 文档 → 测试用例的自动生成流程打通
✅ 生成结果 → EvalCase 格式转换 + 用户确认流程
```

### Phase 3: Agent 评测增强（1-2 周）

```
✅ 集成 ToolCorrectnessMetric / ToolUseMetric
✅ 集成 TaskCompletionMetric
✅ 多轮对话评测（ConversationalTestCase）
✅ Agent 评测报告增加 deepeval 语义评分维度
```

### Phase 4: 生产化（1 周）

```
✅ 评测结果缓存机制
✅ 成本监控 + 报警
✅ CI/CD 集成（pytest + deepeval test run）
✅ 评测报告持久化 + 历史对比
```

---

## 八、与 Promptfoo 方案的关系

| 维度 | Promptfoo 方案 | deepeval 方案 | 关系 |
|------|---------------|--------------|------|
| 定位 | 三维评测框架（Tool/Memory/Agent） | LLM-as-Judge + 合成数据 | **互补，非替代** |
| Provider 层 | Tool/Memory/Agent Provider | 不涉及 Provider 概念 | deepeval 在 Provider 下游 |
| 断言引擎 | 确定性断言 + 自研 LLM Judge | deepeval metrics 替换 LLM Judge | deepeval 增强断言能力 |
| Mock 机制 | MockToolGateway 全链路 Mock | 不涉及 Mock | Mock 层独立于 deepeval |
| 数据生成 | 手动 + 录制 + 预置模板 + AI 辅助 | Synthesizer 标准化生成 | deepeval 增强 AI 辅助 |
| 执行方式 | EvalRunner + 自定义调度 | pytest / evaluate() | 可共存 |

**集成关系图**：

```
┌─── Promptfoo 三维框架（整体编排） ─────────────────────────────────┐
│                                                                     │
│  EvalRunner → Agent 执行 → EvalEvidence                            │
│       │                                                             │
│       ├── 确定性断言（tool_call_check / contains / regex）          │
│       │                                                             │
│       └── LLM Judge 断言 ──→ DeepEvalAdapter ──→ deepeval metrics  │
│                                                                     │
│  Synthesizer（用例生成）──→ AgentTestSynthesizer ──→ deepeval SDK   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 九、总结与建议

### 核心结论

1. **deepeval 作为"语义评测引擎"嵌入现有体系**，不替代 Promptfoo 方案的整体框架，而是增强 LLM Judge 和数据生成层。

2. **本地部署完全可行**，deepeval 是纯 Python 库，不依赖任何云服务（不配置 Confident AI Key 即为纯本地模式）。Judge 模型复用现有 DeepSeek 端点。

3. **集成改动最小化**：仅新增 `src/eval/deepeval_adapter/` 目录，不修改现有 ToolEvalRunner / MemoryEvalRunner 核心逻辑。

4. **推荐 `main` 分支**的最新稳定版（当前 4.0+），Synthesizer 和 Agentic Metrics 功能在 main 分支已完全稳定。

### 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| DeepSeek JSON Mode 不稳定 | 部分 metric 解析失败 | 后处理修复 + 重试 + 降级到 plain text 评分 |
| LLM Judge 成本膨胀 | 评测预算超支 | 分层策略 + 缓存 + 小模型路由 |
| deepeval 版本升级 breaking change | 适配代码失效 | 锁定版本 + 适配层隔离 |
| 离线环境无法 pip install | 部署阻塞 | 提前打包 wheel + 内部 PyPI mirror |
