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
import re
import threading
from copy import deepcopy
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import jsonpatch

from .aggregator import SnapshotAggregator

logger = logging.getLogger(__name__)


def infer_user_requested_views(
    message: str,
    business_context: dict[str, Any] | None = None,
) -> tuple[list[str], str]:
    """从用户原始意图推断允许展示的 CRM view；Skill 内部查询不在此授权。"""
    text = str(message or "").strip()
    business = business_context or {}
    if (
        business.get("intent") == "customer_insight"
        or re.search(r"客户洞察|customer[_\s-]*insight|洞察\s*Skill", text, re.I)
    ):
        return [], "customer_insight"

    specific_entities = [
        entity
        for entity, pattern in (
            ("opportunity", r"商机|opportunit|pipeline"),
            ("contact", r"联系人|contact"),
            ("activity", r"活动|activity"),
            ("lead", r"线索|lead"),
        )
        if re.search(pattern, text, re.I)
    ]
    entities = specific_entities
    if not entities and re.search(r"客户|账户|account|customer", text, re.I):
        entities = ["account"]
    if not entities:
        return [], ""

    detail_intent = bool(re.search(
        r"详情|详细|记录标识|record\s*(?:api\s*)?key", text, re.I))
    create_intent = bool(re.search(r"新建|创建|新增|create|add", text, re.I))
    edit_intent = bool(re.search(r"编辑|修改|更新|edit|update", text, re.I))
    list_intent = not (detail_intent or create_intent or edit_intent) and bool(
        re.search(r"列表|查询|查找|搜索|检索|列出|展示|查看|有哪些|list|search|query|find", text, re.I))

    requested: list[str] = []
    for entity in entities:
        if create_intent:
            requested.append(f"{entity}:create")
        elif edit_intent:
            requested.extend((f"{entity}:edit:*", f"{entity}:update:*"))
        elif detail_intent:
            match = re.search(
                r"(?:CRM\s*)?记录标识[：:]\s*([A-Za-z0-9][A-Za-z0-9_.:-]{0,127})",
                text,
                re.I,
            )
            requested.append(
                f"{entity}:detail:{match.group(1)}" if match
                else f"{entity}:detail:*")
        elif list_intent:
            requested.append(f"{entity}:list")
    return requested, "crm_query" if requested else ""


@dataclass
class ThreadState:
    """单个 thread 的有界重连快照。仅由 ThreadStore 在锁内修改。"""
    thread_id: str
    aggregator: SnapshotAggregator | None = None
    last_run_id: str | None = None
    messages: list[dict] = field(default_factory=list)
    shared_state: dict[str, Any] = field(default_factory=dict)
    activities: OrderedDict[str, dict[str, Any]] = field(default_factory=OrderedDict)
    surface_message_ids: dict[str, str] = field(default_factory=dict)
    context_artifacts: list[dict[str, Any]] = field(default_factory=list)
    context_artifact_sequence: int = 0
    user_requested_views: set[str] = field(default_factory=set)
    active_user_view_scopes: dict[str, dict[str, Any]] = field(default_factory=dict)

    @staticmethod
    def _view_matches(view_id: str, pattern: str) -> bool:
        return (
            view_id.startswith(pattern[:-1])
            if pattern.endswith("*")
            else view_id == pattern
        )

    def begin_user_view_scope(
        self,
        scope_id: str,
        view_patterns: list[str],
        origin_intent: str = "",
    ) -> None:
        normalized = [str(item).strip() for item in view_patterns if str(item).strip()]
        self.active_user_view_scopes[scope_id] = {
            "patterns": normalized,
            "originIntent": str(origin_intent or ""),
        }
        self.user_requested_views.update(
            item for item in normalized if "*" not in item)

    def end_user_view_scope(self, scope_id: str) -> None:
        self.active_user_view_scopes.pop(scope_id, None)

    def _active_user_view_origin(self, view_id: str) -> str:
        for scope in reversed(list(self.active_user_view_scopes.values())):
            if any(self._view_matches(view_id, pattern)
                   for pattern in scope.get("patterns", [])):
                self.user_requested_views.add(view_id)
                return str(scope.get("originIntent") or "crm_query")
        return ""

    def current_origin_intent(self) -> str:
        for scope in reversed(list(self.active_user_view_scopes.values())):
            intent = str(scope.get("originIntent") or "")
            if intent:
                return intent
        return ""

    def record_activity(self, render_type: str, operations: list[dict]) -> None:
        if not operations:
            return
        message_id = self.surface_message_ids.setdefault(
            render_type, f"a2ui-{self.thread_id[:8]}-{render_type}")
        surface_id = f"surface-{render_type}"
        if self.aggregator is not None:
            surface_id = self.aggregator._panel_surface_map.get(  # type: ignore[attr-defined]
                render_type, surface_id)
        self.upsert_activity(
            message_id, "a2ui-surface",
            {"render_type": render_type, "surface_id": surface_id,
             "operations": list(operations)},
            replace=True,
        )

    def upsert_activity(self, message_id: str, activity_type: str,
                        content: dict[str, Any], replace: bool = True) -> None:
        if not message_id:
            raise ValueError("activity message_id is required")
        normalized_content = dict(content)
        render_type = normalized_content.get("render_type")
        if activity_type == "a2ui-surface" and render_type:
            surface_id = f"surface-{render_type}"
            if self.aggregator is not None:
                surface_id = self.aggregator._panel_surface_map.get(  # type: ignore[attr-defined]
                    render_type, surface_id)
            normalized_content.setdefault("surface_id", surface_id)
            self.surface_message_ids[str(render_type)] = message_id
        self.activities[message_id] = {
            "message_id": message_id,
            "activity_type": activity_type,
            "replace": replace,
            "content": normalized_content,
        }
        self.activities.move_to_end(message_id)

    def patch_activity(self, message_id: str, activity_type: str,
                       patch: list[dict[str, Any]]) -> None:
        """Fold an ACTIVITY_DELTA into the latest reconnect snapshot."""
        if not message_id or not patch:
            return
        current = self.activities.get(message_id)
        if current is None:
            logger.warning(
                "ignoring ACTIVITY_DELTA without snapshot: thread=%s message=%s",
                self.thread_id, message_id,
            )
            return
        try:
            content = jsonpatch.apply_patch(
                deepcopy(current.get("content") or {}), patch, in_place=False)
        except jsonpatch.JsonPatchException:
            logger.exception(
                "invalid ACTIVITY_DELTA: thread=%s message=%s",
                self.thread_id, message_id,
            )
            return
        self.upsert_activity(
            message_id,
            activity_type or str(current.get("activity_type") or "activity"),
            content,
            replace=bool(current.get("replace", True)),
        )

    @staticmethod
    def _pointer_parts(path: str) -> list[str]:
        return [part.replace("~1", "/").replace("~0", "~")
                for part in str(path or "").split("/")[1:]]

    def _record_view_artifact(self, view_id: str, value: Any) -> None:
        """保存每个不同数据视图版本，供刷新后恢复完整会话产物链路。"""
        import hashlib
        import json
        import time

        if not view_id or not isinstance(value, (dict, list)):
            return
        serialized = json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), default=str,
        )
        digest = hashlib.sha256(
            f"{view_id}\0{serialized}".encode("utf-8")).hexdigest()
        signature = f"{view_id}:{digest}"
        origin_intent = self._active_user_view_origin(view_id)
        user_triggered = bool(origin_intent)
        existing = next(
            (item for item in self.context_artifacts
             if item.get("signature") == signature),
            None,
        )
        if existing is not None:
            # 相同值可能先由 Skill 内部查询产生，后又被用户明确请求；
            # 此时升级来源标记，而不是永久保留为内部产物。
            if user_triggered:
                existing["userTriggered"] = True
                existing["originIntent"] = origin_intent
            return
        self.context_artifact_sequence += 1
        self.context_artifacts.append({
            "id": f"data-{digest[:20]}",
            "type": "data",
            "viewId": view_id,
            "value": deepcopy(value),
            "timestamp": int(time.time() * 1000),
            "sequence": self.context_artifact_sequence,
            "signature": signature,
            "userTriggered": user_triggered,
            "originIntent": origin_intent,
        })
        if len(self.context_artifacts) > 200:
            del self.context_artifacts[:-200]

    def _record_snapshot_views(self) -> None:
        views = ((self.shared_state.get("data") or {}).get("views") or {})
        if isinstance(views, dict):
            for view_id, value in views.items():
                self._record_view_artifact(str(view_id), value)

    def record_state(self, event_type: str, data: dict[str, Any]) -> None:
        """持久化 STATE_SNAPSHOT/DELTA，供浏览器刷新后 reconnect 恢复。"""
        if event_type == "STATE_SNAPSHOT":
            self.shared_state = deepcopy(data.get("snapshot") or {})
            self._record_snapshot_views()
            return
        if event_type != "STATE_DELTA":
            return
        patch_ops = list(data.get("delta") or [])
        if not patch_ops:
            return
        try:
            self.shared_state = jsonpatch.apply_patch(
                deepcopy(self.shared_state), patch_ops, in_place=False)
        except jsonpatch.JsonPatchException:
            # Keep the previous valid snapshot. Applying a partial patch would
            # make every later delta use an invalid base.
            logger.exception(
                "invalid STATE_DELTA: thread=%s operations=%s",
                self.thread_id, len(patch_ops),
            )
            return
        self._record_snapshot_views()

    def snapshot_state(self) -> dict | None:
        if self.shared_state:
            snapshot = deepcopy(self.shared_state)
        elif self.aggregator is not None:
            snapshot = self.aggregator.get_snapshot()
        else:
            snapshot = None
        if snapshot is None:
            return None
        if self.context_artifacts:
            snapshot["contextArtifacts"] = deepcopy(self.context_artifacts)
        if self.user_requested_views:
            snapshot["userTriggeredViewIds"] = sorted(self.user_requested_views)
        return snapshot

    def active_activities(self) -> list[dict]:
        return [dict(activity) for activity in self.activities.values()]


class ThreadStore:
    """内存 thread 状态注册表。"""

    def __init__(self, *, max_messages: int = 200,
                 max_activities: int = 100) -> None:
        self._threads: dict[str, ThreadState] = {}
        self._lock = threading.RLock()
        self._max_messages = max_messages
        self._max_activities = max_activities

    def _ensure_locked(self, thread_id: str) -> ThreadState:
        state = self._threads.get(thread_id)
        if state is None:
            state = ThreadState(thread_id=thread_id)
            self._threads[thread_id] = state
        return state

    def get(self, thread_id: str) -> ThreadState | None:
        with self._lock:
            return self._threads.get(thread_id)

    def ensure(self, thread_id: str) -> ThreadState:
        with self._lock:
            return self._ensure_locked(thread_id)

    def delete(self, thread_id: str) -> None:
        with self._lock:
            self._threads.pop(thread_id, None)

    def bind_aggregator(self, thread_id: str, aggregator: SnapshotAggregator) -> None:
        with self._lock:
            self._ensure_locked(thread_id).aggregator = aggregator

    def set_last_run(self, thread_id: str, run_id: str) -> None:
        with self._lock:
            self._ensure_locked(thread_id).last_run_id = run_id

    def begin_user_view_scope(
        self,
        thread_id: str,
        scope_id: str,
        view_patterns: list[str],
        origin_intent: str = "",
    ) -> None:
        with self._lock:
            self._ensure_locked(thread_id).begin_user_view_scope(
                scope_id, view_patterns, origin_intent)

    def end_user_view_scope(self, thread_id: str, scope_id: str) -> None:
        with self._lock:
            state = self._threads.get(thread_id)
            if state is not None:
                state.end_user_view_scope(scope_id)

    def record_state(self, thread_id: str, event_type: str,
                     data: dict[str, Any]) -> None:
        with self._lock:
            self._ensure_locked(thread_id).record_state(event_type, data)

    def record_activity(self, thread_id: str, render_type: str,
                        operations: list[dict]) -> None:
        with self._lock:
            state = self._ensure_locked(thread_id)
            state.record_activity(render_type, operations)
            self._trim_activities(state)

    def upsert_activity(self, thread_id: str, message_id: str,
                        activity_type: str, content: dict[str, Any],
                        replace: bool = True) -> None:
        with self._lock:
            state = self._ensure_locked(thread_id)
            state.upsert_activity(
                message_id, activity_type, content, replace=replace)
            self._trim_activities(state)

    def patch_activity(self, thread_id: str, message_id: str,
                       activity_type: str,
                       patch: list[dict[str, Any]]) -> None:
        with self._lock:
            state = self._ensure_locked(thread_id)
            state.patch_activity(message_id, activity_type, patch)
            self._trim_activities(state)

    def append_message(self, thread_id: str, message: dict) -> None:
        with self._lock:
            state = self._ensure_locked(thread_id)
            state.messages.append(dict(message))
            if len(state.messages) > self._max_messages:
                del state.messages[:-self._max_messages]

    def upsert_message(self, thread_id: str, message: dict) -> None:
        """按稳定 message.id 幂等写入；无 id 的普通流消息保持 append 语义。"""
        message_id = str(message.get("id") or "")
        if not message_id:
            self.append_message(thread_id, message)
            return
        with self._lock:
            state = self._ensure_locked(thread_id)
            normalized = dict(message)
            for index, existing in enumerate(state.messages):
                if str(existing.get("id") or "") == message_id:
                    state.messages[index] = normalized
                    return
            state.messages.append(normalized)
            if len(state.messages) > self._max_messages:
                del state.messages[:-self._max_messages]

    def snapshot_bundle(self, thread_id: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._threads.get(thread_id)
            if state is None:
                return None
            return {
                "messages": [dict(message) for message in state.messages],
                "state": state.snapshot_state(),
                "activities": state.active_activities(),
                "last_run_id": state.last_run_id,
            }

    def clear(self) -> None:
        with self._lock:
            self._threads.clear()

    def _trim_activities(self, state: ThreadState) -> None:
        while len(state.activities) > self._max_activities:
            message_id, activity = state.activities.popitem(last=False)
            render_type = activity.get("content", {}).get("render_type")
            if render_type and state.surface_message_ids.get(render_type) == message_id:
                state.surface_message_ids.pop(render_type, None)


# 全局单例（测试里可通过 reset_for_tests 清空）
thread_store = ThreadStore()


def reset_for_tests() -> None:  # pragma: no cover — 仅测试使用
    """原地清空，保证 `from src.a2ui import thread_store` 引用仍有效。"""
    thread_store.clear()
    try:
        from .stream_hub import stream_hub
        stream_hub.clear()
    except ImportError:
        pass
