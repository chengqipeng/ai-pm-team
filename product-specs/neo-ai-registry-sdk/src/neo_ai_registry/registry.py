"""Registry — 内存注册表（手动内置数据）

业务域服务在代码中手动注册 Tool / Middleware 定义及其 handler，
通过 Provider 接口暴露 HTTP API 供 Agent 运行时远程调用。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from .models import ToolDefinition, MiddlewareDefinition
from .providers.base import ToolProvider, MiddlewareProvider
from .validator import validate_tool, validate_middleware

logger = logging.getLogger(__name__)

# Handler 类型定义
ToolHandler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]
MiddlewareHandler = Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


class Registry(ToolProvider, MiddlewareProvider):
    """内存注册表 — 手动内置数据，实现 Provider 接口

    业务域服务创建 Registry 实例，手动注册 Tool/Middleware 定义及 handler，
    然后通过 HTTP 路由层暴露 Provider 接口供 Agent FeignClient 调用。
    """

    def __init__(self, domain: str = "", auto_validate: bool = True):
        """初始化 Registry 实例

        Args:
            domain: 当前服务所属业务域标识（如 "sales" / "marketing" / "basic"）。
                    注册时如果实体本身未指定 domain，会自动填充此值。
            auto_validate: 注册时是否自动执行 Schema 校验（默认 True）。
        """
        self._domain = domain
        self._auto_validate = auto_validate
        self._tools: dict[str, ToolDefinition] = {}
        self._middlewares: dict[str, MiddlewareDefinition] = {}
        self._tool_handlers: dict[str, ToolHandler] = {}
        self._middleware_handlers: dict[str, MiddlewareHandler] = {}

    # ═══════════════════════════════════════════════════════════
    # 注册 API（业务域服务启动时手动调用）
    # ═══════════════════════════════════════════════════════════

    def register_tool(self, tool: ToolDefinition, handler: ToolHandler | None = None) -> None:
        """注册 Tool 定义及其执行 handler

        Args:
            tool: Tool 定义对象（ToolDefinition 实例）。
            handler: Tool 执行函数（必须提供，否则调用时报错）。签名为：
                     async def handler(input_data: dict, context: dict) -> dict
                     或同步版本 def handler(input_data: dict, context: dict) -> dict。

        Raises:
            RegistryValidationError: auto_validate=True 且定义不合法时抛出。
            ValueError: handler 为 None 时抛出。
        """
        if self._auto_validate:
            validate_tool(tool)
        if handler is None:
            raise ValueError(f"Tool '{tool.api_key}' 注册时必须提供 handler")
        if not tool.domain:
            tool.domain = self._domain
        self._tools[tool.api_key] = tool
        self._tool_handlers[tool.api_key] = handler
        logger.info("[Registry:%s] Tool 注册: %s", self._domain, tool.api_key)

    def register_middleware(
        self,
        mw: MiddlewareDefinition,
        handler: MiddlewareHandler | None = None,
    ) -> None:
        """注册 Middleware 定义及其执行 handler

        Args:
            mw: Middleware 定义对象（MiddlewareDefinition 实例）。
            handler: Middleware 执行函数（必须提供）。签名为：
                     async def handler(hook: str, payload: dict, context: dict) -> dict

                     返回值约定：
                     - {"action": "continue"} — 不修改，继续
                     - {"action": "modify", "patch": {...}} — 修改 state
                     - {"action": "abort", "message": "..."} — 中止流程

        Raises:
            RegistryValidationError: auto_validate=True 且定义不合法时抛出。
            ValueError: handler 为 None 时抛出。
        """
        if self._auto_validate:
            validate_middleware(mw)
        if handler is None:
            raise ValueError(f"Middleware '{mw.api_key}' 注册时必须提供 handler")
        self._middlewares[mw.api_key] = mw
        self._middleware_handlers[mw.api_key] = handler
        logger.info("[Registry:%s] Middleware 注册: %s", self._domain, mw.api_key)

    # ═══════════════════════════════════════════════════════════
    # ToolProvider 实现
    # ═══════════════════════════════════════════════════════════

    async def execute_tool(
        self,
        api_key: str,
        input_data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """根据 api_key 执行已注册的 Tool handler

        本方法为 async，可安全在 FastAPI 等异步框架中直接 await 调用。
        支持 async handler 和 sync handler。

        Args:
            api_key: Tool 唯一标识。
            input_data: Tool 入参字典。
            context: 执行上下文（可选）。

        Returns:
            handler 返回值（dict）。

        Raises:
            KeyError: api_key 未注册时抛出。
        """
        if api_key not in self._tool_handlers:
            raise KeyError(f"Tool '{api_key}' 不存在，已注册: {list(self._tool_handlers.keys())}")
        handler = self._tool_handlers[api_key]
        ctx = context or {}
        result = handler(input_data, ctx)
        # 如果 handler 返回协程，await 它
        if hasattr(result, "__await__"):
            return await result
        return result

    # ═══════════════════════════════════════════════════════════
    # MiddlewareProvider 实现
    # ═══════════════════════════════════════════════════════════

    async def execute_middleware(
        self,
        api_key: str,
        hook: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """根据 api_key 执行已注册的 Middleware handler

        本方法为 async，可安全在 FastAPI 等异步框架中直接 await 调用。

        Args:
            api_key: Middleware 唯一标识。
            hook: 生命周期钩子名称。
            payload: 钩子入参字典。
            context: 执行上下文（可选）。

        Returns:
            handler 返回值（dict），包含 action + patch/message。

        Raises:
            KeyError: api_key 未注册时抛出。
        """
        if api_key not in self._middleware_handlers:
            raise KeyError(f"Middleware '{api_key}' 不存在，已注册: {list(self._middleware_handlers.keys())}")
        handler = self._middleware_handlers[api_key]
        ctx = context or {}
        result = handler(hook, payload, ctx)
        if hasattr(result, "__await__"):
            return await result
        return result

    # ═══════════════════════════════════════════════════════════
    # 查询方法（供路由层使用）
    # ═══════════════════════════════════════════════════════════

    def get_tool_handler(self, api_key: str) -> ToolHandler:
        """获取 Tool handler 函数（供路由层直接 await 调用）

        Args:
            api_key: Tool 唯一标识。

        Returns:
            handler 函数。

        Raises:
            KeyError: api_key 未注册时抛出。
        """
        if api_key not in self._tool_handlers:
            raise KeyError(f"Tool '{api_key}' 不存在，已注册: {list(self._tool_handlers.keys())}")
        return self._tool_handlers[api_key]

    def get_middleware_handler(self, api_key: str) -> MiddlewareHandler:
        """获取 Middleware handler 函数（供路由层直接 await 调用）

        Args:
            api_key: Middleware 唯一标识。

        Returns:
            handler 函数。

        Raises:
            KeyError: api_key 未注册时抛出。
        """
        if api_key not in self._middleware_handlers:
            raise KeyError(f"Middleware '{api_key}' 不存在，已注册: {list(self._middleware_handlers.keys())}")
        return self._middleware_handlers[api_key]

    # ═══════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════

    def has_tool(self, api_key: str) -> bool:
        """检查 Tool 是否已注册"""
        return api_key in self._tool_handlers

    def has_middleware(self, api_key: str) -> bool:
        """检查 Middleware 是否已注册"""
        return api_key in self._middleware_handlers

    def summary(self) -> dict[str, int]:
        """返回注册数量汇总"""
        return {"tools": len(self._tools), "middlewares": len(self._middlewares)}

    @property
    def domain(self) -> str:
        """当前 Registry 所属业务域标识"""
        return self._domain
