"""按 thread 广播 AG-UI 事件，支持有限重放和慢消费者隔离。"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Callable

from src.agui.models import AGUIEvent, AGUIEventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StreamEvent:
    sequence: int
    event: AGUIEvent
    published_at: float


@dataclass
class StreamSubscription:
    thread_id: str
    subscriber_id: str
    queue: asyncio.Queue[StreamEvent]


class ThreadStreamHub:
    """每个订阅者使用独立 Queue；同一事件会广播给全部订阅者。"""

    def __init__(self, *, replay_size: int = 256,
                 subscriber_queue_size: int = 128) -> None:
        self._replay_size = replay_size
        self._queue_size = subscriber_queue_size
        self._sequences: dict[str, int] = defaultdict(int)
        self._replay: dict[str, deque[StreamEvent]] = {}
        self._subscribers: dict[str, dict[str, asyncio.Queue[StreamEvent]]] = {}
        self._lock = threading.RLock()

    async def publish(self, thread_id: str, event: AGUIEvent) -> StreamEvent:
        if not thread_id or not thread_id.strip():
            raise ValueError("thread_id is required")
        with self._lock:
            self._sequences[thread_id] += 1
            item = StreamEvent(self._sequences[thread_id], event, time.time())
            replay = self._replay.setdefault(
                thread_id, deque(maxlen=self._replay_size))
            replay.append(item)
            queues = list(self._subscribers.get(thread_id, {}).values())
            # Keep the replay sequence and folded reconnect state on the same
            # atomic boundary. Snapshot readers acquire this lock first.
            self._record_activity(thread_id, event)
        for queue in queues:
            self._put_latest(queue, item)
        return item

    async def publish_many(self, thread_id: str,
                           events: list[AGUIEvent]) -> list[StreamEvent]:
        return [await self.publish(thread_id, event) for event in events]

    async def subscribe(self, thread_id: str, *,
                        after_sequence: int | None = None) -> StreamSubscription:
        if not thread_id or not thread_id.strip():
            raise ValueError("thread_id is required")
        subscriber_id = uuid.uuid4().hex
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue(self._queue_size)
        with self._lock:
            subscribers = self._subscribers.setdefault(thread_id, {})
            subscribers[subscriber_id] = queue
            if after_sequence is not None:
                for item in self._replay.get(thread_id, ()):
                    if item.sequence > after_sequence:
                        self._put_latest(queue, item)
        return StreamSubscription(thread_id, subscriber_id, queue)

    async def unsubscribe(self, subscription: StreamSubscription) -> None:
        with self._lock:
            subscribers = self._subscribers.get(subscription.thread_id)
            if subscribers is None:
                return
            subscribers.pop(subscription.subscriber_id, None)
            if not subscribers:
                self._subscribers.pop(subscription.thread_id, None)

    def latest_sequence(self, thread_id: str) -> int:
        with self._lock:
            return self._sequences.get(thread_id, 0)

    def snapshot_with_boundary(
        self,
        thread_id: str,
        snapshot_provider: Callable[[], Any],
    ) -> tuple[Any, int]:
        """Read folded state and its exact replay boundary atomically."""
        with self._lock:
            snapshot = snapshot_provider()
            return snapshot, self._sequences.get(thread_id, 0)

    def clear(self) -> None:
        with self._lock:
            self._sequences.clear()
            self._replay.clear()
            self._subscribers.clear()

    @staticmethod
    def _put_latest(queue: asyncio.Queue[StreamEvent], item: StreamEvent) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            logger.warning("dropping oldest event for slow AG-UI subscriber")
        queue.put_nowait(item)

    @staticmethod
    def _record_activity(thread_id: str, event: AGUIEvent) -> None:
        event_type = getattr(event.type, "value", event.type)
        try:
            from .thread_store import thread_store
            if event_type in {
                    AGUIEventType.STATE_SNAPSHOT.value,
                    AGUIEventType.STATE_DELTA.value}:
                thread_store.record_state(
                    thread_id=thread_id,
                    event_type=str(event_type),
                    data=dict(event.data or {}),
                )
                return
            if event_type == AGUIEventType.ACTIVITY_DELTA.value:
                thread_store.patch_activity(
                    thread_id=thread_id,
                    message_id=str(event.data.get("message_id") or ""),
                    activity_type=str(event.data.get("activity_type") or "activity"),
                    patch=list(event.data.get("patch") or []),
                )
                return
            if event_type != AGUIEventType.ACTIVITY_SNAPSHOT.value:
                return
            thread_store.upsert_activity(
                thread_id=thread_id,
                message_id=str(event.data.get("message_id") or ""),
                activity_type=str(event.data.get("activity_type") or "activity"),
                content=dict(event.data.get("content") or {}),
                replace=bool(event.data.get("replace", True)),
            )
        except Exception:
            logger.exception("failed to record event for thread=%s", thread_id)


stream_hub = ThreadStreamHub()
