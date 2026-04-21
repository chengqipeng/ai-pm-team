"""
PlanningNode — 任务规划，对应产品设计 §3.3.4 + Agent-Core §三
判断复杂度 → 简单任务单步 / 复杂任务 LLM 多步规划
"""
from __future__ import annotations

import json
import logging

from ..graph.state import GraphState, TaskPlan, TaskStep
from ..middleware.base import PluginContext

logger = logging.getLogger(__name__)

PLANNING_PROMPT = """你是任务规划专家。分析用户请求，生成执行计划。

## 规则
1. 简单任务（单次查询/单次操作）→ 生成 1 步计划
2. 复杂任务（多步骤/多实体/需要分析）→ 生成 2-15 步计划
3. 每步包含 description（做什么）

## 输出格式（严格 JSON，不要 markdown 包裹）
{"goal": "任务目标", "steps": [{"description": "步骤描述"}]}

## 用户请求
{user_message}
"""


class PlanningNode:

    async def execute(self, state: GraphState, context: PluginContext) -> GraphState:
        user_msg = self._get_last_user_message(state)
        step_budget = state._limits.MAX_STEP_LLM_CALLS if hasattr(state, '_limits') else 20

        if not user_msg:
            state.plan = TaskPlan(goal="", steps=[TaskStep(description="回答用户", max_llm_calls=step_budget)])
            return state

        # 简单任务：直接单步
        if self._is_simple(user_msg):
            state.plan = TaskPlan(goal=user_msg, steps=[TaskStep(description=user_msg, max_llm_calls=step_budget)])
            return state

        # 复杂任务：调 LLM 规划
        prompt = PLANNING_PROMPT.replace("{user_message}", user_msg)
        if state.memory_context:
            prompt += f"\n\n## 历史经验\n{state.memory_context}"

        try:
            response = await context.llm.call(
                system_prompt=prompt,
                messages=[{"role": "user", "content": user_msg}],
            )
            state.total_llm_calls += 1
            plan = self._parse_plan(response, step_budget)
            if plan and 1 <= len(plan.steps) <= 15:
                state.plan = plan
                return state
        except Exception as e:
            logger.warning(f"Planning LLM call failed: {e}")

        # 降级：单步
        state.plan = TaskPlan(goal=user_msg, steps=[TaskStep(description=user_msg, max_llm_calls=step_budget)])
        return state

    def _is_simple(self, msg: str) -> bool:
        if len(msg) > 150:
            return False
        complex_kw = ["分析", "对比", "批量", "迁移", "审计", "诊断", "配置", "报告", "调研", "同时", "然后"]
        return not any(kw in msg for kw in complex_kw)

    def _parse_plan(self, response: dict, step_budget: int = 20) -> TaskPlan | None:
        for block in response.get("content", []):
            if block.get("type") != "text":
                continue
            text = block["text"].strip()
            # 去掉 markdown 包裹
            if "```json" in text:
                text = text.split("```json", 1)[1].split("```", 1)[0]
            elif "```" in text:
                text = text.split("```", 1)[1].split("```", 1)[0]
            try:
                data = json.loads(text.strip())
                steps = [
                    TaskStep(
                        description=s.get("description", ""),
                        agent_type=s.get("agent_type"),
                        tools=s.get("tools"),
                        max_llm_calls=step_budget,
                    )
                    for s in data.get("steps", [])
                    if s.get("description")
                ]
                if steps:
                    return TaskPlan(goal=data.get("goal", ""), steps=steps)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return None

    @staticmethod
    def _get_last_user_message(state: GraphState) -> str:
        for msg in reversed(state.messages):
            role_val = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            if role_val == "user":
                c = msg.content
                if isinstance(c, str):
                    return c
                if isinstance(c, list):
                    parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
                    return " ".join(parts)
        return ""
