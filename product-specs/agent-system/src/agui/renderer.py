"""AG-UI 渐进式渲染器 — 在 STEP 边界触发组件匹配和渲染

对齐 apps-agent v2 V2ProgressiveRenderer：
- 监听 STEP_STARTED / STEP_FINISHED
- 拦截 CUSTOM("skill_output") 内部事件（不透传前端），缓存后作为 component_complete 数据
- STEP_FINISHED 延迟到 component_complete + STATE_DELTA 之后再透传（保证前端一致性）
- 通过 CUSTOM 事件推送组件渲染状态：component_loading → component_delta → component_complete/error
- 同时产出 STATE_DELTA 增量更新 /panels/<apikey>/{state,data}
"""
from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Callable

from . import models as m

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# ComponentMatcher — 支持 5 层匹配的抽象基础版
# ═══════════════════════════════════════════════════════════

Resolver = Callable[[str], str | None]


class ComponentMatcher:
    """组件匹配器。

    本类提供静态 bind 映射的基础实现。5 层完整匹配（bind / prefer / ModelName /
    schema / LLM fallback）请使用子类 `ComponentMatcherV2`（见
    `src/a2ui/catalog.py` 中的注册表驱动版本）。

    为向后兼容，仍保留 `register(skill, component)` / `resolve(skill)` 接口。
    """

    def __init__(self, component_map: dict[str, str] | None = None) -> None:
        self._map: dict[str, str] = dict(component_map or {})
        self._extra_resolvers: list[Resolver] = []

    def register(self, skill_apikey: str, component_apikey: str) -> None:
        self._map[skill_apikey] = component_apikey

    def add_resolver(self, resolver: Resolver) -> None:
        """追加一个 fallback resolver（按注册顺序尝试）。"""
        self._extra_resolvers.append(resolver)

    def resolve(self, skill_apikey: str, **_kwargs: Any) -> str | None:
        if skill_apikey in self._map:
            return self._map[skill_apikey]
        for r in self._extra_resolvers:
            try:
                result = r(skill_apikey)
            except Exception:
                logger.exception("ComponentMatcher resolver failed for %s", skill_apikey)
                continue
            if result:
                return result
        return None

    def warmup(self) -> None:
        """预热（加载配置/缓存等），子类可覆盖"""


# ═══════════════════════════════════════════════════════════
# ProgressiveRenderer
# ═══════════════════════════════════════════════════════════

class ProgressiveRenderer:
    """渐进式渲染器。

    事件改写规则：
    - STEP_STARTED        : 透传后插入 CUSTOM("component_loading")
    - CUSTOM(skill_output): 吸收（不透传），缓存到 _pending_skill_output
    - STEP_FINISHED       : 先插入 CUSTOM("component_complete"/"component_error") + STATE_DELTA
                            最后再透传 STEP_FINISHED 原事件
    """

    def __init__(self, matcher: ComponentMatcher | None = None) -> None:
        self._matcher = matcher or ComponentMatcher()
        # skill_apikey → component_apikey
        self._active_components: dict[str, str] = {}
        # step_name → skill_apikey（STEP_STARTED 时记录，以便 STEP_FINISHED 反查）
        self._step_skill: dict[str, str] = {}
        # skill_apikey → 最后一次 skill_output data
        self._pending_skill_output: dict[str, Any] = {}
        # step_name → status（由 step_metadata 事件记录，用于 STEP_FINISHED 分支）
        self._pending_status: dict[str, str] = {}

    async def process(
        self, events: AsyncGenerator[m.AGUIEvent, None]
    ) -> AsyncGenerator[m.AGUIEvent, None]:
        async for event in events:
            # 1. 拦截 skill_output 内部事件（不透传）
            if (event.type == m.AGUIEventType.CUSTOM
                    and event.data.get("name") == "skill_output"):
                value = event.data.get("value", {}) or {}
                skill = value.get("skill_apikey", "")
                if skill:
                    self._pending_skill_output[skill] = value.get("data")
                continue

            # 2. step_metadata 记录 skill_apikey / status（但仍透传）
            if (event.type == m.AGUIEventType.CUSTOM
                    and event.data.get("name") == "step_metadata"):
                value = event.data.get("value", {}) or {}
                step_name = value.get("step_name")
                skill = value.get("skill_apikey")
                phase = value.get("phase")
                status = value.get("status")
                if step_name and skill:
                    self._step_skill[step_name] = skill
                if phase == "finished" and step_name and status:
                    self._pending_status[step_name] = status
                yield event
                continue

            # 3. STEP_FINISHED 延迟透传
            if event.type == m.AGUIEventType.STEP_FINISHED:
                async for e in self._on_step_finished(event):
                    yield e
                yield event  # 最后透传
                continue

            # 4. 其他事件原样透传
            yield event

            # 5. STEP_STARTED 之后插入 component_loading
            if event.type == m.AGUIEventType.STEP_STARTED:
                async for e in self._on_step_started(event):
                    yield e

    # ── 内部 ──

    async def _on_step_started(self, event: m.AGUIEvent) -> AsyncGenerator[m.AGUIEvent, None]:
        step_name = event.data.get("step_name", "")
        skill_apikey = self._step_skill.get(step_name, step_name)  # fallback 用 step_name
        comp_apikey = self._matcher.resolve(skill_apikey)
        if comp_apikey is None:
            return
        self._active_components[skill_apikey] = comp_apikey
        yield m.custom_event("component_loading",
                             {"apikey": comp_apikey, "state": "loading"})

    async def _on_step_finished(self, event: m.AGUIEvent) -> AsyncGenerator[m.AGUIEvent, None]:
        step_name = event.data.get("step_name", "")
        skill_apikey = self._step_skill.pop(step_name, step_name)
        status = self._pending_status.pop(step_name, "completed")
        comp_apikey = self._active_components.pop(skill_apikey, None)
        skill_data = self._pending_skill_output.pop(skill_apikey, None)

        if comp_apikey is None:
            return

        if status == "failed":
            yield m.custom_event("component_error", {
                "apikey": comp_apikey,
                "state": "error",
                "error": f"Skill {skill_apikey} failed",
            })
            yield m.state_delta([
                {"op": "replace", "path": f"/panels/{comp_apikey}/state", "value": "error"},
            ])
        else:
            yield m.custom_event("component_complete", {
                "apikey": comp_apikey,
                "state": "complete",
                "data": skill_data,
            })
            patch: list[dict] = [
                {"op": "replace", "path": f"/panels/{comp_apikey}/state", "value": "complete"},
            ]
            if skill_data is not None:
                patch.append({"op": "replace",
                              "path": f"/panels/{comp_apikey}/data",
                              "value": skill_data})
            yield m.state_delta(patch)

    # ── 外部 API ──

    def push_delta(self, skill_apikey: str, data: Any) -> m.AGUIEvent | None:
        """推送 Skill 中间数据（组件增量渲染）"""
        comp_apikey = self._active_components.get(skill_apikey)
        if comp_apikey is None:
            return None
        return m.custom_event("component_delta",
                              {"apikey": comp_apikey, "data": data})
