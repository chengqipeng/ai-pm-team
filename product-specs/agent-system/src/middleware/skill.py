"""SkillMiddleware — 技能经验注入"""
from __future__ import annotations

from .base import PluginContext
from ..graph.state import GraphState


class SkillMiddleware:
    name = "skill"

    def __init__(self, skill_registry=None):
        self._registry = skill_registry

    async def before_step(self, state: GraphState, context: PluginContext) -> GraphState:
        """如果当前步骤涉及技能，注入历史使用经验"""
        if not self._registry or not context.memory:
            return state
        step = state.current_step
        if not step:
            return state
        # 搜索技能相关的历史经验
        skill = self._registry.match_by_intent(step.description) if hasattr(self._registry, "match_by_intent") else None
        if skill and context.memory:
            try:
                memories = await context.memory.recall(
                    f"skill:{skill.name} 使用经验",
                    categories=["skills", "cases"],
                    max_results=2,
                )
                if memories:
                    exp = "\n".join(f"- {m.get('content', m) if isinstance(m, dict) else str(m)}" for m in memories)
                    state.memory_context += f"\n[技能经验: {skill.name}]\n{exp}"
            except Exception:
                pass
        return state

    async def after_step(self, state: GraphState, context: PluginContext) -> GraphState:
        return state

    async def before_tool_call(self, tool_name, input_data, state, context):
        return input_data

    async def after_tool_call(self, tool_name, result, state, context):
        return result
