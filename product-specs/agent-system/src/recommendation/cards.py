"""推荐卡片模型与 per-thread 存储"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RecommendationCard:
    """单张推荐卡片"""
    card_id: str
    title: str
    icon: str = "💡"
    reason: str = ""
    command: str = ""  # 点击后发送到 Agent 的指令
    deadline: str = ""  # "建议X日前完成"
    priority: int = 3  # 1 (highest) - 5
    category: str = "action_suggestion"  # action_suggestion | reminder | insight
    status: str = "pending"  # pending | adopted | dismissed
    created_at: int = 0
    expires_at: int = 0  # 0 = never
    dedup_key: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = int(time.time() * 1000)
        if not self.dedup_key:
            self.dedup_key = hashlib.md5(
                f"{self.category}:{self.command}".encode()).hexdigest()[:16]
        if not self.card_id:
            self.card_id = f"card-{self.dedup_key}-{self.created_at}"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "cardId": self.card_id,
            "title": self.title,
            "icon": self.icon,
            "command": self.command,
            "priority": self.priority,
            "category": self.category,
            "status": self.status,
            "createdAt": self.created_at,
        }
        if self.reason:
            out["reason"] = self.reason
        if self.deadline:
            out["deadline"] = self.deadline
        return out


class CardStore:
    """per-thread 推荐卡片管理"""

    def __init__(self, *, max_per_thread: int = 20, max_threads: int = 512) -> None:
        self._max_per_thread = max_per_thread
        self._max_threads = max_threads
        self._stores: OrderedDict[str, list[RecommendationCard]] = OrderedDict()
        self._dismissed: dict[str, set[str]] = {}  # thread_id → dismissed dedup_keys
        self._lock = threading.RLock()

    def get(self, thread_id: str) -> list[RecommendationCard]:
        with self._lock:
            return list(self._stores.get(thread_id, []))

    def merge(self, thread_id: str, candidates: list[RecommendationCard]) -> list[RecommendationCard]:
        """合并新候选，去重、排序并保留 top N"""
        with self._lock:
            existing = self._stores.get(thread_id, [])
            dismissed = self._dismissed.get(thread_id, set())
            existing_keys = {c.dedup_key for c in existing}

            added: list[RecommendationCard] = []
            for card in candidates:
                if card.dedup_key in existing_keys:
                    continue
                if card.dedup_key in dismissed:
                    continue
                if card.expires_at and card.expires_at < int(time.time() * 1000):
                    continue
                existing.append(card)
                existing_keys.add(card.dedup_key)
                added.append(card)

            # 清理过期
            now = int(time.time() * 1000)
            existing = [c for c in existing
                        if c.status == "pending" and (not c.expires_at or c.expires_at > now)]

            # 按优先级排序
            existing.sort(key=lambda c: (c.priority, -c.created_at))
            existing = existing[:self._max_per_thread]

            self._stores[thread_id] = existing
            self._stores.move_to_end(thread_id)
            if len(self._stores) > self._max_threads:
                self._stores.popitem(last=False)

            return added

    def dismiss(self, thread_id: str, card_id: str) -> None:
        with self._lock:
            cards = self._stores.get(thread_id, [])
            for card in cards:
                if card.card_id == card_id:
                    card.status = "dismissed"
                    self._dismissed.setdefault(thread_id, set()).add(card.dedup_key)
                    break
            self._stores[thread_id] = [c for c in cards if c.status == "pending"]

    def adopt(self, thread_id: str, card_id: str) -> RecommendationCard | None:
        with self._lock:
            cards = self._stores.get(thread_id, [])
            adopted = None
            for card in cards:
                if card.card_id == card_id:
                    card.status = "adopted"
                    adopted = card
                    break
            self._stores[thread_id] = [c for c in cards if c.status == "pending"]
            return adopted

    def get_serialized(self, thread_id: str) -> list[dict[str, Any]]:
        """获取可序列化为 Shared State 的卡片列表"""
        cards = self.get(thread_id)
        return [c.to_dict() for c in cards if c.status == "pending"]

    def clear(self, thread_id: str | None = None) -> None:
        with self._lock:
            if thread_id:
                self._stores.pop(thread_id, None)
                self._dismissed.pop(thread_id, None)
            else:
                self._stores.clear()
                self._dismissed.clear()


card_store = CardStore()
