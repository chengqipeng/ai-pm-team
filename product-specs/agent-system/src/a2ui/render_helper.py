"""A2UI 渲染辅助 — 给 Skill / Middleware 开发者用的一站式 API

典型用法：

    helper = A2UIRenderHelper(run_id, thread_id)

    # Skill 产出业务数据
    data = {"customers": [{"id": "C1", "name": "工行"}, ...]}

    # 一步完成：数据写 Shared State + 构建 Surface + 下发
    for event in helper.render(
        render_type="customers_top",
        data=data["customers"],
        surface_fn=build_customers_surface,   # 业务侧提供
        notification_message="✅ Top10 客户已加载",
    ):
        yield event   # → AG-UI 事件流

其中 `build_customers_surface(builder, data_path)` 由业务侧实现：

    def build_customers_surface(ui: A2UIBuilder, data_path: str) -> None:
        ui.column("root", children=[
            ui.text("title", literal="Q3 新签 Top10", usage_hint="h2"),
            ui.list_template("list",
                data_binding=data_path,          # "/data/customers_top"
                template_id="row"),
            ui.add(Component(id="row", type="CrmRecordCard", props={
                "recordType": {"literalString": "customer"},
                "recordId":   {"path": "./id"},
            })),
        ])

Helper 负责：
1. Aggregator.add → STATE_SNAPSHOT/DELTA（业务数据进 Shared State）
2. CatalogRegistry.default_id → beginRendering.catalogId
3. 调用 surface_fn 构建结构
4. Aggregator.emit_ui → ACTIVITY_SNAPSHOT（结构下发）
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

from src.agui import models as agui

from .aggregator import SnapshotAggregator
from .builder import A2UIBuilder
from .catalog import CatalogRegistry, STANDARD_V08

logger = logging.getLogger(__name__)

# Skill 侧提供的 surface 构建回调 — 接收 Builder + 数据路径前缀，就地向 Builder 添加组件
SurfaceBuilder = Callable[[A2UIBuilder, str], None]


class A2UIRenderHelper:
    """组合 SnapshotAggregator + A2UIBuilder + CatalogRegistry 的一站式渲染辅助。

    生命周期：每个 Agent run 一个实例。
    """

    def __init__(
        self,
        run_id: str,
        thread_id: str = "",
        *,
        aggregator: SnapshotAggregator | None = None,
        catalog_registry: CatalogRegistry | None = None,
        catalog_id: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.thread_id = thread_id
        self.aggregator = aggregator or SnapshotAggregator(run_id=run_id, thread_id=thread_id)
        self.catalog_registry = catalog_registry
        self._catalog_id = catalog_id or (
            catalog_registry.default_id() if catalog_registry else STANDARD_V08
        )

    # ── 主 API ──

    def render(
        self,
        render_type: str,
        data: Any,
        surface_fn: SurfaceBuilder,
        *,
        notification_message: str | None = None,
        notification_icon: str = "ℹ️",
        activity_type: str = "a2ui-surface",
    ) -> list[agui.AGUIEvent]:
        """一站式产出：数据 + 结构 + 下发。

        返回事件序列（按顺序）：
          1. [首次] ACTIVITY_SNAPSHOT — 进度通知
          2. STATE_SNAPSHOT / STATE_DELTA — 业务数据
          3. ACTIVITY_SNAPSHOT — surface 结构（surfaceUpdate + beginRendering）
        """
        events: list[agui.AGUIEvent] = []

        # 1. 业务数据进 Shared State（aggregator 内部产出通知 + STATE 事件）
        events.extend(self.aggregator.add(
            render_type,
            data,
            notification_message=notification_message,
            notification_icon=notification_icon,
        ))

        # 2. 构建 surface 结构
        surface_id = self.aggregator.ensure_surface(render_type)
        data_path = self.aggregator.bind_a2ui_data(render_type)
        ui = A2UIBuilder(surface_id=surface_id, catalog_id=self._catalog_id)
        try:
            surface_fn(ui, data_path)
        except Exception:
            logger.exception("surface_fn failed for render_type=%s", render_type)
            return events
        messages = ui.messages()

        # 3. 下发 surface 结构（ACTIVITY_SNAPSHOT）
        events.extend(self.aggregator.emit_ui(
            render_type, messages, activity_type=activity_type,
        ))
        return events

    def update_data(self, render_type: str, data: Any) -> list[agui.AGUIEvent]:
        """只更新数据，不重建结构（适合列表追加、字段变更等场景）。"""
        return self.aggregator.add(render_type, data, emit_activity=False)

    def reset(self) -> None:
        self.aggregator.reset()


__all__ = ["A2UIRenderHelper", "SurfaceBuilder"]
