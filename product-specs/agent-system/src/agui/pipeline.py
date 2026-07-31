"""AG-UI 管道工厂 — 创建 Converter + Renderer 管道"""
from __future__ import annotations

from typing import Any

from .converter import AGUIConverter
from .renderer import ProgressiveRenderer, ComponentMatcher


def create_agui_pipeline(
    run_id: str,
    thread_id: str,
    history_messages: list[dict] | None = None,
    component_map: dict[str, str] | None = None,
    skill_registry: Any | None = None,
    *,
    parent_run_id: str | None = None,
    emit_legacy_reasoning: bool = True,
) -> tuple[AGUIConverter, ProgressiveRenderer]:
    """工厂函数：创建 AG-UI 转换 + 渲染管道

    Args:
        run_id: 运行 ID
        thread_id: 线程 ID
        history_messages: 历史消息（会话初始化时发射 MESSAGES_SNAPSHOT）
        component_map: skill_apikey → component_apikey 映射
        skill_registry: SkillRegistry 实例，用于解析 output_mode

    Returns:
        (converter, renderer) 元组。
        使用: async for event in renderer.process(converter.convert(astream)):
    """
    matcher = ComponentMatcher(component_map)
    matcher.warmup()
    converter = AGUIConverter(
        run_id=run_id, thread_id=thread_id,
        history_messages=history_messages,
        parent_run_id=parent_run_id,
        emit_legacy_reasoning=emit_legacy_reasoning,
        skill_registry=skill_registry,
    )
    renderer = ProgressiveRenderer(matcher=matcher)
    return converter, renderer
