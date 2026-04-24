"""
CRM 业务工具 — 调用 CrmSimulatedBackend 的真实 CRUD 逻辑
每个工具对应产品设计 §3.7.2 的工具清单
"""
from __future__ import annotations

import json
from src.tools.base import Tool, ToolRegistry
from src.core.dtypes import ToolResult, ValidationResult


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
            entity, input_data.get("filters") or {},
            fields=input_data.get("fields"),
            page=input_data.get("page") or 1,
            page_size=input_data.get("page_size") or 20,
            order_by=input_data.get("order_by"),
        )
        return ToolResult(content=json.dumps(result["data"], ensure_ascii=False, indent=2))

    def prompt(self):
        return (
            "查询业务数据。action: query=列表查询, get=按ID查单条, count=统计数量。"
            "entity_api_key: account/contact/opportunity/activity/lead。"
            "支持 filters（过滤条件，如 {owner_name:'张三', stage:'谈判'}）、"
            "fields（返回字段列表）、order_by（排序，前缀-表示降序）、page/page_size（分页）。"
        )

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
        return (
            "修改业务数据。action: create=创建新记录, update=更新已有记录, delete=删除记录。"
            "entity_api_key: account/contact/opportunity/activity/lead。"
            "update/delete 时必须传 record_id。data 为要写入的字段键值对，如 {name:'新名称', amount:500000}。"
            "删除操作需先向用户确认。"
        )


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

    def prompt(self):
        return (
            "向用户简单确认。仅用于数据修改/删除前的二次确认（如'确认删除该客户？'）。"
            "信息不足或需求模糊时应使用 ask_clarification 而非本工具。"
        )


class AskClarificationTool(Tool):
    """向用户澄清追问 — 信息不足或有歧义时中断执行并追问

    4 种澄清类型：
    - missing_info: 缺少关键参数（实体名、筛选条件、目标值）
    - ambiguous_requirement: 用户表述有歧义，可能指向多种操作
    - approach_choice: 多个匹配结果或多种可行方案需用户选择
    - risk_confirmation: 操作涉及删除、批量修改等不可逆影响
    """

    @property
    def name(self): return "ask_clarification"

    def input_schema(self):
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "要问用户的具体问题",
                },
                "clarification_type": {
                    "type": "string",
                    "enum": ["missing_info", "ambiguous_requirement", "approach_choice", "risk_confirmation"],
                    "description": "澄清类型",
                },
                "context": {
                    "type": "string",
                    "description": "当前已知的上下文信息，帮助用户理解追问背景",
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选项列表（approach_choice 时必填）",
                },
            },
            "required": ["question", "clarification_type"],
        }

    async def call(self, input_data, context, on_progress=None):
        # 实际执行由 ClarificationMiddleware 拦截，不会走到这里
        # 此处作为 fallback，返回格式化的追问内容
        question = input_data.get("question", "")
        ctype = input_data.get("clarification_type", "missing_info")
        ctx = input_data.get("context", "")
        options = input_data.get("options", [])

        icons = {"missing_info": "❓", "ambiguous_requirement": "🤔",
                 "approach_choice": "🔀", "risk_confirmation": "⚠️"}
        icon = icons.get(ctype, "❓")
        parts = [f"{icon} {ctx}\n{question}" if ctx else f"{icon} {question}"]
        if options:
            parts += [""] + [f"  {i}. {o}" for i, o in enumerate(options, 1)]
        return ToolResult(content="\n".join(parts))

    def prompt(self):
        return (
            "向用户澄清追问。当信息不足、需求模糊、存在多种方案或操作有风险时使用。"
            "clarification_type: missing_info/ambiguous_requirement/approach_choice/risk_confirmation"
        )


class ManageMemoryTool(Tool):
    """管理 Agent 记忆 — 查询、删除、清空

    支持的操作：
    - list: 列出记忆（可按关键词和维度筛选）
    - delete: 按关键词删除匹配的记忆
    - delete_by_ids: 按 ID 列表删除
    - clear: 清空所有记忆
    """

    def __init__(self, memory_engine=None):
        self._engine = memory_engine

    @property
    def name(self): return "manage_memory"

    def input_schema(self):
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "delete", "delete_by_ids", "clear"],
                    "description": "操作类型: list=查看记忆, delete=按关键词删除, delete_by_ids=按ID删除, clear=清空全部",
                },
                "keyword": {
                    "type": "string",
                    "description": "搜索/删除的关键词（list 和 delete 时使用）",
                },
                "dimension": {
                    "type": "string",
                    "enum": ["task_history", "customer_context", "user_profile", "domain_knowledge"],
                    "description": "记忆维度筛选（可选）",
                },
                "ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "要删除的记忆 ID 列表（delete_by_ids 时使用）",
                },
            },
            "required": ["action"],
        }

    async def call(self, input_data, context, on_progress=None):
        if self._engine is None:
            return ToolResult(content="记忆引擎未初始化", is_error=True)

        action = input_data.get("action", "")
        keyword = input_data.get("keyword", "")
        dimension = input_data.get("dimension")
        user_id = "default"  # TODO: 从 context 获取

        if action == "list":
            memories = self._engine.list_memories(user_id, keyword, dimension)
            if not memories:
                return ToolResult(content="未找到匹配的记忆" + (f"（关键词: {keyword}）" if keyword else ""))
            lines = []
            for m in memories:
                content_preview = m["content"][:150] + ("..." if len(m["content"]) > 150 else "")
                lines.append(f"[ID:{m['id']}] [{m['dimension']}] {content_preview}")
            return ToolResult(content=f"找到 {len(memories)} 条记忆:\n\n" + "\n\n".join(lines))

        elif action == "delete":
            if not keyword:
                return ToolResult(content="删除操作需要提供 keyword 参数", is_error=True)
            deleted = self._engine.delete_memories_by_keyword(user_id, keyword, dimension)
            return ToolResult(content=f"已删除 {deleted} 条包含「{keyword}」的记忆")

        elif action == "delete_by_ids":
            ids = input_data.get("ids", [])
            if not ids:
                return ToolResult(content="需要提供 ids 参数", is_error=True)
            deleted = self._engine.delete_memories_by_ids(ids)
            return ToolResult(content=f"已删除 {deleted} 条记忆")

        elif action == "clear":
            deleted = self._engine.clear_all_memories(user_id)
            return ToolResult(content=f"已清空所有记忆，共删除 {deleted} 条")

        return ToolResult(content=f"未知操作: {action}", is_error=True)

    def prompt(self):
        return (
            "管理 Agent 的对话记忆。当用户要求查看、删除、清理、忘记记忆时必须调用此工具。"
            "action: list=查看/列出记忆, delete=按关键词删除记忆, delete_by_ids=按ID删除, clear=清空全部记忆。"
            "示例：用户说'删除商机查询的记忆' → action=delete, keyword='商机'；"
            "用户说'看看我的记忆' → action=list；"
            "用户说'清空所有记忆' → action=clear。"
        )


def register_crm_tools(registry: ToolRegistry, backend, memory_engine=None) -> None:
    """注册全部 CRM 业务工具"""
    registry.register(QuerySchemaTool(backend))
    registry.register(QueryDataTool(backend))
    registry.register(ModifyDataTool(backend))
    registry.register(AnalyzeDataTool(backend))
    registry.register(AskUserTool())
    registry.register(AskClarificationTool())
    if memory_engine is not None:
        registry.register(ManageMemoryTool(memory_engine))
