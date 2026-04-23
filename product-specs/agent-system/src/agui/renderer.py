"""AG-UI 渐进式渲染器 — 在 STEP 边界触发组件匹配和渲染

对齐 v2 的 V2ProgressiveRenderer：
- 监听 STEP_STARTED/STEP_FINISHED 事件
- 通过 CUSTOM 事件推送组件渲染数据（loading → delta → complete/error）
"""
from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

from . import models as m

logger = logging.getLogger(__name__)


class ComponentMatcher:
    """组件匹配器 — 根据 skill_apikey 查找对应的前端组件 apikey

    子类可覆盖 resolve() 实现自定义匹配逻辑（schema 匹配、配置查找等）。
    """

    def __init__(self, component_map: dict[str, str] | None = None) -> None:
        # skill_apikey → component_apikey 的静态映射
        self._map = component_map or {}

    def resolve(self, skill_apikey: str) -> str | None:
        """根据 skill_apikey 查找组件 apikey，未匹配返回 None"""
        return self._map.get(skill_apikey)

    def register(self, skill_apikey: str, component_apikey: str) -> None:
        self._map[skill_apikey] = component_apikey

    def warmup(self) -> None:
        """预热（加载配置/缓存等），子类可覆盖"""
        pass


class ProgressiveRenderer:
    """渐进式渲染器 — 在 STEP 边界插入 CUSTOM 组件渲染事件"""

    def __init__(self, matcher: ComponentMatcher | None = None) -> None:
        self._matcher = matcher or ComponentMatcher()
        self._active_components: dict[str, str] = {}  # skill_apikey → component_apikey

    async def process(
        self, events: AsyncGenerator[m.AGUIEvent, None]
    ) -> AsyncGenerator[m.AGUIEvent, None]:
        """处理事件流，在适当位置插入 CUSTOM 组件渲染事件"""
        async for event in events:
            # 先透传原始事件
            yield event

            # 在 STEP 边界触发组件渲染
            if event.type == m.AGUIEventType.STEP_STARTED:
                async for e in self._on_step_started(event):
                    yield e
            elif event.type == m.AGUIEventType.STEP_FINISHED:
                async for e in self._on_step_finished(event):
                    yield e

    async def _on_step_started(self, event: m.AGUIEvent) -> AsyncGenerator[m.AGUIEvent, None]:
        skill_apikey = event.data.get("skill_apikey", "")
        comp_apikey = self._matcher.resolve(skill_apikey)
        if comp_apikey is None:
            return
        self._active_components[skill_apikey] = comp_apikey
        yield m.custom_event("component_loading", {"apikey": comp_apikey, "state": "loading"})

    async def _on_step_finished(self, event: m.AGUIEvent) -> AsyncGenerator[m.AGUIEvent, None]:
        skill_apikey = event.data.get("skill_apikey", "")
        comp_apikey = self._active_components.pop(skill_apikey, None)
        if comp_apikey is None:
            return
        status = event.data.get("status", "completed")
        if status == "failed":
            yield m.custom_event("component_error", {
                "apikey": comp_apikey, "state": "error",
                "error": f"Skill {skill_apikey} failed",
            })
        else:
            yield m.custom_event("component_complete", {
                "apikey": comp_apikey, "state": "complete", "data": {},
            })

    def push_delta(self, skill_apikey: str, data: Any) -> m.AGUIEvent | None:
        """外部调用：推送 Skill 中间数据"""
        comp_apikey = self._active_components.get(skill_apikey)
        if comp_apikey is None:
            return None
        return m.custom_event("component_delta", {"apikey": comp_apikey, "data": data})
