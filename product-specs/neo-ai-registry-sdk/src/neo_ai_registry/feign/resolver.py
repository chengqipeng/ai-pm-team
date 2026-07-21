"""ServiceResolver — 服务名解析器

供 HttpxTransport 使用（开发/测试环境）。
生产环境通过 NeoApiTransport → NeoApiClient 内部 Eureka 解析。
"""
from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)


class ServiceResolver:
    """服务名解析器 — 将 app_name 解析为实际服务地址"""

    def __init__(
        self,
        static_map: dict[str, str] | None = None,
        k8s_namespace: str = "",
        k8s_port: int = 8080,
        custom_resolver: Callable[[str], str] | None = None,
    ):
        self._static_map = static_map or {}
        self._k8s_namespace = k8s_namespace
        self._k8s_port = k8s_port
        self._custom_resolver = custom_resolver

    def resolve(self, app_name: str) -> str:
        """将服务名解析为 HTTP 基础地址"""
        if app_name in self._static_map:
            return self._static_map[app_name]
        if self._custom_resolver:
            return self._custom_resolver(app_name)
        if self._k8s_namespace:
            return f"http://{app_name}.{self._k8s_namespace}.svc.cluster.local:{self._k8s_port}"
        return f"http://{app_name}:{self._k8s_port}"
