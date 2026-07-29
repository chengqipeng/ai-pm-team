"""MCP Service Demo — 一行代码创建

从 config/ 目录加载所有 registry*.yaml 文件，自动生成：
- 按域划分的 StreamableHTTP 对外接口
- 内部 REST 接口供 Agent FeignClient 调用
- 所有 Tool handler 自动调下游 Provider

启动时注册到 Eureka，关闭时注销。
"""
import os
from pathlib import Path

from neo_ai_registry.mcp.fastapi import create_mcp_app

_BASE_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
app = create_mcp_app(config_dir=str(_BASE_DIR / "config"))


@app.on_event("startup")
async def startup():
    from neo_ai_infr_eureka import EurekaGlobalClient
    await EurekaGlobalClient().register_eureka()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8003, reload=True)
