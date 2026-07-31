"""Process-local run admission control for the standard AG-UI endpoint."""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

RunAdmission = Literal["started", "duplicate", "conflict"]


@dataclass(frozen=True)
class RunRecord:
    thread_id: str
    run_id: str
    status: Literal["running", "finished"]


class RunRegistry:
    """Prevent duplicate execution and concurrent runs on one thread.

    This is intentionally process-local for phase one.  The interface can be
    backed by Redis later without changing the HTTP protocol boundary.
    """

    def __init__(self, *, completed_limit: int = 2048) -> None:
        self._completed_limit = completed_limit
        self._active_by_thread: dict[str, str] = {}
        self._completed: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._lock = threading.RLock()

    def start(self, thread_id: str, run_id: str) -> RunAdmission:
        key = (thread_id, run_id)
        with self._lock:
            if key in self._completed:
                self._completed.move_to_end(key)
                return "duplicate"
            active = self._active_by_thread.get(thread_id)
            if active == run_id:
                return "duplicate"
            if active is not None:
                return "conflict"
            self._active_by_thread[thread_id] = run_id
            return "started"

    def finish(self, thread_id: str, run_id: str) -> None:
        key = (thread_id, run_id)
        with self._lock:
            if self._active_by_thread.get(thread_id) == run_id:
                self._active_by_thread.pop(thread_id, None)
            self._completed[key] = None
            self._completed.move_to_end(key)
            while len(self._completed) > self._completed_limit:
                self._completed.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._active_by_thread.clear()
            self._completed.clear()


run_registry = RunRegistry()
