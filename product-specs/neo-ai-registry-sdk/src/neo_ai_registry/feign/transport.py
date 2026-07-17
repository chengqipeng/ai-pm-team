"""Transport 传输层抽象 — 可插拔的 HTTP 调用底层

生产环境注入 NeoApiTransport（基于 NeoApiClient，自动传递上下文+trace）。
开发/测试环境使用 HttpxTransport（基于 httpx，直连无依赖）。

Usage:
    # 生产环境
    from neo_ai_registry.feign.transport import NeoApiTransport
    transport = NeoApiTransport()
    result = await transport.invoke("neo-ai-salescloud-service", "/v1/tools/query_customer/execute", "POST", data)

    # 开发环境
    from neo_ai_registry.feign.transport import HttpxTransport, ServiceResolver
    transport = HttpxTransport(resolver=ServiceResolver(static_map={...}))
    result = transport.invoke("neo-ai-provider-demo", "/v1/tools/query_customer/execute", "POST", data)
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from neo_ai_registry.feign.client import ServiceResolver

logger = logging.getLogger(__name__)


class Transport(ABC):
    """传输层抽象基类

    定义 SDK FeignClient 底层 HTTP 调用的统一接口。
    不同环境注入不同实现：
    - NeoApiTransport: 生产环境，基于 NeoApiClient（自动带上下文+trace）
    - HttpxTransport: 开发/测试环境，基于 httpx（直连，无外部依赖）
    """

    @abstractmethod
    def invoke(
        self,
        app_name: str,
        service: str,
        method: str = "POST",
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """发起 HTTP 调用

        Args:
            app_name: 目标服务名（如 "neo-ai-salescloud-service"）。
                      生产环境通过 Eureka 解析，开发环境通过 ServiceResolver 解析。
            service: 请求路径（如 "/v1/tools/query_customer/execute"）。
            method: HTTP 方法（"GET" / "POST"）。
            data: 请求体 JSON 字典（POST 时使用）。
            headers: 额外请求头（可选，会与传输层自动注入的 headers 合并）。

        Returns:
            响应 JSON 中的 data 字段（{"code":0,"data":...} 格式时）。
            否则返回完整响应 JSON。

        Raises:
            Exception: 调用失败时抛出（具体类型由实现决定）。
        """
        ...


class HttpxTransport(Transport):
    """基于 httpx 的传输层实现（开发/测试环境）

    直连目标服务，无上下文自动注入，无 trace 传递。
    适用于本地开发和 Demo 验证。

    Args:
        resolver: 服务名解析器，将 app_name 解析为实际 HTTP 地址。
        timeout_s: 请求超时时间（秒）。
    """

    def __init__(self, resolver: ServiceResolver | None = None, timeout_s: float = 10.0):
        """初始化 HttpxTransport

        Args:
            resolver: 服务名解析器。为 None 时使用默认解析（K8s 同 namespace）。
            timeout_s: HTTP 请求超时时间（秒），默认 10 秒。
        """
        import httpx
        self._resolver = resolver or ServiceResolver()
        self._timeout = timeout_s
        self._httpx = httpx

    def invoke(
        self,
        app_name: str,
        service: str,
        method: str = "POST",
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """通过 httpx 直连调用

        Args:
            app_name: 目标服务名，通过 resolver 解析为 base_url。
            service: 请求路径。
            method: HTTP 方法。
            data: 请求体。
            headers: 额外请求头。
        """
        base_url = self._resolver.resolve(app_name)
        url = f"{base_url}{service}"
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)

        if method.upper() == "GET":
            resp = self._httpx.get(url, headers=req_headers, timeout=self._timeout)
        else:
            resp = self._httpx.post(url, json=data, headers=req_headers, timeout=self._timeout)

        resp.raise_for_status()
        body = resp.json()
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body


class NeoApiTransport(Transport):
    """基于 NeoApiClient 的传输层实现（生产环境）

    自动传递：
    - GlobalContext 上下文 headers（tenant_id / user_id / language / device / agent_source）
    - SkyWalking trace headers（sw8 / sw8-x）
    - Langfuse trace_id
    - Eureka 服务发现

    依赖 neo-ai-infr-eureka 包（生产环境已安装）。

    Usage:
        from neo_ai_registry.feign.transport import NeoApiTransport
        transport = NeoApiTransport()
        # 自动从 GlobalContext 读取上下文，自动注入 SkyWalking trace
        result = transport.invoke("neo-ai-salescloud-service", "/v1/tools/xxx/execute", "POST", data)
    """

    def __init__(self):
        """初始化 NeoApiTransport

        Raises:
            ImportError: neo_ai_infr_eureka 未安装时抛出。
        """
        try:
            from neo_ai_infr_eureka import NeoApiClient
            self._client_class = NeoApiClient
        except ImportError:
            raise ImportError(
                "NeoApiTransport 需要 neo-ai-infr-eureka 包。"
                "请安装: pip install neo-ai-infr-eureka，"
                "或在开发环境使用 HttpxTransport 替代。"
            )

    def invoke(
        self,
        app_name: str,
        service: str,
        method: str = "POST",
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """通过 NeoApiClient 调用（自动传递上下文+trace）

        内部调用 NeoApiClient().ainvoke()，它会自动：
        1. 从 GlobalContext 读取 tenant_id/user_id/language 等注入 headers
        2. 从 SkyWalking context 注入 trace headers (sw8)
        3. 通过 Eureka 解析 app_name 为实际地址

        Args:
            app_name: 目标服务名（Eureka 注册名）。
            service: 请求路径。
            method: HTTP 方法。
            data: 请求体。
            headers: 额外请求头（会与自动注入的 headers 合并）。
        """
        import asyncio

        req_headers = {"content-type": "application/json"}
        if headers:
            req_headers.update(headers)

        async def _call():
            result = await self._client_class().ainvoke(
                app_name=app_name,
                service=service,
                method=method,
                data=data,
                headers=req_headers,
                return_type="json",
            )
            return result

        # 处理事件循环（兼容同步/异步调用场景）
        try:
            loop = asyncio.get_running_loop()
            # 如果在异步上下文中，需要用不同方式
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(asyncio.run, _call()).result()
        except RuntimeError:
            # 没有运行中的事件循环，直接 asyncio.run
            result = asyncio.run(_call())

        # 统一响应格式处理
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        return result
