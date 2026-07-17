"""Provider 抽象层 — 按类型定义接口

Tool 和 Middleware 均采用远程回调模式执行。
业务服务实现 Provider 接口，Agent 运行时通过 FeignClient 按服务名调用。
"""

from neo_ai_registry.providers.base import (
    ToolProvider,
    MiddlewareProvider,
)

__all__ = [
    "ToolProvider",
    "MiddlewareProvider",
]
