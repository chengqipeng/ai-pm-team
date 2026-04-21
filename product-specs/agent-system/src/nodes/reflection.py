"""
ReflectionNode — 反思决策，对应产品设计 §3.8 + Agent-Core §五
5 种触发类型，每种有独立的处理策略
"""
from __future__ import annotations

import json
import logging

from ..graph.state import (
    GraphState, AgentStatus, StepStatus, AgentLimits,
)
from ..middleware.base import PluginContext
from ..dtypes import Message, MessageRole

logger = logging.getLogger(__name__)

FAILURE_ANALYSIS_PROMPT = """分析以下步骤失败的原因，推荐恢复策略。

## 失败的步骤
描述: {step_desc}
错误: {step_error}
已重试: {step_calls} 次
剩余预算: {remaining}

## 可选策略
- "retry": 重试当前步骤
- "skip": 跳过当前步骤继续
- "replan": 重新规划整个任务
- "escalate": 需要人工介入
- "abort": 终止任务

返回严格 JSON: {{"strategy": "...", "reason": "..."}}
"""

MEMORY_EXTRACT_PROMPT = """从以下对话中提取值得记住的业务知识。

分类: cases(案例), patterns(模式), entities(实体信息), events(事件), tools(工具技巧), skills(技能经验)

返回 JSON 数组: [{{"category": "...", "content": "...", "importance": "high|medium|low"}}]

对话内容:
{conversation}
"""


class ReflectionNode:

    async def execute(self, state: GraphState, context: PluginContext) -> GraphState:
        trigger = self._detect_trigger(state)
        logger.info(f"ReflectionNode trigger: {trigger}")

        if trigger == "stuck":
            return self._stuck_recovery(state)
        elif trigger == "step_failed":
            return await self._failure_analysis(state, context)
        elif trigger == "final":
            return await self._final_reflection(state, context)
        elif trigger == "budget_exhausted":
            return await self._budget_exhausted(state, context)
        else:
            state.status = AgentStatus.COMPLETED
            return state

    def _detect_trigger(self, state: GraphState) -> str:
        L = state._limits
        # stuck
        if (state.consecutive_errors >= L.MAX_CONSECUTIVE_ERRORS
                or state.consecutive_same_tool >= L.MAX_CONSECUTIVE_SAME_TOOL):
            return "stuck"
        # 预算耗尽
        if state.status == AgentStatus.MAX_TURNS or state.total_llm_calls >= L.MAX_TOTAL_LLM_CALLS:
            return "budget_exhausted"
        # 所有步骤完成
        if state.all_steps_done:
            return "final"
        # 当前步骤失败
        if state.current_step and state.current_step.status == StepStatus.FAILED:
            return "step_failed"
        return "final"

    # ── 策略 1: Stuck 自救（零 LLM 成本）──

    def _stuck_recovery(self, state: GraphState) -> GraphState:
        recovery = (
            "[STUCK RECOVERY] 你似乎陷入了循环。请:\n"
            "1. 停止重复相同的操作\n"
            "2. 重新审视原始目标\n"
            "3. 尝试完全不同的方法\n"
            "4. 如果无法继续，使用 ask_user 工具向用户求助"
        )
        state.messages.append(Message(role=MessageRole.SYSTEM, content=recovery))
        state.consecutive_errors = 0
        state.consecutive_same_tool = 0
        logger.info("Stuck recovery: injected prompt, reset counters")
        return state

    # ── 策略 2: 步骤失败分析 ──

    async def _failure_analysis(self, state: GraphState, context: PluginContext) -> GraphState:
        step = state.current_step
        if not step:
            state.status = AgentStatus.FAILED
            return state

        remaining = state._limits.MAX_TOTAL_LLM_CALLS - state.total_llm_calls
        prompt = FAILURE_ANALYSIS_PROMPT.format(
            step_desc=step.description,
            step_error=step.error or "未知错误",
            step_calls=step.llm_calls,
            remaining=remaining,
        )

        try:
            response = await context.llm.call(
                system_prompt="你是错误分析专家。",
                messages=[{"role": "user", "content": prompt}],
            )
            state.total_llm_calls += 1
            strategy = self._parse_strategy(response)
        except Exception as e:
            logger.error(f"Failure analysis LLM call failed: {e}")
            strategy = "abort"

        logger.info(f"Failure analysis strategy: {strategy}")

        if strategy == "retry":
            step.status = StepStatus.PENDING
            step.error = ""
            step.llm_calls = 0
        elif strategy == "skip":
            step.status = StepStatus.SKIPPED
            state.current_step_index += 1
        elif strategy == "replan":
            if state.replan_count < state._limits.MAX_REPLAN_COUNT:
                state.plan = None
                state.replan_count += 1
                state.current_step_index = 0
            else:
                state.status = AgentStatus.FAILED
                state.final_answer = "多次重新规划仍无法完成任务"
        elif strategy == "escalate":
            state.status = AgentStatus.PAUSED
            state.pause_reason = f"步骤失败需要人工介入: {step.error}"
        else:  # abort
            state.status = AgentStatus.FAILED
            state.final_answer = f"任务失败: {step.error}"

        return state

    # ── 策略 3: 最终反思 ──

    async def _final_reflection(self, state: GraphState, context: PluginContext) -> GraphState:
        # 提取记忆
        if context.memory:
            await self._extract_memories(state, context)

        # 编译最终回答
        state.final_answer = self._compile_answer(state)
        state.status = AgentStatus.COMPLETED
        return state

    # ── 策略 4: 预算耗尽 ──

    async def _budget_exhausted(self, state: GraphState, context: PluginContext) -> GraphState:
        # 尝试提取记忆
        if context.memory:
            await self._extract_memories(state, context)

        # 编译已完成的工作摘要
        completed = []
        pending = []
        if state.plan:
            for s in state.plan.steps:
                if s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED):
                    completed.append(s.description)
                else:
                    pending.append(s.description)

        summary = "预算已耗尽。\n"
        if completed:
            summary += f"已完成: {'; '.join(completed)}\n"
        if pending:
            summary += f"未完成: {'; '.join(pending)}\n"

        state.final_answer = summary
        state.status = AgentStatus.MAX_TURNS
        return state

    # ── 辅助方法 ──

    async def _extract_memories(self, state: GraphState, context: PluginContext):
        """提取 8 类记忆并写入 memory-plugin"""
        recent = state.messages[-10:] if len(state.messages) > 10 else state.messages
        conv_text = "\n".join(
            f"{getattr(m, 'role', 'unknown')}: {m.content if isinstance(m.content, str) else '...'}"
            for m in recent
            if hasattr(m, "content") and isinstance(m.content, str)
        )
        if not conv_text.strip():
            return

        prompt = MEMORY_EXTRACT_PROMPT.format(conversation=conv_text[:3000])
        try:
            response = await context.llm.call(
                system_prompt="你是知识提取专家。",
                messages=[{"role": "user", "content": prompt}],
            )
            state.total_llm_calls += 1
            memories = self._parse_memories(response)
            for mem in memories:
                await context.memory.commit(mem)
            if context.callbacks and context.callbacks.on_memory_extracted:
                context.callbacks.on_memory_extracted(memories)
        except Exception as e:
            logger.warning(f"Memory extraction failed: {e}")

    def _compile_answer(self, state: GraphState) -> str:
        """从消息历史中编译最终回答"""
        for msg in reversed(state.messages):
            role_val = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            if role_val == "assistant":
                if isinstance(msg.content, str) and msg.content.strip():
                    return msg.content
        return state.plan.goal if state.plan else ""

    def _parse_strategy(self, response: dict) -> str:
        for block in response.get("content", []):
            if block.get("type") != "text":
                continue
            text = block["text"].strip()
            if "```" in text:
                text = text.split("```json", 1)[-1].split("```", 1)[0] if "```json" in text else text.split("```", 1)[1].split("```", 1)[0]
            try:
                data = json.loads(text.strip())
                s = data.get("strategy", "abort")
                if s in ("retry", "skip", "replan", "escalate", "abort"):
                    return s
            except (json.JSONDecodeError, TypeError):
                pass
        return "abort"

    def _parse_memories(self, response: dict) -> list[dict]:
        for block in response.get("content", []):
            if block.get("type") != "text":
                continue
            text = block["text"].strip()
            if "```" in text:
                text = text.split("```json", 1)[-1].split("```", 1)[0] if "```json" in text else text.split("```", 1)[1].split("```", 1)[0]
            try:
                data = json.loads(text.strip())
                if isinstance(data, list):
                    return [m for m in data if isinstance(m, dict) and "category" in m and "content" in m]
            except (json.JSONDecodeError, TypeError):
                pass
        return []
