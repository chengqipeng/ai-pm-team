"""agent-system 内部业务记录服务及 A2UI 确定性 Action Handler。"""
from __future__ import annotations

import asyncio
import re
from typing import Any, TYPE_CHECKING

from src.agui.models import AGUIEvent, state_delta
from src.core.context import DEFAULT_TENANT_ID, get_context
from src.store.business_record_dao import BusinessRecordDAO
from src.tools.crm_backend import ENTITY_SCHEMAS
from .models import UserAction

if TYPE_CHECKING:
    from .action_dispatcher import ActionDispatcher

_ENTITY_ALIASES = {"customer": "account"}
_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,99}$")


class RecordActionError(ValueError):
    """可安全反馈给 UI 的业务动作错误。"""


class RecordActionService:
    """元数据校验、乐观锁与持久化均在 agent-system 内完成。"""

    def __init__(self, dao: type[BusinessRecordDAO] = BusinessRecordDAO) -> None:
        self._dao = dao

    @staticmethod
    def _identity() -> tuple[int, int]:
        ctx = get_context()
        tenant_id = int(ctx.tenant_id or DEFAULT_TENANT_ID)
        user_id = int(ctx.user_id) if str(ctx.user_id).isdigit() else 0
        return tenant_id, user_id

    @staticmethod
    def _entity(context: dict[str, Any]) -> str:
        raw = str(context.get("entityApiKey") or context.get("recordType") or "")
        entity = _ENTITY_ALIASES.get(raw, raw)
        if not _KEY_RE.fullmatch(entity) or entity not in ENTITY_SCHEMAS:
            raise RecordActionError(f"unsupported entityApiKey: {raw}")
        return entity

    @staticmethod
    def _record_key(context: dict[str, Any]) -> str:
        value = str(context.get("recordApiKey") or context.get("recordId") or "")
        if not value or len(value) > 128 or any(ch in value for ch in "\r\n"):
            raise RecordActionError("recordApiKey is required")
        return value

    @staticmethod
    def _schema(entity: str) -> dict[str, Any]:
        schema = ENTITY_SCHEMAS[entity]
        return {
            "entityApiKey": entity,
            "label": schema.get("label", entity),
            "fields": [
                {
                    "apiKey": item.get("api_key"),
                    "label": item.get("label", item.get("api_key")),
                    "type": item.get("item_type", "VARCHAR"),
                    "required": bool(item.get("required")),
                    "options": item.get("options", []),
                }
                for item in schema.get("items", [])
            ],
        }

    @staticmethod
    def _validate_data(entity: str, data: Any, *, partial: bool) -> dict[str, Any]:
        if not isinstance(data, dict) or not data:
            raise RecordActionError("data must be a non-empty object")
        if len(data) > 200:
            raise RecordActionError("too many fields")
        items = {item["api_key"]: item for item in ENTITY_SCHEMAS[entity].get("items", [])}
        allowed = set(items) | {"name"}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise RecordActionError(f"unknown fields: {unknown[:10]}")
        if not partial:
            missing = [item.get("api_key") for item in items.values()
                       if item.get("required") and not data.get(item.get("api_key"))]
            if missing:
                raise RecordActionError(f"required fields missing: {missing}")
        clean: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, str) and len(value) > 10000:
                raise RecordActionError(f"field too long: {key}")
            item_type = str(items.get(key, {}).get("item_type", "VARCHAR"))
            if value is not None and item_type in {"INTEGER"} and not isinstance(value, int):
                raise RecordActionError(f"field {key} must be integer")
            if value is not None and item_type in {"DECIMAL"} and not isinstance(value, (int, float)):
                raise RecordActionError(f"field {key} must be number")
            if value is not None and item_type == "BOOLEAN" and not isinstance(value, (bool, int)):
                raise RecordActionError(f"field {key} must be boolean")
            clean[key] = value
        return clean

    @staticmethod
    def _view_event(view_id: str, value: Any) -> AGUIEvent:
        safe_view = str(view_id or "default").replace("~", "~0").replace("/", "~1")
        return state_delta([{"op": "add", "path": f"/data/views/{safe_view}",
                             "value": value}])

    async def open_create(self, thread_id: str, action: UserAction):
        entity = self._entity(action.context)
        value = {"mode": "create", **self._schema(entity), "values": {}, "errors": {}}
        return [self._view_event(action.context.get("viewId") or f"{entity}:create", value)], value

    async def open_edit(self, thread_id: str, action: UserAction):
        tenant_id, _ = self._identity()
        entity, key = self._entity(action.context), self._record_key(action.context)
        record = await asyncio.to_thread(self._dao.get, tenant_id, entity, key)
        if record is None:
            raise RecordActionError("record not found")
        value = {"mode": "update", **self._schema(entity),
                 "recordApiKey": key, "version": record.version,
                 "values": record.data, "errors": {}}
        return [self._view_event(action.context.get("viewId") or f"{entity}:edit:{key}", value)], value

    async def view_record(self, thread_id: str, action: UserAction):
        tenant_id, _ = self._identity()
        entity, key = self._entity(action.context), self._record_key(action.context)
        record = await asyncio.to_thread(self._dao.get, tenant_id, entity, key)
        if record is None:
            raise RecordActionError("record not found")
        value = record.to_dict()
        return [self._view_event(action.context.get("viewId") or f"{entity}:detail:{key}", value)], value

    async def list_records(self, thread_id: str, action: UserAction):
        tenant_id, _ = self._identity()
        entity = self._entity(action.context)
        filters = action.context.get("filters") or {}
        if not isinstance(filters, dict) or len(filters) > 50:
            raise RecordActionError("invalid filters")
        page = max(1, int(action.context.get("page") or 1))
        page_size = min(100, max(1, int(action.context.get("pageSize") or 20)))
        records, total = await asyncio.to_thread(
            self._dao.list_records, tenant_id, entity, filters, page, page_size)
        value = {"entityApiKey": entity, "records": [r.to_dict() for r in records],
                 "page": page, "pageSize": page_size, "total": total}
        return [self._view_event(action.context.get("viewId") or f"{entity}:list", value)], value

    async def submit_create(self, thread_id: str, action: UserAction):
        tenant_id, user_id = self._identity()
        entity = self._entity(action.context)
        data = self._validate_data(entity, action.context.get("data"), partial=False)
        action_id = action.action_id or str(action.context.get("actionId") or "")
        if not action_id:
            raise RecordActionError("actionId is required")
        record = await asyncio.to_thread(
            self._dao.create, tenant_id, user_id, entity, data, action_id)
        value = record.to_dict()
        events = [self._view_event(
            action.context.get("viewId") or f"{entity}:detail:{record.record_api_key}", value)]
        return events, {"operation": "created", "record": value}

    async def submit_update(self, thread_id: str, action: UserAction):
        tenant_id, user_id = self._identity()
        entity, key = self._entity(action.context), self._record_key(action.context)
        changes = self._validate_data(entity, action.context.get("data"), partial=True)
        try:
            expected = int(action.context["expectedVersion"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RecordActionError("expectedVersion is required") from exc
        action_id = action.action_id or str(action.context.get("actionId") or "")
        try:
            record = await asyncio.to_thread(
                self._dao.update, tenant_id, user_id, entity, key,
                changes, expected, action_id)
        except RuntimeError as exc:
            raise RecordActionError(str(exc)) from exc
        value = record.to_dict()
        events = [self._view_event(
            action.context.get("viewId") or f"{entity}:detail:{key}", value)]
        return events, {"operation": "updated", "record": value}

    async def delete_record(self, thread_id: str, action: UserAction):
        if action.context.get("confirmed") is not True:
            raise RecordActionError("delete requires confirmed=true")
        tenant_id, user_id = self._identity()
        entity, key = self._entity(action.context), self._record_key(action.context)
        try:
            expected = int(action.context["expectedVersion"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RecordActionError("expectedVersion is required") from exc
        action_id = action.action_id or str(action.context.get("actionId") or "")
        try:
            deleted = await asyncio.to_thread(
                self._dao.soft_delete, tenant_id, user_id, entity, key,
                expected, action_id)
        except (LookupError, RuntimeError) as exc:
            raise RecordActionError(str(exc)) from exc
        value = {"entityApiKey": entity, "recordApiKey": key,
                 "deleted": True, "version": deleted.version}
        return [self._view_event(
            action.context.get("viewId") or f"{entity}:detail:{key}", value)], {
                "operation": "deleted", **value}

    async def field_change(self, thread_id: str, action: UserAction):
        entity = self._entity(action.context)
        field = str(action.context.get("field") or "")
        value = action.context.get("value")
        self._validate_data(entity, {field: value}, partial=True)
        form_id = str(action.context.get("formId") or "default")
        safe_form = form_id.replace("~", "~0").replace("/", "~1")
        safe_field = field.replace("~", "~0").replace("/", "~1")
        event = state_delta([{"op": "add",
                              "path": f"/data/forms/{safe_form}/fields/{safe_field}",
                              "value": value}])
        return [event], {"field": field, "valid": True}


def register_record_handlers(dispatcher: "ActionDispatcher",
                             service: RecordActionService | None = None) -> None:
    service = service or RecordActionService()
    dispatcher.register_handler("create_record", service.open_create)
    dispatcher.register_handler("edit_record", service.open_edit)
    dispatcher.register_handler("view_record", service.view_record)
    dispatcher.register_handler("refresh_view", service.list_records)
    dispatcher.register_handler("change_page", service.list_records,
                                chat_visibility="hidden")
    dispatcher.register_handler("field_change", service.field_change,
                                chat_visibility="hidden")
    dispatcher.register_handler("submit_create", service.submit_create,
                                chat_visibility="full", persist_chat=True)
    dispatcher.register_handler("submit_update", service.submit_update,
                                chat_visibility="full", persist_chat=True)
    dispatcher.register_handler("delete_record", service.delete_record,
                                chat_visibility="full")
