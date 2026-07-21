"""MCP Service Demo — 一行代码创建

从 config/servers.yaml 加载，自动生成：
- 按域划分的 StreamableHTTP 对外接口
- 内部 REST 接口供 Agent FeignClient 调用
- 所有 Tool handler 自动调下游 Provider
"""
from neo_ai_registry.mcp.fastapi import create_mcp_app

app = create_mcp_app(config_path="config/servers.yaml")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8003, reload=True)
