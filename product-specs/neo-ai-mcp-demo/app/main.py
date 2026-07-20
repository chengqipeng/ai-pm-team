"""MCP Service Demo — 按业务域划分独立 MCP StreamableHTTP 接口

对外接口（按域划分，MCP 协议标准）：
    POST /mcp/v2.0/crm          → crm-data-mcp（CRM 数据）
    POST /mcp/v2.0/knowledge    → knowledge-mcp（知识库）
    POST /mcp/v2.0/metadata     → metadata-mcp（元数据）

内部接口（Agent FeignClient 调用）：
    POST /v2/mcp/tools/call
    GET  /v2/mcp/tools
    GET  /v2/mcp/servers

MCP Server 列表：
    ├── crm-data-mcp        → query_records / get_record_details / create_record
    ├── knowledge-mcp       → search_knowledge / list_knowledge_bases
    └── metadata-mcp        → list_entities / get_entity_fields
"""
from fastapi import FastAPI

from app.router import router as internal_router
from app.mcp_endpoint import router as mcp_router
from app.servers import server_registry

app = FastAPI(title="Neo AI MCP Service Demo", version="0.1.0")

# 内部接口（Agent FeignClient 调用）
app.include_router(internal_router)

# 对外 MCP 协议接口（按业务域划分）
app.include_router(mcp_router)


@app.get("/health")
def health():
    servers = server_registry.list_servers()
    return {
        "status": "ok",
        "mcp_endpoints": {
            "crm": "/mcp/v2.0/crm",
            "knowledge": "/mcp/v2.0/knowledge",
            "metadata": "/mcp/v2.0/metadata",
        },
        "servers": len(servers),
        "total_tools": sum(s["tool_count"] for s in servers),
    }
