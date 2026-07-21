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


@app.post("/v1/agent/invoke-tool")
async def invoke_tool(request: dict):
    """模拟 LangGraph 调用 BaseTool._arun（本地 + remote 统一路径）

    请求体：{"name": "query_customer", "args": {"customer_name": "仁科"}}
    """
    from app.agent_state import create_thread_state, create_configurable
    from langgraph.config import var_child_runnable_config

    tool_name = request.get("name", "")
    args = request.get("args", {})

    # 查找 BaseTool
    tools = agent_loader.get_base_tools()
    tool = next((t for t in tools if t.name == tool_name), None)
    if not tool:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

    # 模拟 LangGraph configurable（get_config() 能读到）
    graph_state = create_thread_state(user_input=str(args))
    configurable = create_configurable()

    # 设置 LangGraph config context（让 tool 内部 get_config() 能工作）
    config = {"configurable": configurable}
    token = var_child_runnable_config.set(config)

    try:
        # 注入 state（模拟 InjectedState）
        call_args = dict(args)
        call_args["state"] = graph_state

        # 通过 ainvoke 调用（和 LangGraph ToolNode 一致的调用方式）
        result = await tool.ainvoke(call_args, config=config)
    finally:
        var_child_runnable_config.reset(token)

    return {"code": 0, "data": {"tool": tool_name, "result": result}}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
