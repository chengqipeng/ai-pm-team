"""
Metarepo 工具 —— 元模型 & 元数据浏览，对齐 paas-platform-service MetamodelBrowseApiService

工具分层：
  - browse_metamodel     ↔ /meta/metamodels, /meta/meta-items, /meta/column-mapping,
                           /meta/meta-links, /meta/meta-options, /meta/item-type-mapping
  - query_metadata       ↔ /meta/metadata, /meta/metadata/entities, /meta/metadata/items,
                           /meta/metadata/entity-links, /meta/metadata/check-rules,
                           /meta/metadata/busi-types, /meta/metadata/pick-options

后端可以是 MetarepoSimulatedBackend（同步）或 MetarepoHttpBackend（异步），
两种 backend 同名方法，工具内部用 inspect.isawaitable 桥接。
"""
from __future__ import annotations

import inspect
import json
import logging
from typing import Any

from src.core.dtypes import ToolResult
from src.tools.base import Tool, ToolRegistry

logger = logging.getLogger(__name__)

# ═══ 依赖解析（供 create() 工厂方法使用） ═══

_metarepo_backend_instance = None


def _resolve_metarepo_backend():
    """解析 Metarepo backend（单例，按环境变量选择 Sim 或 HTTP）"""
    global _metarepo_backend_instance
    if _metarepo_backend_instance is None:
        from src.tools._http_auth import get_shared_auth_client
        client = get_shared_auth_client()
        if client is not None:
            from src.tools.metarepo_http_backend import MetarepoHttpBackend
            _metarepo_backend_instance = MetarepoHttpBackend(auth_client=client)
            logger.info("Metarepo backend resolved: HTTP → %s", client.base_url)
        else:
            from src.tools.metarepo_backend import MetarepoSimulatedBackend
            _metarepo_backend_instance = MetarepoSimulatedBackend()
            logger.info("Metarepo backend resolved: Simulated")
    return _metarepo_backend_instance


async def _await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class BrowseMetamodelTool(Tool):
    """浏览元模型层（p_meta_model / p_meta_item / p_meta_link / p_meta_option / ItemTypeEnum）"""

    def __init__(self, backend=None):
        self._backend = backend

    @classmethod
    def create(cls, tenant_id: int = 0, db_row=None) -> "BrowseMetamodelTool":
        """自包含初始化 — 自动解析 metarepo backend"""
        backend = _resolve_metarepo_backend()
        return cls(backend=backend)

    @property
    def name(self): return "browse_metamodel"

    def input_schema(self):
        return {
            "type": "object",
            "properties": {
                "query_type": {
                    "type": "string",
                    "enum": [
                        "list_metamodels",
                        "get_metamodel",
                        "list_meta_items",
                        "column_mapping",
                        "list_meta_links",
                        "list_meta_options",
                        "item_type_mapping",
                        "trace_db_column",
                    ],
                    "description": "浏览类型，对应 paas-platform-service 的 /meta/* 接口",
                },
                "metamodel_api_key": {
                    "type": "string",
                    "description": "元模型 apiKey，如 entity / item / role / department",
                },
                "item_api_key": {
                    "type": "string",
                    "description": "元模型字段 apiKey（list_meta_options 时可选过滤）",
                },
                "db_column": {
                    "type": "string",
                    "description": "物理列名，如 dbc_varchar5，仅 trace_db_column 使用",
                },
            },
            "required": ["query_type"],
        }

    async def call(self, input_data, context, on_progress=None):
        qt = input_data["query_type"]
        mm = input_data.get("metamodel_api_key")
        item = input_data.get("item_api_key")
        col = input_data.get("db_column")

        try:
            if qt == "list_metamodels":
                data = await _await(self._backend.list_metamodels())
            elif qt == "get_metamodel":
                if not mm:
                    return ToolResult(content="get_metamodel 需要 metamodel_api_key", is_error=True)
                data = await _await(self._backend.get_metamodel(mm))
                if data is None:
                    return ToolResult(content=f"元模型 {mm} 不存在", is_error=True)
            elif qt == "list_meta_items":
                if not mm:
                    return ToolResult(content="list_meta_items 需要 metamodel_api_key", is_error=True)
                data = await _await(self._backend.list_meta_items(mm))
            elif qt == "column_mapping":
                if not mm:
                    return ToolResult(content="column_mapping 需要 metamodel_api_key", is_error=True)
                data = await _await(self._backend.get_column_mapping(mm))
            elif qt == "list_meta_links":
                data = await _await(self._backend.list_meta_links(mm))
            elif qt == "list_meta_options":
                if not mm:
                    return ToolResult(content="list_meta_options 需要 metamodel_api_key", is_error=True)
                data = await _await(self._backend.list_meta_options(mm, item_api_key=item))
            elif qt == "item_type_mapping":
                data = await _await(self._backend.get_item_type_mapping())
            elif qt == "trace_db_column":
                if not col:
                    return ToolResult(content="trace_db_column 需要 db_column", is_error=True)
                data = await _await(self._backend.trace_db_column(col))
            else:
                return ToolResult(content=f"未知 query_type: {qt}", is_error=True)
        except Exception as e:  # pragma: no cover - defensive
            return ToolResult(content=f"元模型查询失败: {e}", is_error=True)

        return ToolResult(content=json.dumps(data, ensure_ascii=False, indent=2))

    def is_read_only(self, input_data): return True

    def prompt(self):
        return (
            "浏览 aPaaS 平台的元模型层（paas-platform-service /meta/*）。\n"
            "何时使用：用户问'系统里有哪些元模型'、'某个元模型有哪些字段'、'某个字段映射到哪一列'、\n"
            "'dbc_varchar5 是哪个字段'、'选项集有哪些值'、'ItemType 有几种' 时使用。\n"
            "参数说明：\n"
            "  - query_type（必填）：\n"
            "    · list_metamodels    — 列出所有元模型（p_meta_model 全量）\n"
            "    · get_metamodel      — 查看单个元模型（需传 metamodel_api_key）\n"
            "    · list_meta_items    — 查看元模型的字段定义（需传 metamodel_api_key）\n"
            "    · column_mapping     — 查看字段 apiKey → dbc 列名的映射表（需传 metamodel_api_key）\n"
            "    · list_meta_links    — 查看元模型间关联（可传 metamodel_api_key 过滤）\n"
            "    · list_meta_options  — 查看枚举字段的合法取值（需传 metamodel_api_key，可选 item_api_key）\n"
            "    · item_type_mapping  — 查看平台支持的 ItemTypeEnum 清单\n"
            "    · trace_db_column    — 反查 dbc 列被哪些元模型字段占用（需传 db_column）\n"
            "  - metamodel_api_key（部分 query_type 必填）：entity / item / role / department / ...\n"
            "  - item_api_key（list_meta_options 可选）：限定某个字段的取值\n"
            "  - db_column（trace_db_column 必填）：dbc_varchar1 / dbc_int1 / dbc_smallint2 ...\n"
            "典型用法：\n"
            "  · '系统里有多少元模型？' → browse_metamodel(query_type='list_metamodels')\n"
            "  · 'entity 元模型有哪些字段？' → browse_metamodel(query_type='list_meta_items', metamodel_api_key='entity')\n"
            "  · 'item.itemType 能填什么？' → browse_metamodel(query_type='list_meta_options', metamodel_api_key='item', item_api_key='itemType')\n"
            "  · 'dbc_varchar5 是哪个字段？' → browse_metamodel(query_type='trace_db_column', db_column='dbc_varchar5')\n"
            "注意：本工具仅返回元模型定义（p_meta_*），要查元数据实例请用 query_metadata。"
        )

    @property
    def code_extractable(self): return True
    @property
    def summary_threshold(self): return 500


class QueryMetadataTool(Tool):
    """查询元数据实例（Common + Tenant 合并后的数据，对齐 /meta/metadata/*）"""

    def __init__(self, backend=None):
        self._backend = backend

    @classmethod
    def create(cls, tenant_id: int = 0, db_row=None) -> "QueryMetadataTool":
        """自包含初始化 — 自动解析 metarepo backend"""
        backend = _resolve_metarepo_backend()
        return cls(backend=backend)

    @property
    def name(self): return "query_metadata"

    def input_schema(self):
        return {
            "type": "object",
            "properties": {
                "metamodel_api_key": {
                    "type": "string",
                    "description": "元模型 apiKey，如 entity / item / pickOption / entityLink / checkRule / busiType / role / department",
                },
                "entity_api_key": {
                    "type": "string",
                    "description": "按业务对象过滤（item/pickOption/checkRule/entityLink/busiType 子表时可传）",
                },
                "item_api_key": {
                    "type": "string",
                    "description": "按字段过滤（pickOption 时可传，用来查某个字段的选项值）",
                },
                "api_key": {
                    "type": "string",
                    "description": "按元数据实例 apiKey 精确查询单条",
                },
            },
            "required": ["metamodel_api_key"],
        }

    async def call(self, input_data, context, on_progress=None):
        mm = input_data["metamodel_api_key"]
        entity = input_data.get("entity_api_key")
        item = input_data.get("item_api_key")
        api_key = input_data.get("api_key")

        model = await _await(self._backend.get_metamodel(mm))
        if model is None:
            return ToolResult(
                content=f"元模型 {mm} 未注册，使用 browse_metamodel(query_type='list_metamodels') 查看全部元模型",
                is_error=True,
            )

        if api_key:
            record = await _await(self._backend.get_metadata(mm, api_key, entity_api_key=entity))
            if record is None:
                return ToolResult(content=f"{mm} 中不存在 apiKey={api_key} 的元数据实例", is_error=True)
            return ToolResult(content=json.dumps(record, ensure_ascii=False, indent=2))

        records = await _await(
            self._backend.list_metadata(mm, entity_api_key=entity, item_api_key=item)
        ) or []
        payload = {"metamodelApiKey": mm, "total": len(records), "records": records}
        return ToolResult(content=json.dumps(payload, ensure_ascii=False, indent=2))

    def is_read_only(self, input_data): return True

    def prompt(self):
        return (
            "查询 aPaaS 平台的元数据实例（Common + Tenant 合并后的结果，对齐 /meta/metadata/*）。\n"
            "何时使用：用户问'系统里有哪些业务对象'、'account 有哪些字段/选项值/关联/校验规则/业务类型'、\n"
            "'所有角色是什么' 时使用。\n"
            "参数说明：\n"
            "  - metamodel_api_key（必填）：\n"
            "    · entity      — 业务对象列表\n"
            "    · item        — 业务对象字段（配合 entity_api_key 过滤）\n"
            "    · entityLink  — 业务对象关联（配合 entity_api_key 过滤父对象）\n"
            "    · pickOption  — 选项值（配合 item_api_key 过滤）\n"
            "    · checkRule   — 校验规则（配合 entity_api_key）\n"
            "    · busiType    — 业务类型（配合 entity_api_key）\n"
            "    · role        — 角色（独立元模型）\n"
            "    · department  — 部门（独立元模型）\n"
            "  - entity_api_key（可选）：按业务对象过滤子元数据\n"
            "  - item_api_key（可选）：按字段过滤（主要给 pickOption 用）\n"
            "  - api_key（可选）：精确查询单条元数据实例\n"
            "典型用法：\n"
            "  · '系统有哪些业务对象？' → query_metadata(metamodel_api_key='entity')\n"
            "  · 'account 的字段列表' → query_metadata(metamodel_api_key='item', entity_api_key='account')\n"
            "  · 'opportunity.stage 能填什么' → query_metadata(metamodel_api_key='pickOption', item_api_key='stage')\n"
            "  · '系统有哪些角色' → query_metadata(metamodel_api_key='role')\n"
            "注意：本工具返回的是元数据实例；要查元模型本身（字段结构、dbc 列映射），请用 browse_metamodel。"
        )

    @property
    def code_extractable(self): return True
    @property
    def summary_threshold(self): return 500


def register_metarepo_tools(registry: ToolRegistry, backend) -> None:
    """注册元模型 / 元数据浏览工具。backend 可以是 Sim 或 Http 版本。"""
    registry.register(BrowseMetamodelTool(backend))
    registry.register(QueryMetadataTool(backend))
