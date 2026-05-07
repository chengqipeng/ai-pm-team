"""A2UI 客户端入站消息解析与转发（v0.8 §5）

客户端通过 POST /agent/a2ui/event 回传两种消息：
- userAction — 用户交互事件
- error      — 客户端渲染/绑定错误

本模块职责：
1. 解析 payload → UserAction / ClientError
2. 合成 HumanMessage 注入 Agent（可选，供 Adapter 调用）
3. 简单幂等：以 (surface_id, source_component_id, timestamp) 做短时去重

业务侧约定：
- `userAction` 的 `name` 由 A2UI Builder 产出时指定（button.action.name）
- `context` 里的值已经由前端 resolve 了 BoundValue（§5.2）
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .models import ClientError, ClientEvent, UserAction

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 解析
# ═══════════════════════════════════════════════════════════

def parse_client_event(payload: dict) -> ClientEvent:
    """解析客户端消息 payload。

    Raises:
        ValueError: 未知消息类型 / 必填字段缺失
    """
    if not isinstance(payload, dict):
        raise ValueError(f"Payload must be dict, got {type(payload).__name__}")

    if "userAction" in payload:
        ua = payload["userAction"]
        if not isinstance(ua, dict):
            raise ValueError("userAction body must be object")
        missing = [k for k in ("name", "surfaceId", "sourceComponentId", "timestamp")
                   if k not in ua]
        if missing:
            raise ValueError(f"userAction missing fields: {missing}")
        return UserAction(
            name=ua["name"],
            surface_id=ua["surfaceId"],
            source_component_id=ua["sourceComponentId"],
            timestamp=str(ua["timestamp"]),
            context=dict(ua.get("context") or {}),
        )

    if "error" in payload:
        err = payload["error"]
        if not isinstance(err, dict):
            raise ValueError("error body must be object")
        return ClientError(
            message=str(err.get("message", "")),
            component_id=err.get("componentId"),
            surface_id=err.get("surfaceId"),
            extra={k: v for k, v in err.items()
                   if k not in {"message", "componentId", "surfaceId"}},
        )

    raise ValueError(f"Unknown A2UI client event: keys={list(payload.keys())}")


# ═══════════════════════════════════════════════════════════
# 幂等短时去重（同一交互事件在秒级重复只处理一次）
# ═══════════════════════════════════════════════════════════

@dataclass
class _DedupeEntry:
    fingerprint: str
    seen_at: float


class InboundDedupe:
    """LRU 风格的交互事件去重窗口。

    粒度：(surface_id, source_component_id, timestamp) — 前端发两次视为一次。
    窗口默认 30 秒，超出自然淘汰。
    """

    def __init__(self, *, window_seconds: float = 30.0, max_entries: int = 512) -> None:
        self._window = window_seconds
        self._max = max_entries
        self._entries: dict[str, _DedupeEntry] = {}

    @staticmethod
    def _fingerprint(ua: UserAction) -> str:
        return f"{ua.surface_id}|{ua.source_component_id}|{ua.timestamp}|{ua.name}"

    def is_duplicate(self, ua: UserAction) -> bool:
        now = time.time()
        self._evict(now)
        fp = self._fingerprint(ua)
        if fp in self._entries:
            return True
        # 追加
        self._entries[fp] = _DedupeEntry(fingerprint=fp, seen_at=now)
        if len(self._entries) > self._max:
            # 丢弃最早的一半
            victims = sorted(self._entries.items(), key=lambda kv: kv[1].seen_at)
            for k, _ in victims[: len(victims) // 2]:
                self._entries.pop(k, None)
        return False

    def _evict(self, now: float) -> None:
        limit = now - self._window
        to_drop = [k for k, v in self._entries.items() if v.seen_at < limit]
        for k in to_drop:
            self._entries.pop(k, None)


# ═══════════════════════════════════════════════════════════
# 转发：userAction → HumanMessage
# ═══════════════════════════════════════════════════════════

class A2UIInboundHandler:
    """解析 + 去重 + 转成 Agent 可消费的消息。"""

    def __init__(self, dedupe: InboundDedupe | None = None) -> None:
        self._dedupe = dedupe or InboundDedupe()

    def handle(self, payload: dict) -> ClientEvent | None:
        """主入口：解析并做幂等过滤。

        Returns:
            ClientEvent 实例；重复 UserAction 返回 None。
        """
        event = parse_client_event(payload)
        if isinstance(event, UserAction) and self._dedupe.is_duplicate(event):
            logger.info("duplicate userAction ignored: %s/%s/%s",
                        event.surface_id, event.source_component_id, event.timestamp)
            return None
        return event

    @staticmethod
    def to_human_message(ua: UserAction) -> Any:
        """把 UserAction 编码成一条 HumanMessage 注入 Agent。

        延迟 import `langchain_core`，避免模块加载时的重量级依赖。
        """
        try:
            from langchain_core.messages import HumanMessage
        except ImportError:  # pragma: no cover
            return {"role": "user", "content": _format_ua_text(ua)}
        return HumanMessage(
            content=_format_ua_text(ua),
            additional_kwargs={
                "ui_action": {
                    "name": ua.name,
                    "surface_id": ua.surface_id,
                    "source_component_id": ua.source_component_id,
                    "timestamp": ua.timestamp,
                    "context": ua.context,
                }
            },
        )


def _format_ua_text(ua: UserAction) -> str:
    """给 LLM 看的简洁文本，提醒这是一条 UI action 而非普通用户输入。"""
    ctx = json.dumps(ua.context, ensure_ascii=False) if ua.context else "{}"
    return f"[ui-action] {ua.name} on surface={ua.surface_id} context={ctx}"
