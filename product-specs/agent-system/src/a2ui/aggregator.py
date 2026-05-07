"""SnapshotAggregator — 业务状态聚合器

设计对齐 apps-agent v1 `SnapshotAggregator` + v2 `V2SnapshotAggregator` 的合并方案。

职责：
1. 接收 Agent 产出的"数据事件"（render_type + data），按 render_type 归类到业务状态 dict
2. 为每个新出现的 render_type 自动分配 surfaceId，维护 panelSurfaceMap
3. 计算两次快照间的 JSON Patch 差分，决定发送 STATE_SNAPSHOT 还是 STATE_DELTA
4. 首次出现的 render_type 产出 ACTIVITY_SNAPSHOT（进度通知，承载 A2UI 消息）

输出 A2UI v0.8 业务状态快照结构:
    {
      "phase": "executing",
      "<render_type_1>": <data_1>,
      "<render_type_2>": <data_2>,
      "panelLayoutOrder": [...],
      "panelAppearanceOrder": [...],
      "notifications": [...],
      "panelSurfaceMap": {"render_type_1": "panel-slot-1", ...}
    }

生命周期：每个 Agent run 创建一个实例，reset() 清空；跨 run 不共享（实例级状态）。
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from src.agui import models as agui
from .models import A2UIMessage, Component, SurfaceUpdate

try:
    import jsonpatch  # type: ignore
except ImportError:  # pragma: no cover
    jsonpatch = None  # type: ignore

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════

# delta 体积 < 全量体积 * 阈值 → 发 STATE_DELTA，否则 STATE_SNAPSHOT
DELTA_THRESHOLD = 0.5

# 通知面板固定使用的 surface id
NOTIFICATION_SURFACE_ID = "panel-slot-top-1"

# 快照元数据 key 集合（非业务数据；用于 generate_state_delta 等场景过滤）
SNAPSHOT_META_KEYS: frozenset[str] = frozenset({
    "phase",
    "panelLayoutOrder",
    "panelAppearanceOrder",
    "notifications",
    "panelSurfaceMap",
})


# ═══════════════════════════════════════════════════════════
# 辅助：构造进度通知 SurfaceUpdate
# ═══════════════════════════════════════════════════════════

def _progress_surface_update(
    surface_id: str,
    message: str,
    icon: str = "ℹ️",
    root_id: str = "root",
) -> SurfaceUpdate:
    """构建"图标 + 文本"的 Row 通知组件，返回 SurfaceUpdate"""
    icon_id = f"{root_id}/icon"
    msg_id = f"{root_id}/msg"
    components = [
        Component(id=icon_id, type="Text", props={
            "text": {"literalString": icon}, "size": "lg",
        }),
        Component(id=msg_id, type="Text", props={
            "text": {"literalString": message},
        }),
        Component(id=root_id, type="Row", props={
            "alignment": "center",
            "children": {"explicitList": [icon_id, msg_id]},
        }),
    ]
    return SurfaceUpdate(surface_id=surface_id, components=components)


# ═══════════════════════════════════════════════════════════
# SnapshotAggregator
# ═══════════════════════════════════════════════════════════

class SnapshotAggregator:
    """业务状态聚合器。

    典型用法：

        agg = SnapshotAggregator(run_id="r-123", thread_id="t-456")

        # 每当 Skill / Tool 产出一块业务数据:
        events = agg.add("customers", [{"name": "工行"}, ...])  # 首次 → 3 个事件
        for e in events: yield e

        events = agg.add("customers", [...])  # 后续 → 1 个事件
        for e in events: yield e

        # run 结束时清空:
        agg.reset()
    """

    def __init__(self, run_id: str, thread_id: str = "") -> None:
        self._run_id = run_id
        self._thread_id = thread_id
        self._message_id = f"a2ui-{run_id[:8]}"

        # 业务数据: render_type → data
        self._business_state: dict[str, Any] = {}
        # 面板映射: render_type → surfaceId
        self._panel_surface_map: dict[str, str] = {}
        # 面板排列顺序（按首次添加顺序）
        self._panel_layout_order: list[str] = []
        # 通知列表
        self._notifications: list[dict] = []
        # 面板槽位计数器
        self._panel_counter = 0
        # 上一次快照（用于 diff）
        self._previous_snapshot: dict | None = None

    # ── 主 API ──

    def add(
        self,
        render_type: str,
        data: Any,
        *,
        notification_message: str | None = None,
        notification_icon: str = "ℹ️",
        emit_activity: bool = True,
    ) -> list[agui.AGUIEvent]:
        """追加一块业务数据，返回需要发送给前端的 AG-UI 事件列表

        事件列表顺序（取决于场景）:
        1. ACTIVITY_SNAPSHOT（首次添加且 emit_activity=True）— 进度通知
        2. STATE_SNAPSHOT 或 STATE_DELTA — 业务状态
        """
        is_first = render_type not in self._business_state
        self._business_state[render_type] = data

        events: list[agui.AGUIEvent] = []

        if is_first:
            self._panel_counter += 1
            surface_id = f"panel-slot-{self._panel_counter}"
            self._panel_surface_map[render_type] = surface_id
            self._panel_layout_order.append(render_type)

            # 维护内部通知列表
            msg = notification_message or f"✅ {render_type} 已加载"
            notification = {
                "id": f"n-{render_type}-{uuid.uuid4().hex[:6]}",
                "type": "info",
                "message": msg,
                "timestamp": "now",
            }
            self._notifications.append(notification)

            if emit_activity:
                notify_su = _progress_surface_update(
                    surface_id=NOTIFICATION_SURFACE_ID,
                    message=msg,
                    icon=notification_icon,
                )
                events.append(agui.activity_snapshot(
                    message_id=self._message_id,
                    activity_type="a2ui-surface",
                    content={"operations": [notify_su.to_dict()]},
                    replace=True,
                ))

        # 快照/差分决策
        current = self._build_snapshot_dict()
        events.append(self._decide_state_event(current))
        self._previous_snapshot = current

        return events

    def emit_ui(
        self,
        render_type: str,
        messages: list[A2UIMessage],
        *,
        activity_type: str = "a2ui-surface",
    ) -> list[agui.AGUIEvent]:
        """把一批 A2UI 消息打到 render_type 对应的面板槽位上，产出 ACTIVITY_SNAPSHOT

        Skill / IntentHandler 产出 A2UIBuilder 的消息后调用此方法即可下发。
        若 render_type 尚未分配槽位，会先自动分配。
        """
        if render_type not in self._panel_surface_map:
            self._panel_counter += 1
            surface_id = f"panel-slot-{self._panel_counter}"
            self._panel_surface_map[render_type] = surface_id
            self._panel_layout_order.append(render_type)

        return [agui.activity_snapshot(
            message_id=self._message_id,
            activity_type=activity_type,
            content={"operations": [m.to_dict() for m in messages]},
            replace=True,
        )]

    def surface_id_for(self, render_type: str) -> str | None:
        """查询 render_type 对应的 surfaceId，未分配则返回 None"""
        return self._panel_surface_map.get(render_type)

    def ensure_surface(self, render_type: str) -> str:
        """查询或分配 surfaceId（保证返回一个）"""
        if render_type not in self._panel_surface_map:
            self._panel_counter += 1
            self._panel_surface_map[render_type] = f"panel-slot-{self._panel_counter}"
            self._panel_layout_order.append(render_type)
        return self._panel_surface_map[render_type]

    def get_snapshot(self) -> dict:
        """获取当前完整业务状态（不触发事件发送）"""
        return self._build_snapshot_dict()

    def force_snapshot(self) -> agui.AGUIEvent:
        """强制产出一次 STATE_SNAPSHOT（不做 delta，用于会话首包/重连）"""
        current = self._build_snapshot_dict()
        self._previous_snapshot = current
        return agui.state_snapshot(current)

    def reset(self) -> None:
        """清空所有状态，跨 run 时调用"""
        self._business_state = {}
        self._panel_surface_map = {}
        self._panel_layout_order = []
        self._notifications = []
        self._panel_counter = 0
        self._previous_snapshot = None

    # ── 内部 ──

    def _build_snapshot_dict(self) -> dict:
        """序列化为 A2UI v0.8 业务状态快照"""
        snapshot: dict[str, Any] = {"phase": "executing"}
        for rt, data in self._business_state.items():
            snapshot[rt] = data
        snapshot["panelLayoutOrder"] = list(self._panel_layout_order)
        snapshot["panelAppearanceOrder"] = list(self._panel_layout_order)
        snapshot["notifications"] = list(self._notifications)
        snapshot["panelSurfaceMap"] = dict(self._panel_surface_map)
        return snapshot

    def _decide_state_event(self, current: dict) -> agui.AGUIEvent:
        """增量 vs 全量决策"""
        if self._previous_snapshot is None or jsonpatch is None:
            return agui.state_snapshot(current)

        try:
            patch = jsonpatch.make_patch(self._previous_snapshot, current)
            patch_ops = patch.patch

            if not patch_ops:
                # 无变化仍发全量，保证幂等（前端可据此刷新时间戳）
                return agui.state_snapshot(current)

            diff_size = len(json.dumps(patch_ops, ensure_ascii=False))
            snap_size = len(json.dumps(current, ensure_ascii=False))

            if diff_size < snap_size * DELTA_THRESHOLD:
                return agui.state_delta(patch_ops)
            return agui.state_snapshot(current)
        except Exception:
            logger.exception("state delta 计算失败，降级为全量快照")
            return agui.state_snapshot(current)
