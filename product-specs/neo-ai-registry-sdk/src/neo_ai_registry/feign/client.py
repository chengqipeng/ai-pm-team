"""FeignClient — 基于可插拔 Transport 的远程调用

路由规范：
    - Tool:       POST /v2/tools/{api_key}/execute
    - Middleware:  POST /v2/middlewares/{api_key}/execute
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ToolFeignClient:
    """Tool Provider 的 FeignClient"""

    def __init__(self, app_name: str = "", transport: Any = None):
        self._app_name = app_name
        self._transport = transport

    def execute_tool(self, api_key: str, input_data: dict[str, Any], state: Any = None) -> dict[str, Any]:
        """同步执行 Tool"""
        from neo_ai_registry.state import ToolState

        if isinstance(state, ToolState):
            state_dict = state.to_dict()
        elif isinstance(state, dict):
            state_dict = state
        else:
            state_dict = {}

        payload: dict[str, Any] = {"input": input_data}
        if state_dict:
            payload["state"] = state_dict

        response = self._transport.invoke(
            app_name=self._app_name,
            service=f"/v2/tools/{api_key}/execute",
            method="POST",
            data=payload,
        )

        if isinstance(state, ToolState) and isinstance(response, dict):
            patch = response.get("state_patch", {})
            if patch:
                state.merge_patch(patch)

        return response

    async def async_execute_tool(self, api_key: str, input_data: dict[str, Any], state: Any = None) -> dict[str, Any]:
        """异步执行 Tool"""
        from neo_ai_registry.state import ToolState

        if isinstance(state, ToolState):
            state_dict = state.to_dict()
        elif isinstance(state, dict):
            state_dict = state
        else:
            state_dict = {}

        payload: dict[str, Any] = {"input": input_data}
        if state_dict:
            payload["state"] = state_dict

        if hasattr(self._transport, "async_invoke"):
            response = await self._transport.async_invoke(
                app_name=self._app_name,
                service=f"/v2/tools/{api_key}/execute",
                method="POST",
                data=payload,
            )
        else:
            response = self._transport.invoke(
                app_name=self._app_name,
                service=f"/v2/tools/{api_key}/execute",
                method="POST",
                data=payload,
            )

        if isinstance(state, ToolState) and isinstance(response, dict):
            patch = response.get("state_patch", {})
            if patch:
                state.merge_patch(patch)

        return response


class MiddlewareFeignClient:
    """Middleware Provider 的 FeignClient"""

    def __init__(self, app_name: str = "", transport: Any = None):
        self._app_name = app_name
        self._transport = transport

    def execute_middleware(self, api_key: str, hook: str, payload: dict[str, Any], state: Any = None) -> dict[str, Any]:
        """同步执行 Middleware"""
        from neo_ai_registry.state import ToolState

        if isinstance(state, ToolState):
            state_dict = state.to_dict()
        elif isinstance(state, dict):
            state_dict = state
        else:
            state_dict = {}

        request_data: dict[str, Any] = {"hook": hook, "payload": payload}
        if state_dict:
            request_data["state"] = state_dict

        response = self._transport.invoke(
            app_name=self._app_name,
            service=f"/v2/middlewares/{api_key}/execute",
            method="POST",
            data=request_data,
        )

        if isinstance(state, ToolState) and isinstance(response, dict):
            patch = response.get("state_patch", {})
            if patch:
                state.merge_patch(patch)

        return response
