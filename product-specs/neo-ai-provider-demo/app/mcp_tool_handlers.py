"""MCP Tool 业务逻辑处理器 — 数据查询下沉到 Provider

MCP Demo 通过 ToolFeignClient 调用本服务的这些 handler。
数据来源：config/mock_data.yaml（模拟 MySQL）。

handler 签名：async def handler(input_data: dict, context: dict) -> dict
"""
from __future__ import annotations
from typing import Any
from app.data_store import data_store


async def query_records(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """查询 CRM 数据记录"""
    entity = input_data.get("entity", "accounts")
    limit = input_data.get("limit", 10)
    conditions = input_data.get("conditions", {})

    collection = entity if entity.endswith("s") else f"{entity}s"
    records = data_store.query("crm", collection, conditions, limit)

    return {
        "status": "success",
        "content": [{"type": "text", "text": f"查询 {entity} 成功，返回 {len(records)} 条记录"}],
        "records": records,
        "total": len(records),
    }


async def get_record_details(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """获取单条记录详情"""
    entity = input_data.get("entity", "accounts")
    record_id = input_data.get("record_id", "")

    collection = entity if entity.endswith("s") else f"{entity}s"
    record = data_store.get_by_id("crm", collection, record_id)

    if not record:
        return {
            "status": "success",
            "content": [{"type": "text", "text": f"未找到 {entity} 记录: {record_id}"}],
            "record": None,
        }
    return {
        "status": "success",
        "content": [{"type": "text", "text": f"{entity} 记录 {record_id} 详情"}],
        "record": record,
    }


async def create_record(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """创建 CRM 数据记录（模拟）"""
    entity = input_data.get("entity", "")
    data = input_data.get("data", {})

    return {
        "status": "success",
        "content": [{"type": "text", "text": f"已创建 {entity} 记录"}],
        "record_id": f"{entity}_new_{len(data)}",
        "created_fields": list(data.keys()),
    }


async def search_knowledge(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """语义检索知识库文档"""
    query = input_data.get("query", "")
    top_k = input_data.get("top_k", 5)
    knowledge_base_id = input_data.get("knowledge_base_id", "")

    results = data_store.search_knowledge(query, knowledge_base_id, top_k)

    return {
        "status": "success",
        "content": [{"type": "text", "text": f"检索 '{query}' 找到 {len(results)} 条结果"}],
        "results": results,
    }


async def list_knowledge_bases(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """列出可用知识库"""
    kbs = data_store.list_knowledge_bases()
    return {
        "status": "success",
        "content": [{"type": "text", "text": f"共 {len(kbs)} 个知识库"}],
        "knowledge_bases": kbs,
    }


async def list_entities(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """列出所有业务实体"""
    entities = data_store.get_entities()
    return {
        "status": "success",
        "content": [{"type": "text", "text": f"共 {len(entities)} 个业务实体"}],
        "entities": entities,
    }


async def get_entity_fields(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """获取实体字段列表"""
    entity_api_key = input_data.get("entity_api_key", "")
    fields = data_store.get_fields(entity_api_key)

    if not fields:
        return {
            "status": "success",
            "content": [{"type": "text", "text": f"实体 '{entity_api_key}' 未找到字段定义"}],
            "fields": [],
        }
    return {
        "status": "success",
        "content": [{"type": "text", "text": f"实体 {entity_api_key} 共 {len(fields)} 个字段"}],
        "fields": fields,
    }
