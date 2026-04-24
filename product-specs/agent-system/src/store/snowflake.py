"""简易雪花 ID 生成器 — 对齐平台 BIGINT 主键策略"""
from __future__ import annotations

import os
import time
import threading

_EPOCH = 1700000000000  # 2023-11-14 基准时间戳(ms)
_WORKER_BITS = 10
_SEQ_BITS = 12
_MAX_WORKER = (1 << _WORKER_BITS) - 1
_MAX_SEQ = (1 << _SEQ_BITS) - 1

_lock = threading.Lock()
_last_ts: int = 0
_seq: int = 0
_worker_id: int = int(os.environ.get("WORKER_ID", "1")) & _MAX_WORKER


def next_id() -> int:
    """生成全局唯一的雪花 ID"""
    global _last_ts, _seq
    with _lock:
        ts = int(time.time() * 1000)
        if ts == _last_ts:
            _seq = (_seq + 1) & _MAX_SEQ
            if _seq == 0:
                while ts <= _last_ts:
                    ts = int(time.time() * 1000)
        else:
            _seq = 0
        _last_ts = ts
        return ((ts - _EPOCH) << (_WORKER_BITS + _SEQ_BITS)) | (_worker_id << _SEQ_BITS) | _seq
