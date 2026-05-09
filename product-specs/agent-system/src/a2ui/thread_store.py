"""A2UI Thread Store — 按 thread_id 持有重连需要的所有态

断线重连首包顺序（设计 §2.7）：
  1. RUN_STARTED(parent_run_id = last_run_id)
  2. MESSAGES_SNAPSHOT       ← 从这里读
  3. STATE_SNAPSHOT           ← 从 aggregator 读
  4. ACTIVITY_SNAPSHOT × N    ← 从这里读最近一次 surface 的 operations

本模块是进程级单例。生产接入 Redis 时，替换内部存储即可；接口不变。
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from .aggregator import SnapshotAggregator

logger = logging.getLogger(__name__)


@dataclass
class ThreadState:
    """单个 thread 的会话态快照（用于重连）。"""
    thread_id: str
    aggregator: SnapshotAggregator | None = None
    last_run_id: str | None = None
    # render_type → 最近一次下发的 operations 列表（展开后的 dict）
    surface_operations: dict[str, list[dict]] = field(default_factory=dict)
    # 消息缓冲（dict 形态；与 checkpointer 不同的是这里只保留 user/assistant 可序列化版本）
    messages: list[dict] = field(default_factory=list)

    def record_activity(self, render_type: str, operations: list[dict]) -> None:
        if operations:
            self.surface_operations[render_type] = list(operations)

    def append_message(self, message: dict) -> None:
        self.messages.append(message)

    def snapshot_state(self) -> dict | None:
        if self.aggregator is None:
            return None
        return self.aggregator.get_snapshot()

    def active_activities(self) -> list[dict]:
        """产出重连需要的 ACTIVITY_SNAPSHOT 描述。

        每个活跃 surface 对应一条 content.operations = 最近一次下发的 operations。
        优先从 aggregator 拿 surface_id 映射；若 aggregator 不可用则用 render_type 本身。
        """
        out: list[dict] = []
        # 构建 render_type → surface_id 映射
        surface_map: dict[str, str] = {}
        if self.aggregator is not None:
            surface_map = dict(self.aggregator._panel_surface_map)  # type: ignore[attr-defined]

        for render_type, ops in self.surface_operations.items():
            if not ops:
                continue
            surface_id = surface_map.get(render_type, f"surface-{render_type}")
            out.append({
                "message_id": f"a2ui-{self.thread_id[:8]}",
                "activity_type": "a2ui-surface",
                "replace": True,
                "content": {
                    "render_type": render_type,
                    "surface_id": surface_id,
                    "operations": ops,
                },
            })
        return out


class ThreadStore:
    """内存 thread 状态注册表。"""

    def __init__(self) -> None:
        self._threads: dict[str, ThreadState] = {}
        self._lock = threading.RLock()

    # ── CRUD ──

    def get(self, thread_id: str) -> ThreadState | None:
        with self._lock:
            return self._threads.get(thread_id)

    def ensure(self, thread_id: str) -> ThreadState:
        with self._lock:
            st = self._threads.get(thread_id)
            if st is None:
                st = ThreadState(thread_id=thread_id)
                self._threads[thread_id] = st
            return st

    def delete(self, thread_id: str) -> None:
        with self._lock:
            self._threads.pop(thread_id, None)

    # ── 跨 run 维护 ──

    def bind_aggregator(self, thread_id: str, aggregator: SnapshotAggregator) -> None:
        st = self.ensure(thread_id)
        st.aggregator = aggregator

    def set_last_run(self, thread_id: str, run_id: str) -> None:
        st = self.ensure(thread_id)
        st.last_run_id = run_id

    def record_activity(self, thread_id: str, render_type: str,
                        operations: list[dict]) -> None:
        st = self.ensure(thread_id)
        st.record_activity(render_type, operations)

    def append_message(self, thread_id: str, message: dict) -> None:
        st = self.ensure(thread_id)
        st.append_message(message)


# 全局单例（测试里可通过 reset_for_tests 清空）
thread_store = ThreadStore()


def reset_for_tests() -> None:  # pragma: no cover — 仅测试使用
    """清空全部 thread 状态。仅供测试调用。"""
    global thread_store
    thread_store = ThreadStore()
