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
        return (
            "查询 CRM 系统中业务对象的元数据定义（字段结构、关联关系等）。\n"
            "何时使用：当你不确定某个业务对象有哪些字段、字段类型是什么、或者对象之间的关联关系时，先调用此工具查 schema，再用 query_data 查数据。\n"
            "参数说明：\n"
            "  - query_type（必填）：\n"
            "    · list_entities — 列出系统中所有业务对象（如 account、opportunity、contact 等）\n"
            "    · entity — 查看某个业务对象的详细定义（需传 entity_api_key）\n"
            "    · entity_items — 查看某个业务对象的所有字段列表（需传 entity_api_key）\n"
            "    · entity_links — 查看某个业务对象与其他对象的关联关系（需传 entity_api_key）\n"
            "  - entity_api_key（entity/entity_items/entity_links 时必填）：业务对象标识，如 account、opportunity、contact、activity、lead\n"
            "典型用法：\n"
            "  · 用户问'商机有哪些字段' → query_schema(query_type='entity_items', entity_api_key='opportunity')\n"
            "  · 用户问'系统有哪些业务对象' → query_schema(query_type='list_entities')\n"
            "  · 不确定字段名时先查 schema 再查数据，避免字段名写错"
        )

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
            "查询 CRM 系统中的业务数据记录（客户、商机、联系人、活动、线索）。\n"
            "何时使用：用户要求查看、搜索、统计业务数据时使用。这是最常用的数据查询工具。\n"
            "参数说明：\n"
            "  - action（必填）：\n"
            "    · query — 按条件查询记录列表（支持分页、排序、字段筛选）\n"
            "    · get — 按 record_id 查询单条记录的完整详情\n"
            "    · count — 统计符合条件的记录总数\n"
            "  - entity_api_key（必填）：业务对象标识\n"
            "    · account=客户  opportunity=商机  contact=联系人  activity=活动  lead=线索\n"
            "  - filters（可选）：过滤条件，JSON 对象格式\n"
            "    · 精确匹配：{\"owner_name\": \"张三\"}\n"
            "    · 多条件：{\"owner_name\": \"张三\", \"stage\": \"谈判\"}\n"
            "  - fields（可选）：指定返回哪些字段，如 [\"name\", \"amount\", \"stage\"]\n"
            "  - order_by（可选）：排序字段，前缀 - 表示降序，如 \"-amount\" 按金额降序\n"
            "  - page / page_size（可选）：分页参数，默认 page=1, page_size=20\n"
            "  - record_id（get 时必填）：要查询的记录 ID\n"
            "典型用法：\n"
            "  · '查张三的商机' → query_data(action='query', entity_api_key='opportunity', filters={\"owner_name\":\"张三\"})\n"
            "  · '有多少个客户' → query_data(action='count', entity_api_key='account')\n"
            "  · '金额最高的5个商机' → query_data(action='query', entity_api_key='opportunity', order_by='-amount', page_size=5)\n"
            "注意：不确定字段名时，先用 query_schema 查字段定义"
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
            "修改 CRM 系统中的业务数据（创建、更新、删除记录）。\n"
            "何时使用：用户要求新建记录、修改字段值、或删除记录时使用。\n"
            "⚠️ 重要：执行前必须先用 ask_user 向用户确认操作内容和影响范围。\n"
            "参数说明：\n"
            "  - action（必填）：\n"
            "    · create — 创建新记录（需传 data）\n"
            "    · update — 更新已有记录（需传 record_id + data）\n"
            "    · delete — 删除记录（需传 record_id，执行前必须确认）\n"
            "  - entity_api_key（必填）：account/opportunity/contact/activity/lead\n"
            "  - record_id（update/delete 时必填）：要操作的记录 ID\n"
            "  - data（create/update 时必填）：要写入的字段键值对\n"
            "    · 如 {\"name\": \"华为云项目\", \"amount\": 500000, \"stage\": \"谈判\"}\n"
            "典型用法：\n"
            "  · '创建一个商机' → 先用 ask_clarification 确认商机名称和金额，再 modify_data(action='create', ...)\n"
            "  · '把这个商机金额改成100万' → modify_data(action='update', record_id='xxx', data={\"amount\":1000000})\n"
            "  · '删除这个客户' → 先 ask_user 确认，再 modify_data(action='delete', record_id='xxx')\n"
            "注意：不知道 record_id 时，先用 query_data 查询获取"
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
        return (
            "对 CRM 业务数据进行聚合统计分析（求和、计数、平均值、最大最小值 + 分组）。\n"
            "何时使用：用户要求统计、分析、汇总数据时使用。如果只是查看数据列表，用 query_data。\n"
            "参数说明：\n"
            "  - entity_api_key（必填）：account/opportunity/contact/activity/lead\n"
            "  - metrics（必填）：聚合指标数组，每项包含 field（字段名）和 function（聚合函数）\n"
            "    · function 可选：count / sum / avg / min / max\n"
            "    · 如 [{\"field\": \"amount\", \"function\": \"sum\"}, {\"field\": \"id\", \"function\": \"count\"}]\n"
            "  - group_by（可选）：分组字段，如 \"stage\"（按阶段分组）、\"owner_name\"（按负责人分组）\n"
            "  - filters（可选）：过滤条件，格式同 query_data\n"
            "典型用法：\n"
            "  · '商机总金额是多少' → analyze_data(entity='opportunity', metrics=[{field:'amount', function:'sum'}])\n"
            "  · '按阶段统计商机数量和金额' → analyze_data(entity='opportunity', metrics=[{field:'id',function:'count'},{field:'amount',function:'sum'}], group_by='stage')\n"
            "  · '张三的客户数' → analyze_data(entity='account', metrics=[{field:'id',function:'count'}], filters={\"owner_name\":\"张三\"})"
        )

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
            "向用户发起简单的是/否确认。\n"
            "何时使用：仅在执行数据修改（create/update/delete）前，向用户确认操作内容。\n"
            "⚠️ 边界：如果是信息不足、需求模糊、需要用户选择方案，应使用 ask_clarification 而非本工具。\n"
            "典型用法：\n"
            "  · '确认要删除客户「华为科技」吗？该客户下有 3 个商机会受影响。'\n"
            "  · '确认要将商机金额从 50万 修改为 100万 吗？'"
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
            "向用户澄清追问，获取缺失的关键信息后再继续执行。\n"
            "何时使用：用户输入信息不足、表述有歧义、存在多种可行方案、或操作有风险需确认时使用。\n"
            "⚠️ 边界：如果只是简单的是/否确认（如删除前确认），用 ask_user。本工具用于需要用户补充具体信息的场景。\n"
            "参数说明：\n"
            "  - question（必填）：要问用户的具体问题\n"
            "  - clarification_type（必填）：\n"
            "    · missing_info — 缺少关键参数（如'查客户'但没说哪个客户）\n"
            "    · ambiguous_requirement — 表述有歧义（如'处理线索'可能是转化/分配/关闭）\n"
            "    · approach_choice — 多种方案需选择（如查到 3 个同名客户）\n"
            "    · risk_confirmation — 高风险操作确认（如批量删除、权限变更）\n"
            "  - context（可选）：当前已知的上下文，帮助用户理解追问背景\n"
            "  - options（approach_choice 时必填）：可选项列表\n"
            "典型用法：\n"
            "  · 用户说'查客户' → ask_clarification(question='你要查哪个客户？可以提供客户名称或负责人', clarification_type='missing_info')\n"
            "  · 查到 3 个张三 → ask_clarification(question='找到3个张三，你要查哪个？', clarification_type='approach_choice', options=['张三-华为','张三-腾讯','张三-阿里'])"
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
            "管理 Agent 的对话记忆（查看、搜索、删除、清空）。\n"
            "何时使用：用户明确要求查看记忆、删除某些记忆、清理记忆、忘记某些内容时使用。\n"
            "⚠️ 注意：只有用户主动要求管理记忆时才调用，正常对话中不要主动调用。\n"
            "参数说明：\n"
            "  - action（必填）：\n"
            "    · list — 查看/搜索记忆（可选 keyword 和 dimension 筛选）\n"
            "    · delete — 按关键词删除匹配的记忆（需传 keyword）\n"
            "    · delete_by_ids — 按 ID 精确删除（需传 ids 数组，通常先 list 再删除）\n"
            "    · clear — 清空当前用户的所有记忆（⚠️ 不可恢复，需先确认）\n"
            "  - keyword（list/delete 时使用）：搜索或删除的关键词\n"
            "  - dimension（可选）：按维度筛选 task_history/customer_context/user_profile/domain_knowledge\n"
            "  - ids（delete_by_ids 时必填）：要删除的记忆 ID 列表\n"
            "典型用法：\n"
            "  · '看看我的记忆' → manage_memory(action='list')\n"
            "  · '删除关于商机的记忆' → manage_memory(action='delete', keyword='商机')\n"
            "  · '删除商机查询的记忆' → manage_memory(action='delete', keyword='商机')\n"
            "  · '清理所有记忆' → 先 ask_user 确认，再 manage_memory(action='clear')\n"
            "  · '忘记张三的信息' → manage_memory(action='delete', keyword='张三')"
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
