"""Agent 运行时 Demo — 主入口

展示 SDK AgentRegistry 的完整能力：
- get_base_tools() → BaseTool 列表（builtin + remote），传给 create_agent(tools=[...])
- get_middlewares() → AgentMiddleware 列表（builtin + remote），传给 create_agent(middleware=[...])

启动时通过 neo-ai-infr-eureka 注册到 Eureka。
"""
from fastapi import FastAPI

from app.agent_loader import AgentLoader

app = FastAPI(title="Neo AI Agent Runtime Demo", version="0.1.0")
agent_loader = AgentLoader()


@app.on_event("startup")
async def startup():
    from neo_ai_infr_eureka import EurekaGlobalClient
    await EurekaGlobalClient().register_eureka()
    agent_loader.load()


@app.get("/health")
def health():
    return {"status": "ok", "loaded": agent_loader.summary()}


@app.get("/v1/agent/tools")
def list_tools():
    """查看所有 BaseTool（可直接传给 create_agent）"""
    tools = agent_loader.get_base_tools()
    return {
        "code": 0,
        "data": [{"name": t.name, "description": t.description[:80]} for t in tools],
    }


@app.get("/v1/agent/middlewares")
def list_middlewares():
    """查看所有 AgentMiddleware（可直接传给 create_agent）"""
    mws = agent_loader.get_middlewares()
    return {
        "code": 0,
        "data": [{"name": getattr(m, "name", "?"), "type": type(m).__name__} for m in mws],
    }


@app.get("/v1/agent/registry")
def registry():
    """查看注册数据汇总"""
    return {"code": 0, "data": agent_loader.summary()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
