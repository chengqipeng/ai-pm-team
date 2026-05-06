"""防抖队列 — 合并短时间内的多次记忆更新请求"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class _PendingUpdate:
    thread_id: str
    messages: list[Any]
    timestamp: float = field(default_factory=time.monotonic)


class DebounceQueue:
    """防抖队列，合并短时间内的多次记忆更新请求为一次处理"""

    def __init__(
        self,
        debounce_seconds: float = 5.0,
        handler: Callable[[str, list[Any]], Awaitable[None]] | None = None,
    ) -> None:
        self._debounce_seconds = debounce_seconds
        self._handler = handler
        self._pending: dict[str, _PendingUpdate] = {}
        self._timers: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._flush_count: int = 0

    @property
    def debounce_seconds(self) -> float:
        return self._debounce_seconds

    @property
    def flush_count(self) -> int:
        return self._flush_count

    def submit(self, thread_id: str, messages: list[Any]) -> None:
        """提交记忆更新请求，短时间内多次提交会被合并"""
        if not messages:
            return
        if thread_id in self._pending:
            self._pending[thread_id].messages.extend(messages)
            self._pending[thread_id].timestamp = time.monotonic()
        else:
            self._pending[thread_id] = _PendingUpdate(
                thread_id=thread_id, messages=list(messages),
            )
        self._reset_timer(thread_id)

    def _reset_timer(self, thread_id: str) -> None:
        if thread_id in self._timers:
            self._timers[thread_id].cancel()
        try:
            loop = asyncio.get_running_loop()
            self._timers[thread_id] = loop.create_task(self._delayed_flush(thread_id))
        except RuntimeError:
            pass

    async def _delayed_flush(self, thread_id: str) -> None:
        await asyncio.sleep(self._debounce_seconds)
        await self.flush(thread_id)

    async def flush(self, thread_id: str) -> None:
        """立即处理指定 thread_id 的待处理更新"""
        async with self._lock:
            pending = self._pending.pop(thread_id, None)
            self._timers.pop(thread_id, None)
        if pending is None:
            return
        self._flush_count += 1
        logger.info("处理记忆更新: thread_id=%s, messages=%d", thread_id, len(pending.messages))
        if self._handler is not None:
            try:
                await self._handler(thread_id, pending.messages)
            except Exception:
                logger.exception("记忆更新处理失败: thread_id=%s", thread_id)

    def pending_count(self, thread_id: str | None = None) -> int:
        if thread_id is not None:
            p = self._pending.get(thread_id)
            return len(p.messages) if p else 0
        return sum(len(p.messages) for p in self._pending.values())

    def has_pending(self, thread_id: str) -> bool:
        return thread_id in self._pending
