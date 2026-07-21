"""Agent 运行时 Demo — 对齐 neo-apps-ai-agent-service

完整链路：
1. startup: 加载 tools + middlewares → create_agent 构建 LangGraph 图
2. /v1/agent/chat: 接收用户输入 → agent.astream_events → SSE 流式输出

对齐 neo-apps-ai-agent-service 的 adapter.py：
    input_data = {"messages": [HumanMessage(content=user_input)]}
    config = {"configurable": {"thread_id": ..., "tenant_id": ..., ...}}
    astream = agent.astream_events(input_data, config=config, version="v2")
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from app.agent_loader import AgentLoader

logger = logging.getLogger(__name__)

app = FastAPI(title="Neo AI Agent Runtime Demo", version="0.1.0")
agent_loader = AgentLoader()
_agent = None  # CompiledStateGraph


@app.on_event("startup")
async def startup():
    """启动时：Eureka 注册 + 加载 tools/middlewares + 构建 Agent"""
    global _agent
    from neo_ai_infr_eureka import EurekaGlobalClient
    await EurekaGlobalClient().register_eureka()

    agent_loader.load()

    # 构建 Agent（对齐 neo-apps-ai-agent-service AgentFactory._build_agent）
    _agent = _build_agent()


def _build_agent():
    """构建 LangGraph Agent — 对齐 AgentFactory._build_agent"""
    from langchain.agents import create_agent
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.memory import MemorySaver
    import yaml

    # 读取 model 配置
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "registry.yaml")
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    model_cfg = raw.get("model", {})

    model_name = os.environ.get("AGENT_MODEL", model_cfg.get("name", "deepseek-v4-flash"))
    api_key = os.environ.get("AGENT_API_KEY", model_cfg.get("api_key", ""))
    api_base = os.environ.get("AGENT_API_BASE", model_cfg.get("api_base", "https://tokenhub.tencentmaas.com/v1"))

    # 解析环境变量占位符
    if api_key.startswith("${"):
        api_key = api_key.split(":")[-1].rstrip("}")
    if api_base.startswith("${"):
        api_base = api_base.split(":")[-1].rstrip("}")

    model = ChatOpenAI(model=model_name, api_key=api_key, base_url=api_base, max_tokens=4096)

    # 获取 tools + middlewares
    tools = agent_loader.get_base_tools()
    middlewares = agent_loader.get_middlewares()

    # system prompt
    tool_names = [t.name for t in tools]
    system_prompt = (
        "你是 CRM 智能助手，可以帮助用户查询客户、商机、管道数据。\n"
        f"可用工具：{', '.join(tool_names)}\n"
        "回答简洁，数据使用表格展示。"
    )

    # checkpointer（内存，支持多轮对话）
    checkpointer = MemorySaver()

    # 构建 Agent
    agent = create_agent(
        model=model,
        tools=tools if tools else None,
        system_prompt=system_prompt,
        middleware=middlewares,
        checkpointer=checkpointer,
    )

    logger.info("[Agent] 构建完成: model=%s, tools=%d, middleware=%d", model_name, len(tools), len(middlewares))
    return agent


# ═══════════════════════════════════════════════════════════
# /v1/agent/chat — 对齐 adapter.execute_agui
# ═══════════════════════════════════════════════════════════

@app.post("/v1/agent/chat")
async def chat(request: dict):
    """Agent 对话 — 对齐 neo-apps-ai-agent-service adapter.execute_agui

    请求体：{"user_input": "查仁科客户", "thread_id": "th_001"}
    响应：SSE 流式输出
    """
    from langchain_core.messages import HumanMessage
    from app.agent_state import create_configurable

    user_input = request.get("user_input", "")
    thread_id = request.get("thread_id", "default")

    if not user_input:
        raise HTTPException(status_code=400, detail="user_input 不能为空")

    # 构建 input_data（只有 messages）
    input_data = {"messages": [HumanMessage(content=user_input)]}

    # 构建 config（configurable）
    configurable = create_configurable(thread_id=thread_id)
    config = {
        "configurable": configurable,
        "recursion_limit": 100,
    }

    # 流式执行
    async def event_stream():
        async for event in _agent.astream_events(input_data, config=config, version="v2"):
            kind = event.get("event", "")
            # 过滤关键事件输出
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk.content}, ensure_ascii=False)}\n\n"
            elif kind == "on_tool_start":
                tool_name = event.get("name", "")
                yield f"data: {json.dumps({'type': 'tool_start', 'name': tool_name}, ensure_ascii=False)}\n\n"
            elif kind == "on_tool_end":
                tool_name = event.get("name", "")
                output = str(event.get("data", {}).get("output", ""))[:200]
                yield f"data: {json.dumps({'type': 'tool_end', 'name': tool_name, 'output': output}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ═══════════════════════════════════════════════════════════
# 查询接口
# ═══════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {"status": "ok", "agent_ready": _agent is not None, "loaded": agent_loader.summary()}


@app.get("/v1/agent/tools")
def list_tools():
    """查看所有 BaseTool"""
    tools = agent_loader.get_base_tools()
    return {"code": 0, "data": [{"name": t.name, "description": t.description[:80]} for t in tools]}


@app.get("/v1/agent/middlewares")
def list_middlewares():
    """查看所有 AgentMiddleware"""
    mws = agent_loader.get_middlewares()
    return {"code": 0, "data": [{"name": getattr(m, "name", "?"), "type": type(m).__name__} for m in mws]}


@app.get("/v1/agent/registry")
def registry():
    return {"code": 0, "data": agent_loader.summary()}


@app.post("/v1/agent/invoke-tool")
async def invoke_tool(request: dict):
    """直接调用单个 BaseTool（测试用）"""
    from app.agent_state import create_thread_state, create_configurable
    from langgraph.config import var_child_runnable_config

    tool_name = request.get("name", "")
    args = request.get("args", {})

    tools = agent_loader.get_base_tools()
    tool = next((t for t in tools if t.name == tool_name), None)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

    graph_state = create_thread_state(user_input=str(args))
    configurable = create_configurable()
    config = {"configurable": configurable}
    token = var_child_runnable_config.set(config)

    try:
        call_args = dict(args)
        call_args["state"] = graph_state
        result = await tool.ainvoke(call_args, config=config)
    finally:
        var_child_runnable_config.reset(token)

    return {"code": 0, "data": {"tool": tool_name, "result": result}}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
