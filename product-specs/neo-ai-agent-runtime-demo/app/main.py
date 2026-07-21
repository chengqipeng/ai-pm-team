"""Agent 运行时 Demo — 主入口

从 config/registry.yaml 加载注册数据，
通过 Transport 层远程调用 Provider(Tool/Middleware) 和 MCP Service。
"""
from fastapi import FastAPI, HTTPException

from app.agent_loader import AgentLoader

app = FastAPI(title="Neo AI Agent Runtime Demo", version="0.1.0")
agent_loader = AgentLoader()


@app.on_event("startup")
async def startup():
    """启动时加载注册数据"""
    agent_loader.load()


@app.get("/health")
def health():
    return {"status": "ok", "loaded": agent_loader.summary()}


@app.post("/v1/agent/execute-tool")
async def execute_tool(request: dict):
    """Agent 执行 Tool — 演示完整 AgentState ↔ ToolState 转换

    请求体：{"api_key": "query_customer", "input": {"customer_name": "仁科"}, "user_input": "查仁科"}
    """
    from app.agent_state import create_agent_state

    api_key = request.get("api_key", "")
    input_data = request.get("input", {})
    user_input = request.get("user_input", "")

    # 创建 AgentState（模拟 LangGraph 运行时）
    agent_state = create_agent_state(user_input=user_input)

    try:
        result = agent_loader.execute_tool(api_key, input_data, agent_state=agent_state)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    # 返回结果 + Provider write_back 写入的字段
    written_keys = [k for k in agent_state if k not in ("messages", "interrupt_event")]
    return {"code": 0, "data": {"result": result, "agent_state": {k: agent_state[k] for k in written_keys}}}


@app.post("/v1/agent/execute-middleware")
async def execute_middleware(request: dict):
    """Agent 执行 Middleware"""
    api_key = request.get("api_key", "")
    hook = request.get("hook", "")
    payload = request.get("payload", {})
    context = request.get("context", {})
    try:
        result = agent_loader.execute_middleware(api_key, hook, payload, context)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"code": 0, "data": result}


@app.post("/v1/agent/call-mcp-tool")
async def call_mcp_tool(request: dict):
    """Agent 调用 MCP Tool"""
    tool_name = request.get("tool_name", "")
    arguments = request.get("arguments", {})
    server_api_key = request.get("server_api_key", "")
    context = request.get("context", {})
    try:
        result = agent_loader.call_mcp_tool(tool_name, arguments, server_api_key, context)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"code": 0, "data": result}


@app.get("/v1/agent/mcp-tools")
async def list_mcp_tools(server_api_key: str = ""):
    """列出 MCP Tool"""
    tools = agent_loader.list_mcp_tools(server_api_key)
    return {"code": 0, "data": [t.model_dump() for t in tools]}


@app.get("/v1/agent/mcp-servers")
async def list_mcp_servers():
    """列出 MCP Server"""
    servers = agent_loader.list_mcp_servers()
    return {"code": 0, "data": [s.model_dump() for s in servers]}


@app.get("/v1/agent/registry")
def list_registry():
    """查看注册数据"""
    return {"code": 0, "data": {"tools": agent_loader.tool_keys, "middlewares": agent_loader.middleware_keys}}
