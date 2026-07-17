"""FeignClient 实现 — 基于可插拔 Transport 的远程调用

传输层抽象：
    - 生产环境: NeoApiTransport（基于 NeoApiClient，自动传递上下文+trace）
    - 开发环境: HttpxTransport（基于 httpx，直连无依赖）

路由规范：
    - Tool:       POST /v1/tools/{api_key}/execute  → execute_tool
    - Middleware:  POST /v1/middlewares/{api_key}/execute → execute_middleware
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# ServiceResolver（保留，供 HttpxTransport 使用）
# ═══════════════════════════════════════════════════════════

class ServiceResolver:
    """服务名解析器 — 将 app_name 解析为实际服务地址

    支持多种解析策略：
    - 静态配置（开发/测试环境）
    - K8s DNS
    - 自定义解析函数
    """

    def __init__(
        self,
        static_map: dict[str, str] | None = None,
        k8s_namespace: str = "",
        k8s_port: int = 8080,
        custom_resolver: Callable[[str], str] | None = None,
    ):
        """初始化服务解析器

        Args:
            static_map: 静态服务名→地址映射（优先级最高）。
            k8s_namespace: K8s 命名空间，非空时启用 K8s DNS 解析。
            k8s_port: K8s Service 默认端口。
            custom_resolver: 自定义解析函数。
        """
        self._static_map = static_map or {}
        self._k8s_namespace = k8s_namespace
        self._k8s_port = k8s_port
        self._custom_resolver = custom_resolver

    def resolve(self, app_name: str) -> str:
        """将服务名解析为 HTTP 基础地址

        Args:
            app_name: 服务名（如 "neo-ai-salescloud-service"）。

        Returns:
            服务基础地址（如 "http://neo-ai-salescloud-service:8080"）。
        """
        if app_name in self._static_map:
            return self._static_map[app_name]
        if self._custom_resolver:
            return self._custom_resolver(app_name)
        if self._k8s_namespace:
            return f"http://{app_name}.{self._k8s_namespace}.svc.cluster.local:{self._k8s_port}"
        return f"http://{app_name}:{self._k8s_port}"


# ═══════════════════════════════════════════════════════════
# FeignClientConfig
# ═══════════════════════════════════════════════════════════

@dataclass
class FeignClientConfig:
    """FeignClient 通用配置（已废弃，保留兼容。推荐直接传 transport）"""
    app_name: str = ""
    resolver: ServiceResolver | None = None
    timeout_s: float = 10.0
    headers: dict[str, str] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
# ToolFeignClient
# ═══════════════════════════════════════════════════════════

class ToolFeignClient:
    """Tool Provider 的 FeignClient 实现

    底层通过 Transport 发起调用：
    - 生产环境传入 NeoApiTransport → 自动带上下文+trace
    - 开发环境传入 HttpxTransport → 直连无依赖

    Usage:
        # 生产环境
        from neo_ai_registry.feign.transport import NeoApiTransport
        client = ToolFeignClient(app_name="neo-ai-salescloud-service", transport=NeoApiTransport())

        # 开发环境
        from neo_ai_registry.feign.transport import HttpxTransport
        resolver = ServiceResolver(static_map={"neo-ai-provider-demo": "http://localhost:8002"})
        client = ToolFeignClient(app_name="neo-ai-provider-demo", transport=HttpxTransport(resolver=resolver))

        result = client.execute_tool("query_customer", {"customer_name": "仁科"})
    """

    def __init__(
        self,
        app_name: str = "",
        transport: Any = None,
        resolver: ServiceResolver | None = None,
    ):
        """初始化 ToolFeignClient

        Args:
            app_name: 目标业务域服务名（如 "neo-ai-salescloud-service"）。
            transport: 传输层实例（Transport 子类）。
                       传 None 时自动创建 HttpxTransport（开发模式）。
            resolver: 服务名解析器（仅在 transport=None 时用于创建默认 HttpxTransport）。
        """
        self._app_name = app_name
        if transport:
            self._transport = transport
        else:
            from neo_ai_registry.feign.transport import HttpxTransport
            self._transport = HttpxTransport(resolver=resolver)

    def execute_tool(
        self,
        api_key: str,
        input_data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """远程执行 Tool

        通过 Transport 层发起调用：
        - NeoApiTransport: 自动注入 GlobalContext headers + SkyWalking trace
        - HttpxTransport: 直连，context 放在 body 中传递

        Args:
            api_key: Tool 唯一标识。
            input_data: Tool 入参字典（LLM Function Calling 生成）。
            context: 执行上下文（tenant_id/user_id/thread_id/message_id/trace_id）。

        Returns:
            Tool 执行结果字典。

        Raises:
            httpx.HTTPStatusError / Exception: 远程调用失败时抛出。
        """
        payload: dict[str, Any] = {"input": input_data}
        if context:
            payload["context"] = context

        return self._transport.invoke(
            app_name=self._app_name,
            service=f"/v1/tools/{api_key}/execute",
            method="POST",
            data=payload,
        )


# ═══════════════════════════════════════════════════════════
# MiddlewareFeignClient
# ═══════════════════════════════════════════════════════════

class MiddlewareFeignClient:
    """Middleware Provider 的 FeignClient 实现

    底层通过 Transport 发起调用，与 ToolFeignClient 一致。
    """

    def __init__(
        self,
        app_name: str = "",
        transport: Any = None,
        resolver: ServiceResolver | None = None,
    ):
        """初始化 MiddlewareFeignClient

        Args:
            app_name: 目标业务域服务名。
            transport: 传输层实例。传 None 时创建 HttpxTransport。
            resolver: 服务名解析器（transport=None 时使用）。
        """
        self._app_name = app_name
        if transport:
            self._transport = transport
        else:
            from neo_ai_registry.feign.transport import HttpxTransport
            self._transport = HttpxTransport(resolver=resolver)

    def execute_middleware(
        self,
        api_key: str,
        hook: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """远程执行 Middleware 钩子

        通过 Transport 层发起调用：
        - NeoApiTransport: 自动注入上下文+trace
        - HttpxTransport: 直连

        Args:
            api_key: Middleware 唯一标识。
            hook: 生命周期钩子名称（before_agent/after_agent/before_model/after_model/wrap_tool_call）。
            payload: 钩子入参字典。
            context: 执行上下文。

        Returns:
            Middleware 执行结果（action + patch/message）。
        """
        request_data: dict[str, Any] = {
            "hook": hook,
            "payload": payload,
        }
        if context:
            request_data["context"] = context

        return self._transport.invoke(
            app_name=self._app_name,
            service=f"/v1/middlewares/{api_key}/execute",
            method="POST",
            data=request_data,
        )
