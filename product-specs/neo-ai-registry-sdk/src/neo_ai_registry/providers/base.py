"""Provider 抽象基类 — 按类型定义接口

业务域服务实现这些接口，提供 HTTP API 供 Agent 运行时通过 FeignClient 远程调用。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from neo_ai_registry.state import ToolState


class ToolProvider(ABC):
    """Tool Provider 抽象接口"""

    @abstractmethod
    async def execute_tool(
        self,
        api_key: str,
        input_data: dict[str, Any],
        state: ToolState | None = None,
    ) -> dict[str, Any]:
        """根据 api_key 执行指定 Tool

        Args:
            api_key: Tool 唯一标识。
            input_data: Tool 入参字典。
            state: 执行状态（双向传递）。Provider 可通过 state.set() 回写数据。

        Returns:
            Tool 执行结果字典。包含 result + state_patch。
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
        state: ToolState | None = None,
    ) -> dict[str, Any]:
        """根据 api_key 执行指定 Middleware 的生命周期钩子

        Args:
            api_key: Middleware 唯一标识。
            hook: 钩子名称。
            payload: 钩子入参字典。
            state: 执行状态（双向传递）。

        Returns:
            执行结果（action: continue/modify/abort + state_patch）。
        """
        ...
