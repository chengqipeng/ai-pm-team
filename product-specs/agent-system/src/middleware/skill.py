"""
SkillMiddleware — 技能经验注入 + before_model 上下文增强

对应 design.md §5.3.6 + §6.7:
- before_step: 匹配 Skill → 从 memory 召回历史经验
- before_model: 如果有匹配的 inline Skill，将经验注入到 LLM 上下文
"""
from __future__ import annotations

import logging
from .base import PluginContext
from ..state import GraphState

logger = logging.getLogger(__name__)


class SkillMiddleware:
    name = "skill"

    def __init__(self, skill_registry=None):
        self._registry = skill_registry

    async def before_step(self, state: GraphState, context: PluginContext) -> GraphState:
        """匹配 Skill → 从 memory 召回历史使用经验"""
        if not self._registry:
            return state
        step = state.current_step
        if not step:
            return state

        skill = None
        if hasattr(self._registry, 'match_by_intent'):
            skill = self._registry.match_by_intent(step.description)

        if skill and context.memory:
            try:
                memories = await context.memory.recall(
                    f"skill:{skill.name} 使用经验",
                    categories=["skills", "cases"],
                    max_results=2,
                )
                if memories:
                    exp = "\n".join(
                        f"- {m.get('content', m) if isinstance(m, dict) else str(m)}"
                        for m in memories
                    )
                    state.memory_context += f"\n[技能经验: {skill.name}]\n{exp}"
                    logger.info(f"SkillMiddleware: injected experience for {skill.name}")
            except Exception as e:
                logger.warning(f"SkillMiddleware recall error: {e}")

        return state

    async def after_step(self, state: GraphState, context: PluginContext) -> GraphState:
        return state

    async def before_model(self, state: GraphState, context: PluginContext) -> GraphState:
        """每次 LLM 调用前 — 可在此注入 Skill 相关的上下文"""
        return state

    async def after_model(self, state: GraphState, response: dict, context: PluginContext) -> dict:
        """每次 LLM 调用后 — 可在此检查 LLM 是否正确使用了 Skill"""
        return response

    async def before_tool_call(self, tool_name, input_data, state, context):
        return input_data

    async def after_tool_call(self, tool_name, result, state, context):
        return result
