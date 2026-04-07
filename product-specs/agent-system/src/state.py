"""
状态管理 — 借鉴 AppStateStore.ts
不可变状态 + 订阅模式
"""
from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .types import PermissionMode, ToolPermissionContext


@dataclass
class AppState:
    """应用全局状态 (借鉴 AppStateStore.ts)"""
    messages: list = field(default_factory=list)
    is_loading: bool = False
    main_loop_model: str = "claude-sonnet-4-20250514"
    tool_permission_context: ToolPermissionContext = field(
        default_factory=ToolPermissionContext
    )
    mcp_tools: list = field(default_factory=list)
    mcp_commands: list = field(default_factory=list)
    tasks: dict = field(default_factory=dict)
    usage: dict = field(default_factory=lambda: {
        "total_tokens": 0, "total_cost": 0.0, "api_duration_ms": 0,
    })
    file_history: dict = field(default_factory=dict)


class AppStateStore:
    """
    外部状态存储 (借鉴 state/store.ts)
    线程安全的不可变更新 + 订阅模式
    """

    def __init__(self, initial_state: AppState | None = None):
        self._state = initial_state or AppState()
        self._listeners: list[Callable[[], None]] = []
        self._lock = threading.Lock()

    def get_state(self) -> AppState:
        return self._state

    def set_state(self, updater: Callable[[AppState], AppState]) -> None:
        with self._lock:
            old = self._state
            new = updater(copy.copy(old))
            if new is not old:
                self._state = new
                for listener in self._listeners:
                    listener()

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)
