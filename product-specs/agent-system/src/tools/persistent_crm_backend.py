"""基于 agent-system PostgreSQL 的 CRM backend，供 Agent Tool 与页面 Action 共用。"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from src.a2ui.record_action_service import RecordActionService, RecordActionError
from src.a2ui.stream_hub import stream_hub
from src.agui.models import state_delta
from src.core.context import DEFAULT_TENANT_ID, get_context
from src.store.business_record_dao import BusinessRecordDAO
from .crm_backend import ENTITY_SCHEMAS


class PersistentCrmBackend:
    def __init__(self, dao: type[BusinessRecordDAO] = BusinessRecordDAO) -> None:
        self._dao = dao

    @staticmethod
    def _identity() -> tuple[int, int]:
        ctx = get_context()
        tenant_id = int(ctx.tenant_id or DEFAULT_TENANT_ID)
        user_id = int(ctx.user_id) if str(ctx.user_id).isdigit() else 0
        return tenant_id, user_id

    @staticmethod
    async def _publish_view(view_id: str, value: dict[str, Any]) -> None:
        """把 Agent Tool 结果同步到同一 thread 的真实业务页面。"""
        thread_id = str(get_context().thread_id or "").strip()
        if not thread_id:
            return
        safe_view = view_id.replace("~", "~0").replace("/", "~1")
        await stream_hub.publish(thread_id, state_delta([{
            "op": "add", "path": f"/data/views/{safe_view}", "value": value,
        }]))

    async def query_metadata(self, query_type: str, **params) -> dict:
        entity = params.get("entity_api_key", "")
        item_key = params.get("item_api_key", "")
        if query_type == "list_entities":
            return {"data": [{"api_key": key, "label": value.get("label", key)}
                             for key, value in ENTITY_SCHEMAS.items()]}
        if query_type == "entity_pick_options":
            for candidate in ENTITY_SCHEMAS.values():
                for item in candidate.get("items", []):
                    if item.get("api_key") == item_key:
                        return {"data": item.get("options", [])}
            return {"data": [], "error": f"字段 {item_key} 不存在或没有选项值"}
        if entity not in ENTITY_SCHEMAS:
            return {"data": {}, "error": f"实体 {entity} 不存在"}
        schema = ENTITY_SCHEMAS[entity]
        if query_type == "entity":
            return {"data": schema}
        if query_type == "entity_items":
            return {"data": schema.get("items", [])}
        if query_type == "entity_links":
            return {"data": schema.get("links", [])}
        return {"data": {}, "error": f"未知元数据查询: {query_type}"}

    async def query_data(self, entity: str, filters: dict | None = None, **kw) -> dict:
        if entity not in ENTITY_SCHEMAS:
            return {"data": {"records": [], "total": 0},
                    "error": f"实体 {entity} 不存在"}
        tenant_id, _ = self._identity()
        filters = dict(filters or {})
        name_field = {
            "account": "accountName",
            "opportunity": "opportunityName",
            "contact": "contactName",
            "lead": "leadName",
        }.get(entity, "name")
        if "name" in filters and name_field != "name":
            filters[name_field] = filters.pop("name")
        if "name__contains" in filters and name_field != "name":
            filters[f"{name_field}__contains"] = filters.pop("name__contains")
        record_key = filters.pop("id", None) or filters.pop("recordApiKey", None)
        if record_key is not None:
            record = await asyncio.to_thread(
                self._dao.get, tenant_id, entity, str(record_key))
            values = [record.to_dict()] if record else []
            payload = {"records": values, "total": len(values)}
            if record is not None:
                await self._publish_view(
                    f"{entity}:detail:{record.record_api_key}", values[0])
            return {"data": payload}

        contains = {key[:-10]: value for key, value in filters.items()
                    if key.endswith("__contains")}
        exact = {key: value for key, value in filters.items()
                 if not key.endswith("__contains")}
        page, page_size = int(kw.get("page") or 1), int(kw.get("page_size") or 20)
        fetch_page, fetch_size = (1, 10000) if contains else (page, page_size)
        records, total = await asyncio.to_thread(
            self._dao.list_records, tenant_id, entity, exact, fetch_page, fetch_size)
        values = [record.to_dict() for record in records]
        if contains:
            values = [value for value in values if all(
                str(needle).lower() in str(value.get(field, "")).lower()
                for field, needle in contains.items())]
            total = len(values)
            start = (page - 1) * page_size
            values = values[start:start + page_size]
        fields = kw.get("fields")
        if fields:
            values = [{key: value.get(key) for key in ["recordApiKey", *fields]}
                      for value in values]
        payload = {"entityApiKey": entity, "records": values, "total": total,
                   "page": page, "pageSize": page_size}
        await self._publish_view(f"{entity}:list", payload)
        return {"data": {"records": values, "total": total}}

    async def mutate_data(self, entity: str, action: str,
                          data: dict, **kw) -> dict:
        if entity not in ENTITY_SCHEMAS:
            return {"error": f"实体 {entity} 不存在"}
        tenant_id, user_id = self._identity()
        action_id = str(kw.get("action_id") or f"tool-{uuid.uuid4().hex}")
        try:
            clean = RecordActionService._validate_data(
                entity, data, partial=action != "create") if action != "delete" else {}
            if action == "create":
                record = await asyncio.to_thread(
                    self._dao.create, tenant_id, user_id, entity, clean, action_id)
                record_value = record.to_dict()
                await self._publish_view(
                    f"{entity}:detail:{record.record_api_key}", record_value)
                return {"data": {"id": record.record_api_key, "success": True,
                                 "record": record_value}}
            record_key = str(kw.get("record_id") or data.get("recordApiKey") or data.get("id") or "")
            current = await asyncio.to_thread(self._dao.get, tenant_id, entity, record_key)
            if current is None:
                return {"error": f"记录 {record_key} 不存在"}
            expected = int(kw.get("expected_version") or current.version)
            if action == "update":
                record = await asyncio.to_thread(
                    self._dao.update, tenant_id, user_id, entity, record_key,
                    clean, expected, action_id)
                record_value = record.to_dict()
                await self._publish_view(
                    f"{entity}:detail:{record_key}", record_value)
                return {"data": {"id": record_key, "success": True,
                                 "record": record_value}}
            if action == "delete":
                record = await asyncio.to_thread(
                    self._dao.soft_delete, tenant_id, user_id, entity,
                    record_key, expected, action_id)
                deleted_value = {"entityApiKey": entity,
                                 "recordApiKey": record_key,
                                 "deleted": True, "version": record.version}
                await self._publish_view(
                    f"{entity}:detail:{record_key}", deleted_value)
                return {"data": {"id": record_key, "success": True,
                                 "version": record.version}}
            return {"error": f"未知操作: {action}"}
        except (RecordActionError, LookupError, RuntimeError, ValueError) as exc:
            return {"error": str(exc)}

    async def aggregate_data(self, entity: str, metrics: list, **kw) -> dict:
        result = await self.query_data(entity, kw.get("filters") or {},
                                       page=1, page_size=10000)
        records = result["data"]["records"]
        values: dict[str, Any] = {}
        for metric in metrics:
            operation = metric.get("operation") or metric.get("op")
            field = metric.get("field")
            alias = metric.get("alias") or f"{operation}_{field or 'all'}"
            if operation == "count":
                values[alias] = len(records)
            elif operation in {"sum", "avg"} and field:
                numbers = [r.get(field) for r in records
                           if isinstance(r.get(field), (int, float))]
                values[alias] = sum(numbers) if operation == "sum" else (
                    sum(numbers) / len(numbers) if numbers else 0)
        return {"data": {"results": [values]}}

    async def query_permission(self, user_id: str, entity: str,
                               action: str, **kw) -> dict:
        return {"allowed": entity in ENTITY_SCHEMAS,
                "scope": "tenant", "action": action}
