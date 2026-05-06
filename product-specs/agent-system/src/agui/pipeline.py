"""AG-UI 管道工厂 — 创建 Converter + Renderer 管道"""
from __future__ import annotations

from .converter import AGUIConverter
from .renderer import ProgressiveRenderer, ComponentMatcher


def create_agui_pipeline(
    run_id: str,
    thread_id: str,
    history_messages: list[dict] | None = None,
    component_map: dict[str, str] | None = None,
) -> tuple[AGUIConverter, ProgressiveRenderer]:
    """工厂函数：创建 AG-UI 转换 + 渲染管道

    Args:
        run_id: 运行 ID
        thread_id: 线程 ID
        history_messages: 历史消息（会话初始化时发射 MESSAGES_SNAPSHOT）
        component_map: skill_apikey → component_apikey 映射

    Returns:
        (converter, renderer) 元组。
        使用: async for event in renderer.process(converter.convert(astream)):
    """
    matcher = ComponentMatcher(component_map)
    matcher.warmup()
    converter = AGUIConverter(run_id=run_id, thread_id=thread_id, history_messages=history_messages)
    renderer = ProgressiveRenderer(matcher=matcher)
    return converter, renderer
