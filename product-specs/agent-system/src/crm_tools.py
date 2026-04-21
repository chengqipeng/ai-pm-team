"""
CRM 业务工具 — 调用 CrmSimulatedBackend 的真实 CRUD 逻辑
每个工具对应产品设计 §3.7.2 的工具清单
"""
from __future__ import annotations

import json
from .tools import Tool, ToolRegistry
from .dtypes import ToolResult, ValidationResult


class QuerySchemaTool(Tool):
    """查询元数据定义"""

    def __init__(self, backend):
        self._backend = backend

    @property
    def name(self): return "query_schema"

    def input_schema(self):
        return {
            "type": "object",
            "properties": {
                "query_type": {"type": "string",
                    "enum": ["list_entities", "entity", "entity_items", "entity_links"],
                    "description": "查询类型"},
                "entity_api_key": {"type": "string", "description": "业务对象 api_key"},
            },
            "required": ["query_type"],
        }

    async def call(self, input_data, context, on_progress=None):
        result = await self._backend.query_metadata(
            input_data["query_type"],
            entity_api_key=input_data.get("entity_api_key", ""),
        )
        if "error" in result:
            return ToolResult(content=result["error"], is_error=True)
        return ToolResult(content=json.dumps(result["data"], ensure_ascii=False, indent=2))

    def prompt(self):
        return "查询业务对象的元数据定义。query_type: list_entities=列出所有实体, entity=实体详情, entity_items=字段列表, entity_links=关联关系"

    @property
    def code_extractable(self): return True
    @property
    def summary_threshold(self): return 500


class QueryDataTool(Tool):
    """查询业务数据"""

    def __init__(self, backend):
        self._backend = backend

    @property
    def name(self): return "query_data"

    def input_schema(self):
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["query", "get", "count"], "description": "操作类型"},
                "entity_api_key": {"type": "string", "description": "业务对象 api_key"},
                "record_id": {"type": "string", "description": "记录 ID（get 时必填）"},
                "filters": {"type": "object", "description": "过滤条件 {字段: 值}"},
                "fields": {"type": "array", "items": {"type": "string"}, "description": "返回字段"},
                "page": {"type": "integer", "default": 1},
                "page_size": {"type": "integer", "default": 20},
                "order_by": {"type": "string", "description": "排序字段（前缀-表示降序）"},
            },
            "required": ["action", "entity_api_key"],
        }

    async def call(self, input_data, context, on_progress=None):
        action = input_data["action"]
        entity = input_data["entity_api_key"]

        if action == "get":
            rid = input_data.get("record_id")
            if not rid:
                return ToolResult(content="get 操作需要 record_id", is_error=True)
            result = await self._backend.query_data(entity, {"id": rid})
            records = result.get("data", {}).get("records", [])
            if not records:
                return ToolResult(content=f"{entity} 记录 {rid} 不存在", is_error=True)
            return ToolResult(content=json.dumps(records[0], ensure_ascii=False, indent=2))

        if action == "count":
            result = await self._backend.query_data(entity, input_data.get("filters", {}))
            total = result.get("data", {}).get("total", 0)
            return ToolResult(content=f"{entity} 符合条件的记录数: {total}")

        # query
        result = await self._backend.query_data(
            entity, input_data.get("filters", {}),
            fields=input_data.get("fields"),
            page=input_data.get("page", 1),
            page_size=input_data.get("page_size", 20),
            order_by=input_data.get("order_by"),
        )
        return ToolResult(content=json.dumps(result["data"], ensure_ascii=False, indent=2))

    def prompt(self):
        return "查询业务数据。action: query=列表, get=单条, count=计数。entity_api_key: account/contact/opportunity/activity/lead"

    def is_read_only(self, input_data): return True
    @property
    def code_extractable(self): return True
    @property
    def summary_threshold(self): return 300


class ModifyDataTool(Tool):
    """修改业务数据（创建/更新/删除）"""

    def __init__(self, backend):
        self._backend = backend

    @property
    def name(self): return "modify_data"

    def input_schema(self):
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "update", "delete"], "description": "操作类型"},
                "entity_api_key": {"type": "string", "description": "业务对象 api_key"},
                "record_id": {"type": "string", "description": "记录 ID（update/delete 时必填）"},
                "data": {"type": "object", "description": "数据 {字段: 值}"},
            },
            "required": ["action", "entity_api_key"],
        }

    async def call(self, input_data, context, on_progress=None):
        action = input_data["action"]
        entity = input_data["entity_api_key"]
        data = input_data.get("data", {})
        record_id = input_data.get("record_id")

        result = await self._backend.mutate_data(entity, action, data, record_id=record_id)
        if "error" in result:
            return ToolResult(content=f"操作失败: {result['error']}", is_error=True)
        return ToolResult(content=json.dumps(result["data"], ensure_ascii=False, indent=2))

    def is_destructive(self, input_data):
        return input_data.get("action") == "delete"

    def is_read_only(self, input_data): return False

    def prompt(self):
        return "修改业务数据。action: create=创建, update=更新, delete=删除（删除需确认）"


class AnalyzeDataTool(Tool):
    """数据聚合分析"""

    def __init__(self, backend):
        self._backend = backend

    @property
    def name(self): return "analyze_data"

    def input_schema(self):
        return {
            "type": "object",
            "properties": {
                "entity_api_key": {"type": "string", "description": "业务对象 api_key"},
                "metrics": {"type": "array", "items": {"type": "object",
                    "properties": {"field": {"type": "string"}, "function": {"type": "string", "enum": ["count", "sum", "avg", "min", "max"]}},
                    "required": ["field", "function"]}, "description": "聚合指标"},
                "group_by": {"type": "string", "description": "分组字段"},
                "filters": {"type": "object", "description": "过滤条件"},
            },
            "required": ["entity_api_key", "metrics"],
        }

    async def call(self, input_data, context, on_progress=None):
        result = await self._backend.aggregate_data(
            input_data["entity_api_key"],
            input_data["metrics"],
            group_by=input_data.get("group_by"),
            filters=input_data.get("filters", {}),
        )
        return ToolResult(content=json.dumps(result["data"], ensure_ascii=False, indent=2))

    def prompt(self):
        return "数据聚合分析。支持 count/sum/avg/min/max + 分组。entity_api_key: account/opportunity/lead 等"

    def is_read_only(self, input_data): return True
    @property
    def code_extractable(self): return True
    @property
    def summary_threshold(self): return 800


class AskUserTool(Tool):
    """向用户提问"""

    @property
    def name(self): return "ask_user"

    def input_schema(self):
        return {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "要问用户的问题"}},
            "required": ["question"],
        }

    async def call(self, input_data, context, on_progress=None):
        # demo 中模拟用户回答
        q = input_data.get("question", "")
        return ToolResult(content=f"[用户回答] 确认，请继续。（问题: {q}）")

    def prompt(self): return "向用户提问或确认"


def register_crm_tools(registry: ToolRegistry, backend) -> None:
    """注册全部 CRM 业务工具"""
    registry.register(QuerySchemaTool(backend))
    registry.register(QueryDataTool(backend))
    registry.register(ModifyDataTool(backend))
    registry.register(AnalyzeDataTool(backend))
    registry.register(AskUserTool())
