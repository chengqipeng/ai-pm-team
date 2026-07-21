"""Agent 运行时 Demo — 主入口

从 config/registry.yaml 加载注册数据，
启动时通过 neo-ai-infr-eureka 注册到 Eureka。

Tool: 通过 /v1/agent/execute-tool 接口执行（builtin 本地 / remote FeignClient）
Middleware: 通过 get_middlewares() 返回列表，由 create_agent(middleware=[...]) 传入 LangGraph 图自动调度
"""
from fastapi import FastAPI, HTTPException

from app.agent_loader import AgentLoader

app = FastAPI(title="Neo AI Agent Runtime Demo", version="0.1.0")
agent_loader = AgentLoader()


@app.on_event("startup")
async def startup():
    """启动时：初始化 Eureka Discovery Client + 加载注册数据"""
    from neo_ai_infr_eureka import EurekaGlobalClient
    await EurekaGlobalClient().register_eureka()
    agent_loader.load()


@app.get("/health")
def health():
    return {"status": "ok", "loaded": agent_loader.summary()}


@app.post("/v1/agent/execute-tool")
async def execute_tool(request: dict):
    """Agent 执行 Tool — 演示 state + configurable 分离传递

    请求体：{"api_key": "query_customer", "input": {"customer_name": "仁科"}, "user_input": "查仁科"}
    """
    from app.agent_state import create_thread_state, create_configurable

    api_key = request.get("api_key", "")
    input_data = request.get("input", {})
    user_input = request.get("user_input", "")

    # 创建图 state（可读写）
    graph_state = create_thread_state(user_input=user_input)
    # 创建 configurable（只读）
    configurable = create_configurable()

    try:
        result = await agent_loader.async_execute_tool(
            api_key, input_data,
            agent_state=graph_state,
            configurable=configurable,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    # state 中 write_back 的变化
    state_keys = [k for k in graph_state if k not in ("messages",)]
    return {
        "code": 0,
        "data": {
            "result": result,
            "state": {k: graph_state[k] for k in state_keys},
            "configurable": configurable,
        },
    }


@app.post("/v1/agent/call-mcp-tool")
async def call_mcp_tool(request: dict):
    """Agent 调用 MCP Tool"""
    tool_name = request.get("tool_name", "")
    arguments = request.get("arguments", {})
    server_api_key = request.get("server_api_key", "")
    context = request.get("context", {})
    try:
        result = await agent_loader.async_call_mcp_tool(tool_name, arguments, server_api_key, context)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"code": 0, "data": result}


@app.get("/v1/agent/registry")
def list_registry():
    """查看注册数据（tools + middlewares）"""
    return {"code": 0, "data": agent_loader.summary()}


@app.get("/v1/agent/middlewares")
def list_middlewares():
    """查看已加载的 AgentMiddleware 列表（供 create_agent 使用）"""
    mws = agent_loader.get_middlewares()
    return {
        "code": 0,
        "data": [{"name": getattr(m, "name", "?"), "type": type(m).__name__} for m in mws],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
