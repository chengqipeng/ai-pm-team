"""Agent 运行时 Demo — 对齐 neo-apps-ai-agent-service V2

完整链路对齐：
1. startup: AgentFactory._build_agent → create_agent(model, tools, middleware, checkpointer)
2. /v1/agent/chat: adapter.execute_agui_v2 → astream_events(input_data, config)
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from app.agent_loader import AgentLoader

logger = logging.getLogger(__name__)

app = FastAPI(title="Neo AI Agent Runtime Demo", version="0.1.0")
agent_loader = AgentLoader()
_agent = None

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config", "application.yml")


# ═══════════════════════════════════════════════════════════
# 辅助：加载 model 配置
# ═══════════════════════════════════════════════════════════

def _load_model_config() -> dict[str, str]:
    """从 application.yml 加载 model 配置，环境变量优先"""
    import yaml

    with open(_APP_CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    model_cfg = raw.get("model", {})

    def _resolve(value: str, env_key: str) -> str:
        """解析 ${ENV_KEY:default} 格式，环境变量优先"""
        env_val = os.environ.get(env_key)
        if env_val:
            return env_val
        if isinstance(value, str) and value.startswith("${"):
            return value.split(":", 1)[-1].rstrip("}")
        return value or ""

    return {
        "name": os.environ.get("AGENT_MODEL", model_cfg.get("name", "deepseek-v4-flash")),
        "api_key": _resolve(model_cfg.get("api_key", ""), "AGENT_API_KEY"),
        "api_base": _resolve(model_cfg.get("api_base", ""), "AGENT_API_BASE"),
    }


# ═══════════════════════════════════════════════════════════
# Startup — 对齐 AgentFactory._build_agent
# ═══════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    """启动时：Eureka 注册 + 构建 Agent"""
    global _agent
    from neo_ai_infr_eureka import EurekaGlobalClient
    await EurekaGlobalClient().register_eureka()

    agent_loader.load()
    _agent = _build_agent()


def _build_agent():
    """对齐 AgentFactory._build_agent

    流程：
    1. 从 application.yml 解析 model 配置 → ChatOpenAI
    2. get_base_tools() → tools（builtin + remote 统一转 BaseTool）
    3. get_middlewares() → middleware（builtin + remote 统一转 AgentMiddleware）
    4. build_system_prompt → 包含工具说明
    5. create_agent(model, tools, system_prompt, middleware, checkpointer)
    """
    from langchain.agents import create_agent
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.memory import MemorySaver

    # model 配置 — 从 application.yml 读取
    model_cfg = _load_model_config()
    model = ChatOpenAI(
        model=model_cfg["name"],
        api_key=model_cfg["api_key"],
        base_url=model_cfg["api_base"],
        max_tokens=4096,
        timeout=30,
    )

    # tools + middlewares — 从 registry*.yaml 合并加载
    tools = agent_loader.get_base_tools()
    middlewares = agent_loader.get_middlewares()

    # system_prompt — 对齐 build_system_prompt
    tool_descs = "\n".join(f"- {t.name}: {t.description}" for t in tools)
    system_prompt = (
        "你是 CRM 智能助手，帮助用户查询和管理客户、商机、管道数据。\n\n"
        f"## 可用工具\n{tool_descs}\n\n"
        "## 回答规范\n- 简洁明了\n- 数据使用表格展示\n- 操作前需确认"
    )

    # create_agent — 对齐 create_lead_agent
    agent = create_agent(
        model=model,
        tools=tools if tools else None,
        system_prompt=system_prompt,
        middleware=middlewares,
        checkpointer=MemorySaver(),
    )

    logger.info("[Agent] 构建完成: model=%s, tools=%d, middleware=%d", model_cfg["name"], len(tools), len(middlewares))
    return agent


# ═══════════════════════════════════════════════════════════
# /v1/agent/chat — 对齐 adapter.execute_agui_v2
# ═══════════════════════════════════════════════════════════

@app.post("/v1/agent/chat")
async def chat(request: dict):
    """Agent 对话 — 对齐 adapter.execute_agui_v2

    请求体：
        {"user_input": "查仁科客户", "thread_id": "th_001", "tenant_id": 292193, "user_id": "100006"}

    响应：SSE 流式输出
    """
    from langchain_core.messages import HumanMessage
    from app.agent_state import create_runtime_context

    user_input = request.get("user_input", "")
    thread_id = request.get("thread_id", "default")
    tenant_id = request.get("tenant_id", 292193)
    user_id = request.get("user_id", "100000000000000006")

    if not user_input:
        raise HTTPException(status_code=400, detail="user_input 不能为空")

    # 对齐 adapter.execute_agui_v2 构建 input_data
    input_data = {"messages": [HumanMessage(content=user_input)]}

    # 对齐 adapter.execute_agui_v2 构建 config
    run_id = uuid.uuid4().hex
    runtime_context = create_runtime_context()

    config = {
        "configurable": {
            "thread_id": thread_id,
            "conversation_id": thread_id,
            "message_id": run_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "language_code": "zh",
            "language_name": "zh-CN",
            "files": [],
            "extend_params": {},
            "runtime_context": runtime_context,
            "agent_name": "default",
            "run_id": run_id,
        },
        "recursion_limit": 10000,
    }

    # 对齐 astream_events 流式输出
    async def event_stream():
        async for event in _agent.astream_events(input_data, config=config, version="v2"):
            kind = event.get("event", "")
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk.content}, ensure_ascii=False)}\n\n"
            elif kind == "on_tool_start":
                tool_name = event.get("name", "")
                tool_input = event.get("data", {}).get("input", {})
                yield f"data: {json.dumps({'type': 'tool_start', 'name': tool_name, 'input': str(tool_input)[:200]}, ensure_ascii=False)}\n\n"
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
    tools = agent_loader.get_base_tools()
    return {"code": 0, "data": [{"name": t.name, "description": t.description[:80]} for t in tools]}


@app.get("/v1/agent/middlewares")
def list_middlewares():
    mws = agent_loader.get_middlewares()
    return {"code": 0, "data": [{"name": getattr(m, "name", "?"), "type": type(m).__name__} for m in mws]}


@app.get("/v1/agent/registry")
def registry():
    return {"code": 0, "data": agent_loader.summary()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
