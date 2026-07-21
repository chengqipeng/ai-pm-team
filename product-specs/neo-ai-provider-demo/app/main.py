"""业务域服务 Provider Demo — 使用 SDK create_provider_app 一行创建

新建 Provider 只需：
1. config/tools.yaml — 定义 Tool/Middleware 列表
2. handler 文件 — 实现业务逻辑
3. main.py — 一行创建 app
"""
from neo_ai_registry.fastapi import create_provider_app

from app.tool_handlers import query_customer, update_opportunity, analyze_pipeline
from app.mcp_tool_handlers import (
    query_records, get_record_details, create_record,
    search_knowledge, list_knowledge_bases,
    list_entities, get_entity_fields,
)
from app.middleware_handlers import crm_query_state_handler, sales_context_inject_handler

app = create_provider_app(
    domain="sales",
    config_path="config/tools.yaml",
    handler_map={
        # Agent 直接调用
        "query_customer": query_customer,
        "update_opportunity": update_opportunity,
        "analyze_pipeline": analyze_pipeline,
        # MCP 回调
        "query_records": query_records,
        "get_record_details": get_record_details,
        "create_record": create_record,
        "search_knowledge": search_knowledge,
        "list_knowledge_bases": list_knowledge_bases,
        "list_entities": list_entities,
        "get_entity_fields": get_entity_fields,
    },
    middleware_handler_map={
        "crm_query_state": crm_query_state_handler,
        "sales_context_inject": sales_context_inject_handler,
    },
)
