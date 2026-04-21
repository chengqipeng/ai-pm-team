"""
Router — 路由决策，对应产品设计 §3.3.2 的 7 级优先级表
纯函数，根据 GraphState 决定下一个 Node
"""
from __future__ import annotations

import logging
from .state import GraphState, AgentStatus, StepStatus, AgentLimits

logger = logging.getLogger(__name__)


class Router:

    def __init__(self, limits: AgentLimits | None = None):
        self._limits = limits or AgentLimits()

    def next_node(self, state: GraphState) -> str | None:
        """返回下一个 Node 名称，None 表示终止"""
        L = self._limits

        # P1: 非 RUNNING → 终止
        if state.status != AgentStatus.RUNNING:
            return None

        # P2: 全局预算 100% → 强制最终反思
        if state.total_llm_calls >= L.MAX_TOTAL_LLM_CALLS:
            state.status = AgentStatus.MAX_TURNS
            return "reflection"

        # P3: stuck 检测 → 反思
        if (state.consecutive_errors >= L.MAX_CONSECUTIVE_ERRORS
                or state.consecutive_same_tool >= L.MAX_CONSECUTIVE_SAME_TOOL):
            return "reflection"

        # P4: 无计划 → 规划
        if state.plan is None:
            return "planning"

        # P5: 所有步骤完成 → 最终反思
        if state.all_steps_done:
            return "reflection"

        # P6: 当前步骤失败 → 反思
        step = state.current_step
        if step and step.status == StepStatus.FAILED:
            return "reflection"

        # P7: 当前步骤待执行/执行中 → 执行
        if step and step.status in (StepStatus.PENDING, StepStatus.RUNNING):
            return "execution"

        # 推进到下一步
        state.current_step_index += 1
        if state.plan and state.current_step_index < len(state.plan.steps):
            return "execution"

        # 兜底
        return "reflection"

    def inject_budget_warning(self, state: GraphState) -> str | None:
        """预算警告注入 — 80%/95% 时追加提醒"""
        L = self._limits
        used = state.total_llm_calls
        if used >= L.BUDGET_WARNING_95:
            return (
                "\n\n[URGENT] 预算即将耗尽（95%），"
                f"仅剩 {L.MAX_TOTAL_LLM_CALLS - used} 次调用。请立即总结并结束。"
            )
        if used >= L.BUDGET_WARNING_80:
            return (
                "\n\n[WARNING] 已使用 80% 预算，请加快执行节奏，优先完成最重要的步骤。"
            )
        return None
