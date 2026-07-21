"""Transport — 传输层抽象

- NeoApiTransport: 生产环境（基于 NeoApiClient，自动 Eureka + 上下文 + trace）
- HttpxTransport: 开发/测试环境（基于 httpx，直连）
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class Transport(ABC):
    """传输层抽象基类"""

    @abstractmethod
    def invoke(self, app_name: str, service: str, method: str = "POST",
               data: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]: ...


class HttpxTransport(Transport):
    """基于 httpx 的传输层（开发/测试环境）"""

    def __init__(self, resolver=None, timeout_s: float = 10.0):
        import httpx
        from neo_ai_registry.feign.resolver import ServiceResolver
        self._resolver = resolver or ServiceResolver()
        self._timeout = timeout_s
        self._httpx = httpx

    def invoke(self, app_name: str, service: str, method: str = "POST",
               data: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
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
    """基于 NeoApiClient 的传输层（生产环境）

    自动传递 GlobalContext + SkyWalking trace + Eureka 服务发现。
    """

    def __init__(self):
        from neo_ai_infr_eureka import NeoApiClient
        self._client_class = NeoApiClient

    async def async_invoke(self, app_name: str, service: str, method: str = "POST",
                           data: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        """异步调用（在 async 环境中直接 await）"""
        req_headers = {"content-type": "application/json"}
        if headers:
            req_headers.update(headers)

        result = await self._client_class().ainvoke(
            app_name=app_name, service=service, method=method,
            data=data, headers=req_headers, return_type="json",
        )
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        return result

    def invoke(self, app_name: str, service: str, method: str = "POST",
               data: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        """同步调用（内部新建线程+事件循环）"""
        import asyncio
        import threading

        async def _call():
            return await self.async_invoke(app_name, service, method, data, headers)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            result_container = {}
            exception_container = {}

            def _run():
                new_loop = asyncio.new_event_loop()
                try:
                    result_container["value"] = new_loop.run_until_complete(_call())
                except Exception as e:
                    exception_container["error"] = e
                finally:
                    new_loop.close()

            thread = threading.Thread(target=_run)
            thread.start()
            thread.join(timeout=30)
            if "error" in exception_container:
                raise exception_container["error"]
            return result_container.get("value", {})
        else:
            return asyncio.run(_call())
