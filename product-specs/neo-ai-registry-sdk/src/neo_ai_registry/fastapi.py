"""FastAPI 集成 — 自动生成 Provider 路由和应用

提供两个级别的封装：
1. create_provider_router(registry) — 生成路由（已有 Registry 时使用）
2. create_provider_app(...) — 一行代码创建完整 FastAPI 应用（新建 Provider 时使用）

Usage（最简方式 — 一行代码创建 Provider）:

    from neo_ai_registry.fastapi import create_provider_app

    app = create_provider_app(
        domain="marketing",
        config_path="config/tools.yaml",
        handler_map={
            "create_lead": create_lead_handler,
            "send_campaign": send_campaign_handler,
        },
    )

Usage（自定义方式 — 分步控制）:

    from neo_ai_registry.fastapi import create_provider_router

    registry = Registry(domain="sales")
    registry.register_tool(..., handler=...)
    router = create_provider_router(registry)
    app.include_router(router)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, APIRouter, HTTPException
from pydantic import BaseModel, Field

from neo_ai_registry.registry import Registry
from neo_ai_registry.models import ToolDefinition, MiddlewareDefinition, ToolType, MiddlewareHook
from neo_ai_registry.state import ToolState, _init_state_context, _collect_state_patch

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 请求/响应模型
# ═══════════════════════════════════════════════════════════

class ToolExecuteRequest(BaseModel):
    """Tool 执行请求体"""
    input: dict[str, Any] = Field(..., description="Tool 入参字典")
    state: dict[str, Any] = Field(default_factory=dict, description="AgentState 数据（双向传递）")


class MiddlewareExecuteRequest(BaseModel):
    """Middleware 执行请求体"""
    hook: str = Field(..., description="生命周期钩子名称")
    payload: dict[str, Any] = Field(..., description="钩子入参")
    state: dict[str, Any] = Field(default_factory=dict, description="AgentState 数据（双向传递）")


# ═══════════════════════════════════════════════════════════
# create_provider_router — 路由工厂
# ═══════════════════════════════════════════════════════════

def create_provider_router(registry: Registry) -> APIRouter:
    """创建 Provider 标准路由（自动处理 state 生命周期）

    生成的路由：
        POST /v2/tools/{api_key}/execute
        POST /v2/middlewares/{api_key}/execute

    Args:
        registry: 已注册 Tool/Middleware 的 Registry 实例。

    Returns:
        FastAPI APIRouter。
    """
    router = APIRouter()

    @router.post("/v2/tools/{api_key}/execute")
    async def execute_tool(api_key: str, request: ToolExecuteRequest):
        if not registry.has_tool(api_key):
            raise HTTPException(status_code=404, detail=f"Tool '{api_key}' not found")

        handler = registry.get_tool_handler(api_key)
        _init_state_context(request.state)
        tool_state = ToolState.from_dict(request.state)

        result = handler(request.input, tool_state)
        if hasattr(result, "__await__"):
            result = await result

        state_patch = _collect_state_patch()
        return {"code": 0, "data": {"result": result, "state_patch": state_patch}}

    @router.post("/v2/middlewares/{api_key}/execute")
    async def execute_middleware(api_key: str, request: MiddlewareExecuteRequest):
        if not registry.has_middleware(api_key):
            raise HTTPException(status_code=404, detail=f"Middleware '{api_key}' not found")

        handler = registry.get_middleware_handler(api_key)
        _init_state_context(request.state)
        tool_state = ToolState.from_dict(request.state)

        result = handler(request.hook, request.payload, tool_state)
        if hasattr(result, "__await__"):
            result = await result

        state_patch = _collect_state_patch()
        return {"code": 0, "data": {"result": result, "state_patch": state_patch}}

    return router


# ═══════════════════════════════════════════════════════════
# create_provider_app — 一行代码创建完整应用
# ═══════════════════════════════════════════════════════════

def create_provider_app(
    domain: str,
    handler_map: dict[str, Callable],
    config_path: str = "",
    middleware_handler_map: dict[str, Callable] | None = None,
    title: str = "",
    version: str = "0.1.0",
) -> FastAPI:
    """一行代码创建完整 Provider FastAPI 应用

    自动处理：
    - 从 YAML 配置文件加载 Tool/Middleware 定义
    - 匹配 handler_map 中的函数
    - 注册到 Registry
    - 生成标准路由（/v2/tools/... + /v2/middlewares/...）
    - 创建 /health 端点

    Args:
        domain: 业务域标识（如 "sales" / "marketing" / "basic"）。
        handler_map: api_key → handler 函数映射。
                     handler 签名：async def handler(input_data: dict, state: ToolState) -> dict
        config_path: Tool/Middleware 配置文件路径。
                     为空时在当前目录查找 config/tools.yaml。
        middleware_handler_map: api_key → middleware handler 映射（可选）。
                               handler 签名：async def handler(hook: str, payload: dict, state: ToolState) -> dict
        title: FastAPI 应用标题。为空自动生成。
        version: 应用版本号。

    Returns:
        完整配置的 FastAPI 应用实例（可直接 uvicorn 启动）。

    Usage:
        from neo_ai_registry.fastapi import create_provider_app

        app = create_provider_app(
            domain="marketing",
            config_path="config/tools.yaml",
            handler_map={
                "create_lead": create_lead,
                "send_campaign": send_campaign,
            },
            middleware_handler_map={
                "marketing_context": marketing_context_handler,
            },
        )
        # uvicorn main:app --port 8002
    """
    # 解析配置路径
    if not config_path:
        config_path = os.path.join(os.getcwd(), "config", "tools.yaml")

    # 加载配置 + 注册
    registry = _load_registry_from_config(
        config_path=config_path,
        domain=domain,
        handler_map=handler_map,
        middleware_handler_map=middleware_handler_map or {},
    )

    # 创建 FastAPI app
    app_title = title or f"Neo AI Provider ({domain})"
    app = FastAPI(title=app_title, version=version)

    # 注册路由
    router = create_provider_router(registry)
    app.include_router(router)

    # health 端点
    @app.get("/health")
    def health():
        return {"status": "ok", "domain": domain, "registered": registry.summary()}

    return app


def _load_registry_from_config(
    config_path: str,
    domain: str,
    handler_map: dict[str, Callable],
    middleware_handler_map: dict[str, Callable],
) -> Registry:
    """从配置文件加载 Tool/Middleware 定义并匹配 handler"""
    import yaml

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Provider 配置文件不存在: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    registry = Registry(domain=domain)

    # 注册 Tool
    for item in raw.get("tools", []):
        api_key = item["api_key"]
        handler = handler_map.get(api_key)
        if not handler:
            logger.warning("Tool '%s' 无对应 handler，跳过", api_key)
            continue

        tool_def = ToolDefinition(
            api_key=api_key,
            name=item.get("name", ""),
            description=item.get("description", ""),
            type=ToolType(item.get("type", "remote")),
            category=item.get("category", ""),
            tags=item.get("tags", []),
            timeout_ms=item.get("timeout_ms", 5000),
            read_only_flg=item.get("read_only_flg", True),
            input_schema=item.get("input_schema", {}),
        )
        registry.register_tool(tool_def, handler=handler)

    # 注册 Middleware
    for item in raw.get("middlewares", []):
        api_key = item["api_key"]
        handler = middleware_handler_map.get(api_key)
        if not handler:
            logger.warning("Middleware '%s' 无对应 handler，跳过", api_key)
            continue

        mw_def = MiddlewareDefinition(
            api_key=api_key,
            name=item.get("name", ""),
            description=item.get("description", ""),
            hooks=[MiddlewareHook(h) for h in item.get("hooks", [])],
            module_path=item.get("module_path", ""),
            class_name=item.get("class_name", ""),
            sort_num=item.get("sort_num", 0),
            required_features=item.get("required_features", []),
        )
        registry.register_middleware(mw_def, handler=handler)

    logger.info("Provider app 加载完成 [%s]: %s", domain, registry.summary())
    return registry
