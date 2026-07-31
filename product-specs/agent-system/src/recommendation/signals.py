"""用户行为信号采集与有界缓冲"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class UserSignal:
    """单条用户行为信号"""
    signal_type: str  # chat_intent | ui_action | tool_call | data_mutation | time_trigger
    entity_type: str  # account | opportunity | contact | activity | lead
    entity_key: str | None = None  # recordApiKey
    action: str = ""  # view | query | create | edit | insight | analyze | failed_query
    context: dict[str, Any] = field(default_factory=dict)
    thread_id: str = ""
    timestamp: int = 0  # ms

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = int(time.time() * 1000)


class SignalBuffer:
    """per-thread 有界信号缓冲（进程内，后续可迁移 Redis）"""

    def __init__(self, *, max_per_thread: int = 100, max_threads: int = 512) -> None:
        self._max_per_thread = max_per_thread
        self._max_threads = max_threads
        self._buffers: dict[str, deque[UserSignal]] = defaultdict(
            lambda: deque(maxlen=self._max_per_thread))
        self._lock = threading.RLock()

    def append(self, thread_id: str, signal: UserSignal) -> None:
        signal.thread_id = thread_id
        with self._lock:
            self._buffers[thread_id].append(signal)
            # LRU 淘汰
            if len(self._buffers) > self._max_threads:
                oldest = next(iter(self._buffers))
                del self._buffers[oldest]

    def get_recent(self, thread_id: str, *, window_minutes: int = 60) -> list[UserSignal]:
        cutoff = int(time.time() * 1000) - window_minutes * 60_000
        with self._lock:
            buf = self._buffers.get(thread_id)
            if not buf:
                return []
            return [s for s in buf if s.timestamp >= cutoff]

    def get_all(self, thread_id: str) -> list[UserSignal]:
        with self._lock:
            buf = self._buffers.get(thread_id)
            return list(buf) if buf else []

    def clear(self, thread_id: str | None = None) -> None:
        with self._lock:
            if thread_id:
                self._buffers.pop(thread_id, None)
            else:
                self._buffers.clear()


signal_buffer = SignalBuffer()
