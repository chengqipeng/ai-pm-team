"""Provider 抽象基类 — 按类型定义接口

业务域服务实现这些接口，提供 HTTP API 供 Agent 运行时通过 FeignClient 远程调用。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from neo_ai_registry.models import MiddlewareDefinition


class ToolProvider(ABC):
    """Tool Provider 抽象接口"""

    @abstractmethod
    async def execute_tool(
        self,
        api_key: str,
        input_data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """根据 api_key 执行指定 Tool

        Args:
            api_key: Tool 唯一标识。
            input_data: Tool 入参字典。
            context: 执行上下文（tenant_id/user_id/thread_id/message_id/trace_id）。

        Returns:
            Tool 执行结果字典。
        """
        ...


class MiddlewareProvider(ABC):
    """Middleware Provider 抽象接口"""

    @abstractmethod
    async def execute_middleware(
        self,
        api_key: str,
        hook: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """根据 api_key 执行指定 Middleware 的生命周期钩子

        Args:
            api_key: Middleware 唯一标识。
            hook: 钩子名称（before_agent/after_agent/before_model/after_model/wrap_tool_call）。
            payload: 钩子入参字典。
            context: 执行上下文。

        Returns:
            执行结果（action: continue/modify/abort + patch/message）。
        """
        ...
