"""Provider HTTP API 路由 — 暴露 Tool/Middleware 执行接口供 Agent FeignClient 调用

路由规范（与 FeignClient 调用路径一致）：
    POST /v2/tools/{api_key}/execute       → 执行 Tool
    POST /v2/middlewares/{api_key}/execute  → 执行 Middleware 钩子
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Any

from app.registry_setup import registry

router = APIRouter()


# ═══════════════════════════════════════════════════════════
# 请求/响应模型（含示例）
# ═══════════════════════════════════════════════════════════

class ToolExecuteRequest(BaseModel):
    """Tool 执行请求体"""
    input: dict[str, Any] = Field(
        ...,
        description="Tool 入参字典，字段由 ToolDefinition.input_schema 约束",
        json_schema_extra={"example": {"customer_name": "仁科", "industry": "互联网"}},
    )
    state: dict[str, Any] = Field(
        default_factory=dict,
        description="执行状态（双向传递）：Agent 传入完整 state，Provider 可通过 set() 回写",
        json_schema_extra={"example": {
            "tenant_id": 1,
            "user_id": 100,
            "thread_id": "th_abc123",
            "user_input": "查询仁科的商机",
            "query_count": 0,
        }},
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "查询客户",
                    "value": {
                        "input": {"customer_name": "仁科", "industry": "互联网"},
                        "context": {"tenant_id": 1, "user_id": 100, "thread_id": "th_abc"},
                    },
                },
                {
                    "summary": "更新商机",
                    "value": {
                        "input": {"opportunity_id": "opp_001", "stage": "商务谈判", "amount": 500000},
                        "context": {"tenant_id": 1, "user_id": 100},
                    },
                },
            ]
        }
    }


class MiddlewareExecuteRequest(BaseModel):
    """Middleware 执行请求体"""
    hook: str = Field(
        ...,
        description="生命周期钩子名称：before_agent / after_agent / before_model / after_model / wrap_tool_call",
        json_schema_extra={"example": "before_model"},
    )
    payload: dict[str, Any] = Field(
        ...,
        description="钩子入参，内容随 hook 类型不同：before_model 传 messages，after_model 传 ai_message+tool_calls，wrap_tool_call 传 tool_name+tool_args",
        json_schema_extra={"example": {
            "messages": [
                {"role": "user", "content": "帮我查一下仁科的商机"},
            ],
            "total_tokens_est": 3200,
        }},
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="执行上下文（tenant_id/user_id/thread_id/agent_name）",
        json_schema_extra={"example": {
            "tenant_id": 1,
            "user_id": 100,
            "thread_id": "th_abc123",
            "agent_name": "query-crm-data",
        }},
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "before_agent — 初始化查询状态",
                    "value": {
                        "hook": "before_agent",
                        "payload": {"messages": [{"role": "user", "content": "查我的客户"}], "message_count": 1},
                        "context": {"tenant_id": 1, "user_id": 100, "thread_id": "th_abc", "agent_name": "query-crm-data"},
                    },
                },
                {
                    "summary": "before_model — 注入销售上下文",
                    "value": {
                        "hook": "before_model",
                        "payload": {"messages": [{"role": "user", "content": "分析商机"}], "total_tokens_est": 5000},
                        "context": {"tenant_id": 1, "user_id": 100, "thread_id": "th_abc", "agent_name": "default"},
                    },
                },
                {
                    "summary": "after_model — 检查 LLM 输出",
                    "value": {
                        "hook": "after_model",
                        "payload": {
                            "ai_message": "我来帮你查询客户信息",
                            "tool_calls": [{"name": "extract_entity", "args": {"query": "仁科的商机"}}],
                        },
                        "context": {"tenant_id": 1, "thread_id": "th_abc", "agent_name": "query-crm-data"},
                    },
                },
                {
                    "summary": "wrap_tool_call — Tool 调用前拦截",
                    "value": {
                        "hook": "wrap_tool_call",
                        "payload": {"tool_call_id": "tc_01", "tool_name": "modify_data", "tool_args": {"action": "delete", "entity": "account"}},
                        "context": {"tenant_id": 1, "user_id": 100, "agent_name": "default"},
                    },
                },
            ]
        }
    }


class ToolExecuteResponse(BaseModel):
    """Tool 执行响应体"""
    code: int = Field(0, description="状态码，0=成功")
    data: dict[str, Any] = Field(
        ...,
        description="Tool 执行结果",
        json_schema_extra={"example": {
            "status": "success",
            "records": [{"id": "acc_001", "name": "仁科科技有限公司", "industry": "互联网"}],
            "total": 1,
        }},
    )


class MiddlewareExecuteResponse(BaseModel):
    """Middleware 执行响应体"""
    code: int = Field(0, description="状态码，0=成功")
    data: dict[str, Any] = Field(
        ...,
        description="Middleware 执行结果：action=continue（放行）/ modify（修改 state）/ abort（中止）",
        json_schema_extra={"example": {
            "action": "modify",
            "patch": {"inject_system_message": "[销售上下文] 当前用户负责 12 个活跃客户"},
        }},
    )


# ═══════════════════════════════════════════════════════════
# Tool 执行路由
# ═══════════════════════════════════════════════════════════

@router.post(
    "/v2/tools/{api_key}/execute",
    response_model=ToolExecuteResponse,
    summary="执行 Tool",
    description="""Agent 运行时通过 FeignClient 按服务名回调此接口执行远程 Tool。

**调用链路：** Agent → ToolFeignClient(app_name) → POST /v1/tools/{api_key}/execute → handler

**请求体：**
- `input`: Tool 入参（由 LLM Function Calling 生成，字段约束见 ToolDefinition.input_schema）
- `context`: 执行上下文（标识调用者身份和会话环境，同一会话内保持不变）
""",
    responses={
        200: {
            "description": "Tool 执行成功",
            "content": {"application/json": {"example": {
                "code": 0,
                "data": {"status": "success", "records": [{"id": "acc_001", "name": "仁科科技有限公司"}], "total": 1},
            }}},
        },
        404: {"description": "Tool 不存在"},
        500: {"description": "Tool handler 未注册或执行异常"},
    },
)
async def execute_tool(api_key: str, request: ToolExecuteRequest):
    if not registry.has_tool(api_key):
        raise HTTPException(status_code=404, detail=f"Tool '{api_key}' not found")

    from neo_ai_registry.state import ToolState, _init_state_context, _collect_state_patch
    handler = registry.get_tool_handler(api_key)

    # 初始化当前请求的 state 上下文（线程隔离）
    _init_state_context(request.state)
    tool_state = ToolState.from_dict(request.state)

    result = handler(request.input, tool_state)
    if hasattr(result, "__await__"):
        result = await result

    # 收集 handler 中 set_state 写入的 patch
    state_patch = _collect_state_patch()
    return {"code": 0, "data": {"result": result, "state_patch": state_patch}}


# ═══════════════════════════════════════════════════════════
# Middleware 执行路由
# ═══════════════════════════════════════════════════════════

@router.post(
    "/v2/middlewares/{api_key}/execute",
    response_model=MiddlewareExecuteResponse,
    summary="执行 Middleware 钩子",
    description="""Agent 运行时通过 FeignClient 按服务名回调此接口执行远程 Middleware 的生命周期钩子。

**调用链路：** Agent → MiddlewareFeignClient(app_name) → POST /v1/middlewares/{api_key}/execute → handler

**请求体：**
- `hook`: 钩子名称 — 标识 Agent 生命周期的哪个阶段触发
- `payload`: 当前钩子的业务数据 — 每次调用内容不同，取决于当前执行状态
- `context`: 执行上下文 — 调用者身份和环境信息，同一会话内固定

**返回值约定：**
- `{"action": "continue"}` — 不修改，Agent 继续执行
- `{"action": "modify", "patch": {...}}` — 修改 state，patch 合并到 Agent 状态
- `{"action": "abort", "message": "..."}` — 中止流程，message 返回给用户
""",
    responses={
        200: {
            "description": "Middleware 执行成功",
            "content": {"application/json": {"examples": {
                "continue": {"value": {"code": 0, "data": {"action": "continue"}}},
                "modify": {"value": {"code": 0, "data": {"action": "modify", "patch": {"crm_query_state": {"entities_identified": ["account"]}}}}},
                "abort": {"value": {"code": 0, "data": {"action": "abort", "message": "无权限执行此操作"}}},
            }}},
        },
        404: {"description": "Middleware 不存在"},
        500: {"description": "Middleware handler 未注册或执行异常"},
    },
)
async def execute_middleware(api_key: str, request: MiddlewareExecuteRequest):
    if not registry.has_middleware(api_key):
        raise HTTPException(status_code=404, detail=f"Middleware '{api_key}' not found")

    handler = registry.get_middleware_handler(api_key)
    result = handler(request.hook, request.payload, request.context)
    if hasattr(result, "__await__"):
        result = await result
    return {"code": 0, "data": result}
