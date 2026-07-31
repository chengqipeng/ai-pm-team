"""A2UI UserAction 的白名单调度与即时 Agent Run。"""
from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from src.agui.models import AGUIEvent, AGUIEventType, messages_snapshot
from .action_messages import (
    NormalizedAction,
    normalize_action,
    ui_action_activity,
    ui_action_chat_messages,
)
from .inbound import A2UIInboundHandler
from .models import UserAction
from .stream_hub import ThreadStreamHub, stream_hub

logger = logging.getLogger(__name__)
ActionHandler = Callable[[str, UserAction], Awaitable[Any] | Any]


class ActionDispatchError(ValueError):
    """Action envelope 或注册状态不合法。"""


class UnknownActionError(ActionDispatchError):
    """未注册动作，禁止默认放行。"""


class ActionRunError(RuntimeError):
    """动作执行失败。"""


@dataclass(frozen=True)
class ActionDefinition:
    name: str
    mode: str = "deterministic"
    chat_visibility: str = "compact"
    persist_chat: bool = False


class ActionDispatcher:
    """确定性动作走 handler；语义动作才允许进入 Agent。"""

    def __init__(self, hub: ThreadStreamHub | None = None,
                 adapter_provider: Callable[[], Any] | None = None) -> None:
        self._hub = hub or stream_hub
        self._adapter_provider = adapter_provider or self._default_adapter
        self._definitions: dict[str, ActionDefinition] = {}
        self._handlers: dict[str, ActionHandler] = {}
        self._seen: dict[tuple[str, str], str] = {}
        self._state_lock = threading.RLock()
        self._thread_locks: dict[tuple[int, str], asyncio.Lock] = {}
        self._tasks: set[asyncio.Task] = set()
        for name in ("analyze_record", "explain_record",
                     "generate_suggestion", "ask_agent"):
            self.register_agent_action(name)

    @staticmethod
    def _default_adapter() -> Any:
        from src.agents.adapter import neo_agent_v2_adapter
        return neo_agent_v2_adapter

    def register_handler(self, name: str, handler: ActionHandler, *,
                         chat_visibility: str = "compact",
                         persist_chat: bool = False) -> None:
        self._definitions[name] = ActionDefinition(
            name=name, mode="deterministic", chat_visibility=chat_visibility,
            persist_chat=persist_chat)
        self._handlers[name] = handler

    def register_agent_action(self, name: str, *,
                              chat_visibility: str = "agent") -> None:
        self._definitions[name] = ActionDefinition(
            name=name, mode="agent", chat_visibility=chat_visibility)

    async def dispatch(self, thread_id: str, action: UserAction) -> dict[str, str]:
        definition = self._definitions.get(action.name)
        if definition is None:
            raise UnknownActionError(f"unregistered userAction: {action.name}")
        try:
            normalized = normalize_action(
                thread_id, action, visibility=definition.chat_visibility)
        except ValueError as exc:
            raise ActionDispatchError(str(exc)) from exc

        key = (normalized.thread_id, normalized.action_id)
        with self._state_lock:
            prior = self._seen.get(key)
            if prior is not None:
                return {"status": "duplicate", "actionId": normalized.action_id,
                        "phase": prior}
            self._seen[key] = "accepted"

        if normalized.chat_visibility != "hidden":
            await self._hub.publish(thread_id, ui_action_activity(
                normalized, "accepted", status_text="已接收"))

        # 后续 Service/Agent 与 Chat Activity 共享同一个规范化 actionId。
        action.action_id = normalized.action_id
        task = asyncio.create_task(
            self._run(normalized, action, definition),
            name=f"a2ui-action-{normalized.action_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return {"status": "accepted", "actionId": normalized.action_id,
                "phase": "accepted"}

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            logger.exception("A2UI action background task failed")

    async def _run(self, normalized: NormalizedAction, action: UserAction,
                   definition: ActionDefinition) -> None:
        loop_key = (id(asyncio.get_running_loop()), normalized.thread_id)
        with self._state_lock:
            lock = self._thread_locks.setdefault(loop_key, asyncio.Lock())
        context = action.context or {}
        entity = str(context.get("entityApiKey") or "account")
        record_key = str(context.get("recordApiKey") or "")
        view_patterns: list[str] = []
        if context.get("viewId"):
            view_patterns.append(str(context["viewId"]))
        if action.name == "refresh_view":
            view_patterns.append(f"{entity}:list")
        elif action.name == "view_record" and record_key:
            view_patterns.append(f"{entity}:detail:{record_key}")
        elif action.name == "edit_record" and record_key:
            view_patterns.append(f"{entity}:edit:{record_key}")
        elif action.name == "submit_create":
            view_patterns.append(f"{entity}:detail:*")
        elif action.name in {"submit_update", "delete_record"} and record_key:
            view_patterns.append(f"{entity}:detail:{record_key}")

        from .thread_store import thread_store
        scope_id = f"action:{normalized.action_id}"
        async with lock:
            thread_store.begin_user_view_scope(
                normalized.thread_id,
                scope_id,
                view_patterns,
                f"crm_ui_{action.name}",
            )
            try:
                await self._set_phase(normalized, "running")
                if normalized.chat_visibility != "hidden":
                    await self._hub.publish(normalized.thread_id, ui_action_activity(
                        normalized, "running", status_text="正在处理…"))
                if definition.mode == "agent":
                    result = await self._run_agent(normalized.thread_id, action)
                else:
                    handler = self._handlers.get(action.name)
                    if handler is None:
                        raise ActionRunError(
                            f"handler not configured for action: {action.name}")
                    result = await self._run_handler(
                        handler, normalized.thread_id, action)
                if definition.persist_chat:
                    await self._persist_chat_exchange(normalized, result)
                await self._set_phase(normalized, "succeeded")
                if normalized.chat_visibility != "hidden":
                    await self._hub.publish(normalized.thread_id, ui_action_activity(
                        normalized, "succeeded", status_text="处理完成",
                        result=result))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("userAction failed: %s", action.name)
                await self._set_phase(normalized, "failed")
                if normalized.chat_visibility != "hidden":
                    await self._hub.publish(normalized.thread_id, ui_action_activity(
                        normalized, "failed", status_text="处理失败",
                        error={"code": type(exc).__name__}))
            finally:
                thread_store.end_user_view_scope(
                    normalized.thread_id, scope_id)

    async def _persist_chat_exchange(
        self, normalized: NormalizedAction, result: dict[str, Any]
    ) -> None:
        user_message, assistant_message = ui_action_chat_messages(
            normalized, result)
        pair_key = f"ui-action:{normalized.action_id}"
        if len(pair_key) > 64:
            import hashlib
            pair_key = "ui-action:" + hashlib.sha256(
                normalized.action_id.encode("utf-8")).hexdigest()[:48]

        # 数据库历史用于进程重启恢复；写入失败时仍保留 ThreadStore 实时上下文，
        # 避免业务记录已成功但 UI 被误报为保存失败。
        try:
            from src.core.context import get_context
            from src.store.trace_writer import TraceWriter
            current = get_context()
            writer = TraceWriter(tenant_id=int(current.tenant_id))
            await asyncio.to_thread(
                writer.persist_external_exchange,
                normalized.thread_id,
                pair_key,
                user_message["content"],
                assistant_message["content"],
                assistant_message["metadata"],
            )
        except Exception:
            logger.exception(
                "persist UI action exchange failed: %s", normalized.action_id)

        from .thread_store import thread_store
        thread_store.upsert_message(normalized.thread_id, user_message)
        thread_store.upsert_message(normalized.thread_id, assistant_message)

        # 下一轮 Agent 原子消费该消息对，使页面操作结果不仅可见/可恢复，
        # 也直接进入 LangGraph 会话上下文；稳定 message id 便于下游去重。
        try:
            from langchain_core.messages import AIMessage, HumanMessage
            adapter = self._adapter_provider()
            if hasattr(adapter, "inject_message"):
                adapter.inject_message(
                    normalized.thread_id,
                    HumanMessage(
                        content=user_message["content"], id=user_message["id"]),
                    source="ui-action",
                )
                adapter.inject_message(
                    normalized.thread_id,
                    AIMessage(
                        content=assistant_message["content"],
                        id=assistant_message["id"]),
                    source="ui-action",
                )
        except Exception:
            logger.exception(
                "inject UI action exchange failed: %s", normalized.action_id)

        bundle = thread_store.snapshot_bundle(normalized.thread_id)
        await self._hub.publish(normalized.thread_id, messages_snapshot(
            bundle["messages"] if bundle else [user_message, assistant_message]))

    async def _set_phase(self, action: NormalizedAction, phase: str) -> None:
        with self._state_lock:
            self._seen[(action.thread_id, action.action_id)] = phase

    async def _run_handler(self, handler: ActionHandler, thread_id: str,
                           action: UserAction) -> dict[str, Any]:
        output = handler(thread_id, action)
        if inspect.isawaitable(output):
            output = await output
        events: list[AGUIEvent] = []
        result: dict[str, Any] = {}
        if isinstance(output, tuple) and len(output) == 2:
            events, result = output
        elif isinstance(output, list):
            events = output
        elif isinstance(output, dict):
            result = output
        elif output is not None:
            raise ActionRunError("action handler returned unsupported result")
        if events:
            await self._hub.publish_many(thread_id, events)
        return result

    async def _run_agent(self, thread_id: str,
                         action: UserAction) -> dict[str, Any]:
        adapter = self._adapter_provider()
        message = A2UIInboundHandler.to_human_message(action)
        saw_error = False
        async for event in adapter.execute_agui(
                thread_id=thread_id, user_input="",
                injected_messages=[message]):
            await self._hub.publish(thread_id, event)
            event_type = getattr(event.type, "value", event.type)
            if event_type == AGUIEventType.RUN_ERROR.value:
                saw_error = True
        if saw_error:
            raise ActionRunError("Agent run returned RUN_ERROR")
        return {"mode": "agent", "action": action.name}

    def clear(self) -> None:
        with self._state_lock:
            self._seen.clear()
            self._thread_locks.clear()


action_dispatcher = ActionDispatcher()

# agent-system 内部确定性业务 Handler；导入时只注册，不连接数据库。
from .record_action_service import register_record_handlers
register_record_handlers(action_dispatcher)
