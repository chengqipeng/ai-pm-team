"""Skill 测试调试运行器

提供完整的 Skill 测试执行能力：
- 完整执行模式：一次性执行完毕，返回全部步骤链路
- 逐步调试模式：每步暂停，支持修改参数/Mock/跳过
- 测试用例管理：保存、回归验证

不计入 exec_count / success_count 统计。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.skills.base import SkillDefinition, SkillRegistry, SkillExecutor
from src.core.exceptions import SkillExecutionError

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════

class StepType(str, Enum):
    LLM_REASONING = "llm_reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FINAL_OUTPUT = "final_output"
    ERROR = "error"


class StepStatus(str, Enum):
    COMPLETED = "completed"
    RUNNING = "running"
    WAITING = "waiting"  # 逐步模式下等待用户确认
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class TestStep:
    """单个执行步骤"""
    step_num: int
    step_type: StepType
    status: StepStatus = StepStatus.COMPLETED
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    tool_output: str = ""
    llm_thinking: str = ""
    duration_ms: float = 0.0
    tokens: int = 0
    risk_type: str = ""  # safe / sensitive / high_risk
    error_message: str = ""

    def to_dict(self) -> dict:
        return {
            "step_num": self.step_num,
            "step_type": self.step_type.value,
            "status": self.status.value,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "tool_output": self.tool_output[:2000] if self.tool_output else "",
            "llm_thinking": self.llm_thinking[:1000] if self.llm_thinking else "",
            "duration_ms": round(self.duration_ms, 1),
            "tokens": self.tokens,
            "risk_type": self.risk_type,
            "error_message": self.error_message,
        }


@dataclass
class TestResult:
    """测试执行结果"""
    test_id: str = ""
    skill_api_key: str = ""
    status: str = "success"  # success / failed / timeout / cancelled
    steps: list[TestStep] = field(default_factory=list)
    final_output: str = ""
    total_duration_ms: float = 0.0
    total_tokens: int = 0
    total_tool_calls: int = 0
    total_llm_rounds: int = 0
    error_message: str = ""
    started_at: int = 0
    completed_at: int = 0

    def to_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "skill_api_key": self.skill_api_key,
            "status": self.status,
            "steps": [s.to_dict() for s in self.steps],
            "final_output": self.final_output[:5000],
            "total_duration_ms": round(self.total_duration_ms, 1),
            "total_tokens": self.total_tokens,
            "total_tool_calls": self.total_tool_calls,
            "total_llm_rounds": self.total_llm_rounds,
            "error_message": self.error_message,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass
class MockConfig:
    """工具 Mock 配置"""
    tool_name: str
    mock_response: str  # JSON 字符串
    enabled: bool = True


@dataclass
class TestCase:
    """测试用例"""
    id: str = ""
    skill_api_key: str = ""
    name: str = ""
    arguments: dict[str, str] = field(default_factory=dict)
    expected_keywords: list[str] = field(default_factory=list)
    excluded_keywords: list[str] = field(default_factory=list)
    expected_tools: list[str] = field(default_factory=list)
    max_duration_ms: int = 0  # 0=不限制
    mocks: list[MockConfig] = field(default_factory=list)
    last_result: str = ""  # pass / fail / not_run
    last_run_at: int = 0
    created_at: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "skill_api_key": self.skill_api_key,
            "name": self.name,
            "arguments": self.arguments,
            "expected_keywords": self.expected_keywords,
            "excluded_keywords": self.excluded_keywords,
            "expected_tools": self.expected_tools,
            "max_duration_ms": self.max_duration_ms,
            "mocks": [{"tool_name": m.tool_name, "mock_response": m.mock_response, "enabled": m.enabled} for m in self.mocks],
            "last_result": self.last_result,
            "last_run_at": self.last_run_at,
            "created_at": self.created_at,
        }


# ═══════════════════════════════════════════════════════════
# SkillTestRunner — 核心测试执行器
# ═══════════════════════════════════════════════════════════

class SkillTestRunner:
    """Skill 测试调试运行器

    支持两种模式：
    - 完整执行：一次性跑完，收集全部步骤链路
    - 逐步调试：每步暂停（通过 SSE 推送步骤，等待前端确认）

    与正式执行的区别：
    - 不计入 exec_count / success_count
    - 支持 Mock 工具返回
    - 支持逐步暂停
    - 执行日志标记为 test 类型
    """

    def __init__(self, skill_registry: SkillRegistry, agent_factory: Any = None):
        self._registry = skill_registry
        self._agent_factory = agent_factory
        # 活跃的测试会话（逐步模式）
        self._active_sessions: dict[str, dict] = {}

    async def execute_full(
        self,
        skill_api_key: str,
        arguments: dict[str, str],
        mocks: list[MockConfig] | None = None,
        tenant_id: int = 0,
    ) -> TestResult:
        """完整执行模式 — 一次性执行完毕，返回全部步骤链路"""
        test_id = f"test_{uuid.uuid4().hex[:12]}"
        result = TestResult(
            test_id=test_id,
            skill_api_key=skill_api_key,
            started_at=int(time.time() * 1000),
        )

        skill = self._registry.get(skill_api_key)
        if not skill:
            result.status = "failed"
            result.error_message = f"Skill '{skill_api_key}' 未注册或已禁用"
            result.completed_at = int(time.time() * 1000)
            return result

        start_time = time.monotonic()

        try:
            if skill.context == "inline":
                await self._execute_inline_test(skill, arguments, mocks, result)
            else:
                await self._execute_fork_test(skill, arguments, mocks, result)

            result.status = "success"
        except asyncio.TimeoutError:
            result.status = "timeout"
            result.error_message = f"执行超时（{skill.timeout_ms}ms）"
        except SkillExecutionError as e:
            result.status = "failed"
            result.error_message = str(e)
        except Exception as e:
            result.status = "failed"
            result.error_message = f"未知错误: {str(e)}"
            logger.exception("Skill test execution failed: %s", skill_api_key)

        result.total_duration_ms = (time.monotonic() - start_time) * 1000
        result.completed_at = int(time.time() * 1000)
        result.total_tool_calls = sum(1 for s in result.steps if s.step_type == StepType.TOOL_CALL)
        result.total_llm_rounds = sum(1 for s in result.steps if s.step_type == StepType.LLM_REASONING)
        result.total_tokens = sum(s.tokens for s in result.steps)

        return result

    async def _execute_inline_test(
        self,
        skill: SkillDefinition,
        arguments: dict[str, str],
        mocks: list[MockConfig] | None,
        result: TestResult,
    ) -> None:
        """inline 模式测试 — 格式化 prompt 后通过 LLM 执行"""
        formatted_prompt = skill.format_prompt(arguments)

        # Step 1: 记录 prompt 格式化
        result.steps.append(TestStep(
            step_num=1,
            step_type=StepType.LLM_REASONING,
            llm_thinking=f"Skill prompt 已格式化，准备发送给 LLM 执行...\n\n参数: {json.dumps(arguments, ensure_ascii=False)}",
            status=StepStatus.COMPLETED,
        ))

        # 如果有 agent_factory，真正执行
        if self._agent_factory is not None:
            await self._run_with_agent(skill, formatted_prompt, arguments, mocks, result)
        else:
            # 无 agent_factory 时返回格式化后的 prompt 作为预览
            result.final_output = formatted_prompt
            result.steps.append(TestStep(
                step_num=2,
                step_type=StepType.FINAL_OUTPUT,
                llm_thinking="（预览模式：未配置 AgentFactory，返回格式化后的 Prompt）",
                tool_output=formatted_prompt[:2000],
                status=StepStatus.COMPLETED,
            ))

    async def _execute_fork_test(
        self,
        skill: SkillDefinition,
        arguments: dict[str, str],
        mocks: list[MockConfig] | None,
        result: TestResult,
    ) -> None:
        """fork 模式测试 — 启动子 Agent 执行"""
        formatted_prompt = skill.format_prompt(arguments)

        # Step 1: 记录任务构建
        task_instruction = self._build_task_instruction(skill, arguments)
        result.steps.append(TestStep(
            step_num=1,
            step_type=StepType.LLM_REASONING,
            llm_thinking=f"Fork 模式：构建子 Agent 任务指令\nAgent: {skill.agent or 'default'}\n\n{task_instruction[:500]}",
            status=StepStatus.COMPLETED,
        ))

        if self._agent_factory is not None:
            await self._run_with_agent(skill, formatted_prompt, arguments, mocks, result)
        else:
            result.final_output = task_instruction
            result.steps.append(TestStep(
                step_num=2,
                step_type=StepType.FINAL_OUTPUT,
                llm_thinking="（预览模式：未配置 AgentFactory，返回任务指令预览）",
                tool_output=task_instruction[:2000],
                status=StepStatus.COMPLETED,
            ))

    async def _run_with_agent(
        self,
        skill: SkillDefinition,
        formatted_prompt: str,
        arguments: dict[str, str],
        mocks: list[MockConfig] | None,
        result: TestResult,
    ) -> None:
        """通过 AgentFactory 真正执行 Skill 并收集步骤链路"""
        from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
        from src.middleware.tracing import tracing_middleware

        agent_name = skill.agent if skill.agent else "default"
        sub_thread_id = f"test-{skill.name}-{uuid.uuid4().hex[:8]}"

        # 构建 Mock 映射
        mock_map: dict[str, str] = {}
        if mocks:
            for m in mocks:
                if m.enabled:
                    mock_map[m.tool_name] = m.mock_response

        try:
            agent = await self._agent_factory.build(agent_name, depth=0)

            # 构建任务消息
            task_instruction = self._build_task_instruction(skill, arguments)
            messages = [HumanMessage(content=task_instruction)]

            # 执行（带超时）
            agent_result = await asyncio.wait_for(
                agent.ainvoke(
                    {"messages": messages},
                    config={"configurable": {
                        "thread_id": sub_thread_id,
                        "skip_memory_extract": True,
                        "test_mode": True,
                        "mock_tools": mock_map,
                    }},
                ),
                timeout=skill.timeout_ms / 1000,
            )

            # 从 tracing 中收集执行步骤
            spans = tracing_middleware.get_spans(sub_thread_id)
            step_num = len(result.steps)

            for span in spans:
                span_type = span.get("type", "")
                span_meta = span.get("metadata", {})

                if span_type == "llm_call":
                    step_num += 1
                    result.steps.append(TestStep(
                        step_num=step_num,
                        step_type=StepType.LLM_REASONING,
                        llm_thinking=span.get("output_data", {}).get("thinking", ""),
                        duration_ms=span.get("duration_ms", 0),
                        tokens=span.get("metadata", {}).get("tokens", 0),
                        status=StepStatus.COMPLETED,
                    ))
                elif span_type == "tool_call":
                    step_num += 1
                    tool_name = span_meta.get("tool_name", "")
                    is_mocked = tool_name in mock_map
                    result.steps.append(TestStep(
                        step_num=step_num,
                        step_type=StepType.TOOL_CALL,
                        tool_name=tool_name,
                        tool_input=span.get("input_data", {}),
                        tool_output=span.get("output_data", {}).get("result", ""),
                        duration_ms=span.get("duration_ms", 0),
                        risk_type=self._get_tool_risk_type(tool_name),
                        status=StepStatus.COMPLETED,
                    ))

            # 提取最终输出
            output_messages = agent_result.get("messages", [])
            for msg in reversed(output_messages):
                if isinstance(msg, AIMessage) and msg.content:
                    content = msg.content
                    if isinstance(content, list):
                        result.final_output = "".join(
                            c.get("text", "") if isinstance(c, dict) else str(c)
                            for c in content
                        )
                    else:
                        result.final_output = str(content)
                    break

            # 添加最终输出步骤
            result.steps.append(TestStep(
                step_num=step_num + 1,
                step_type=StepType.FINAL_OUTPUT,
                tool_output=result.final_output[:2000],
                status=StepStatus.COMPLETED,
            ))

            # 清理测试 spans
            tracing_middleware.clear(sub_thread_id)

        except asyncio.TimeoutError:
            raise
        except Exception as e:
            result.steps.append(TestStep(
                step_num=len(result.steps) + 1,
                step_type=StepType.ERROR,
                error_message=str(e),
                status=StepStatus.FAILED,
            ))
            raise SkillExecutionError(skill_name=skill.name, detail=str(e))

    @staticmethod
    def _build_task_instruction(skill: SkillDefinition, arguments: dict[str, str]) -> str:
        """构建传递给子 Agent 的任务指令"""
        formatted_prompt = skill.format_prompt(arguments)
        parts = [f"请执行技能 '{skill.name}': {skill.description}"]
        if arguments:
            args_str = ", ".join(f"{k}={v}" for k, v in arguments.items())
            parts.append(f"参数: {args_str}")
        if formatted_prompt:
            parts.append(f"\n{formatted_prompt}")
        return "\n".join(parts)

    @staticmethod
    def _get_tool_risk_type(tool_name: str) -> str:
        """根据工具名称判断风险类型"""
        high_risk_tools = {"modify_data", "delete_data", "batch_update", "batch_delete"}
        sensitive_tools = {"web_search", "send_notification", "api_call", "send_email"}

        if tool_name in high_risk_tools:
            return "high_risk"
        elif tool_name in sensitive_tools:
            return "sensitive"
        return "safe"

    # ── 测试用例验证 ──

    def validate_result(self, result: TestResult, test_case: TestCase) -> dict:
        """验证测试结果是否符合测试用例的期望"""
        passed = True
        failures: list[str] = []

        # 1. 关键词匹配
        if test_case.expected_keywords:
            for kw in test_case.expected_keywords:
                if kw not in result.final_output:
                    passed = False
                    failures.append(f"期望关键词 '{kw}' 未出现在输出中")

        # 2. 排除词检查
        if test_case.excluded_keywords:
            for kw in test_case.excluded_keywords:
                if kw in result.final_output:
                    passed = False
                    failures.append(f"排除词 '{kw}' 出现在输出中")

        # 3. 工具调用断言
        if test_case.expected_tools:
            called_tools = {s.tool_name for s in result.steps if s.step_type == StepType.TOOL_CALL}
            for tool in test_case.expected_tools:
                if tool not in called_tools:
                    passed = False
                    failures.append(f"期望工具 '{tool}' 未被调用")

        # 4. 耗时阈值
        if test_case.max_duration_ms > 0:
            if result.total_duration_ms > test_case.max_duration_ms:
                passed = False
                failures.append(
                    f"执行耗时 {result.total_duration_ms:.0f}ms 超过阈值 {test_case.max_duration_ms}ms"
                )

        # 5. 执行状态
        if result.status != "success":
            passed = False
            failures.append(f"执行状态: {result.status}, 错误: {result.error_message}")

        return {
            "passed": passed,
            "failures": failures,
            "result_summary": {
                "status": result.status,
                "duration_ms": round(result.total_duration_ms, 1),
                "tool_calls": result.total_tool_calls,
                "output_length": len(result.final_output),
            },
        }
