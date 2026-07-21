"""RemoteMiddlewareAdapter — 将 MiddlewareDefinition 转换为 AgentMiddleware

参考 neo-apps-ai-agent-service 的 _create_selective_tracing_wrapper 设计：
动态生成类，只覆写 hooks 中声明的方法，确保 LangGraph 只为该 middleware
注册对应阶段的图节点，不产生多余的空节点。

Usage:
    from neo_ai_registry.middleware_adapter import create_remote_middleware

    definition = MiddlewareDefinition(api_key="crm_query_state", service="neo-ai-provider-demo", hooks=["before_agent"])
    adapter = create_remote_middleware(definition, transport)

    # 直接作为 AgentMiddleware 使用
    create_agent(middleware=[..., adapter])

批量转换:
    from neo_ai_registry.middleware_adapter import create_remote_middlewares

    adapters = create_remote_middlewares(definitions, transport)
    create_agent(middleware=[*builtin_mws, *adapters])
"""
from __future__ import annotations

import logging
from typing import Any

from neo_ai_registry.models import MiddlewareDefinition
from neo_ai_registry.state import ToolState

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 远程调用核心逻辑
# ═══════════════════════════════════════════════════════════

def _remote_call_sync(self, hook: str, state: Any) -> dict[str, Any] | None:
    """同步远程调用 Provider middleware"""
    from langgraph.config import get_config

    state_dict = dict(state) if isinstance(state, dict) else {}
    tool_state = ToolState.from_agent_state(state_dict)

    raw_cfg = get_config().get("configurable", {})
    configurable = {}
    for k, v in raw_cfg.items():
        if k.startswith("__"):
            continue
        try:
            import json as _json
            _json.dumps(v, default=str)
            configurable[k] = v
        except (TypeError, ValueError):
            pass

    request_data = {
        "hook": hook,
        "payload": tool_state.to_dict(),
        "state": tool_state.to_dict(),
        "configurable": configurable,
    }

    response = self._transport.invoke(
        app_name=self._mw_service,
        service=f"/v2/middlewares/{self._mw_api_key}/execute",
        method="POST",
        data=request_data,
    )

    if isinstance(response, dict):
        state_patch = response.get("state_patch", {})
        if state_patch:
            tool_state.merge_patch(state_patch)
            if isinstance(state, dict):
                tool_state.write_back(state)
        result = response.get("result", {})
        if isinstance(result, dict) and result.get("action") == "modify":
            return result.get("patch")

    return None


async def _remote_call_async(self, hook: str, state: Any) -> dict[str, Any] | None:
    """异步远程调用 Provider middleware"""
    from langgraph.config import get_config

    state_dict = dict(state) if isinstance(state, dict) else {}
    tool_state = ToolState.from_agent_state(state_dict)

    raw_cfg = get_config().get("configurable", {})
    configurable = {}
    for k, v in raw_cfg.items():
        if k.startswith("__"):
            continue
        try:
            import json as _json
            _json.dumps(v, default=str)
            configurable[k] = v
        except (TypeError, ValueError):
            pass

    request_data = {
        "hook": hook,
        "payload": tool_state.to_dict(),
        "state": tool_state.to_dict(),
        "configurable": configurable,
    }

    if hasattr(self._transport, "async_invoke"):
        response = await self._transport.async_invoke(
            app_name=self._mw_service,
            service=f"/v2/middlewares/{self._mw_api_key}/execute",
            method="POST",
            data=request_data,
        )
    else:
        response = self._transport.invoke(
            app_name=self._mw_service,
            service=f"/v2/middlewares/{self._mw_api_key}/execute",
            method="POST",
            data=request_data,
        )

    if isinstance(response, dict):
        state_patch = response.get("state_patch", {})
        if state_patch:
            tool_state.merge_patch(state_patch)
            if isinstance(state, dict):
                tool_state.write_back(state)
        result = response.get("result", {})
        if isinstance(result, dict) and result.get("action") == "modify":
            return result.get("patch")

    return None


# ═══════════════════════════════════════════════════════════
# 各钩子方法工厂
# ═══════════════════════════════════════════════════════════

def _make_before_agent():
    def before_agent(self, state, runtime):
        return _remote_call_sync(self, "before_agent", state)
    return before_agent


def _make_abefore_agent():
    async def abefore_agent(self, state, runtime):
        return await _remote_call_async(self, "before_agent", state)
    return abefore_agent


def _make_before_model():
    def before_model(self, state, runtime):
        return _remote_call_sync(self, "before_model", state)
    return before_model


def _make_abefore_model():
    async def abefore_model(self, state, runtime):
        return await _remote_call_async(self, "before_model", state)
    return abefore_model


def _make_after_model():
    def after_model(self, state, runtime):
        return _remote_call_sync(self, "after_model", state)
    return after_model


def _make_aafter_model():
    async def aafter_model(self, state, runtime):
        return await _remote_call_async(self, "after_model", state)
    return aafter_model


def _make_after_agent():
    def after_agent(self, state, runtime):
        return _remote_call_sync(self, "after_agent", state)
    return after_agent


def _make_aafter_agent():
    async def aafter_agent(self, state, runtime):
        return await _remote_call_async(self, "after_agent", state)
    return aafter_agent


def _make_wrap_tool_call():
    def wrap_tool_call(self, request, handler):
        tool_call = request.tool_call if hasattr(request, 'tool_call') else {}
        # wrap_tool_call 场景：state 是 tool_call 信息
        state_dict = {"tool_name": tool_call.get("name", ""), "args": tool_call.get("args", {})}
        tool_state = ToolState.from_agent_state(state_dict)
        request_data = {
            "hook": "wrap_tool_call",
            "payload": state_dict,
            "state": tool_state.to_dict(),
        }
        try:
            response = self._transport.invoke(
                app_name=self._mw_service,
                service=f"/v2/middlewares/{self._mw_api_key}/execute",
                method="POST",
                data=request_data,
            )
        except Exception as e:
            logger.warning("[RemoteMiddleware] %s/wrap_tool_call 调用失败: %s", self._mw_api_key, e)
            return handler(request)
        if isinstance(response, dict):
            result = response.get("result", {})
            if isinstance(result, dict) and result.get("action") == "block":
                from langchain_core.messages import ToolMessage
                return ToolMessage(
                    content=result.get("reason", "操作被远程中间件拦截"),
                    tool_call_id=tool_call.get("id", ""),
                )
        return handler(request)
    return wrap_tool_call


def _make_awrap_tool_call():
    async def awrap_tool_call(self, request, handler):
        tool_call = request.tool_call if hasattr(request, 'tool_call') else {}
        state_dict = {"tool_name": tool_call.get("name", ""), "args": tool_call.get("args", {})}
        tool_state = ToolState.from_agent_state(state_dict)
        request_data = {
            "hook": "wrap_tool_call",
            "payload": state_dict,
            "state": tool_state.to_dict(),
        }
        try:
            if hasattr(self._transport, "async_invoke"):
                response = await self._transport.async_invoke(
                    app_name=self._mw_service,
                    service=f"/v2/middlewares/{self._mw_api_key}/execute",
                    method="POST",
                    data=request_data,
                )
            else:
                response = self._transport.invoke(
                    app_name=self._mw_service,
                    service=f"/v2/middlewares/{self._mw_api_key}/execute",
                    method="POST",
                    data=request_data,
                )
        except Exception as e:
            logger.warning("[RemoteMiddleware] %s/wrap_tool_call 异步调用失败: %s", self._mw_api_key, e)
            return await handler(request)
        if isinstance(response, dict):
            result = response.get("result", {})
            if isinstance(result, dict) and result.get("action") == "block":
                from langchain_core.messages import ToolMessage
                return ToolMessage(
                    content=result.get("reason", "操作被远程中间件拦截"),
                    tool_call_id=tool_call.get("id", ""),
                )
        return await handler(request)
    return awrap_tool_call


# ═══════════════════════════════════════════════════════════
# 动态类生成（核心 — 参考 _create_selective_tracing_wrapper）
# ═══════════════════════════════════════════════════════════

def create_remote_middleware(definition: MiddlewareDefinition, transport: Any) -> Any:
    """将 Remote MiddlewareDefinition 转换为 AgentMiddleware 实例

    动态生成类，只覆写 hooks 中声明的方法。
    LangGraph 的 create_agent 通过 `cls.METHOD is not AgentMiddleware.METHOD` 检测覆写，
    只为实际覆写的方法注册图节点，不产生多余空节点。

    Args:
        definition: Remote Middleware 注册定义。
        transport: Transport 实例（NeoApiTransport）。

    Returns:
        AgentMiddleware 实例（动态生成的子类）。
    """
    from langchain.agents.middleware.types import AgentMiddleware

    hooks = set(definition.hooks)

    # 动态构建类属性 — 只包含 hooks 中声明的方法
    attrs: dict[str, Any] = {
        "name": property(lambda self: self._mw_api_key),
    }

    if "before_agent" in hooks:
        attrs["before_agent"] = _make_before_agent()
        attrs["abefore_agent"] = _make_abefore_agent()

    if "before_model" in hooks:
        attrs["before_model"] = _make_before_model()
        attrs["abefore_model"] = _make_abefore_model()

    if "after_model" in hooks:
        attrs["after_model"] = _make_after_model()
        attrs["aafter_model"] = _make_aafter_model()

    if "after_agent" in hooks:
        attrs["after_agent"] = _make_after_agent()
        attrs["aafter_agent"] = _make_aafter_agent()

    if "wrap_tool_call" in hooks:
        attrs["wrap_tool_call"] = _make_wrap_tool_call()
        attrs["awrap_tool_call"] = _make_awrap_tool_call()

    # 动态创建类 — 继承 AgentMiddleware
    cls_name = f"Remote_{definition.api_key.replace('-', '_')}"
    remote_cls = type(cls_name, (AgentMiddleware,), attrs)

    # 实例化并注入配置
    instance = object.__new__(remote_cls)
    AgentMiddleware.__init__(instance)
    instance._mw_api_key = definition.api_key
    instance._mw_service = definition.service
    instance._transport = transport

    return instance


def create_remote_middlewares(definitions: list[MiddlewareDefinition], transport: Any) -> list:
    """批量将 Remote MiddlewareDefinition 列表转换为 AgentMiddleware 列表

    按 sort_num 排序后转换。

    Args:
        definitions: Remote Middleware 定义列表。
        transport: Transport 实例。

    Returns:
        AgentMiddleware 实例列表（已排序）。
    """
    sorted_defs = sorted(definitions, key=lambda d: d.sort_num)
    return [create_remote_middleware(d, transport) for d in sorted_defs]
