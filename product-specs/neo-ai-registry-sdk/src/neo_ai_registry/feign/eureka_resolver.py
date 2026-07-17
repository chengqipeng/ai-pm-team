"""Eureka ServiceResolver — 从 Eureka Server 发现服务地址

通过 Eureka REST API 查询注册表获取服务实例地址。

Usage:
    from neo_ai_registry.feign.eureka_resolver import EurekaServiceResolver

    resolver = EurekaServiceResolver(eureka_server="https://admin:xxx@discovery-dev.ingageapp.com/eureka/")
    url = resolver.resolve("neo-ai-provider-demo")
    # → "http://192.168.1.100:8002"
"""
from __future__ import annotations

import logging

import httpx

from neo_ai_registry.feign.client import ServiceResolver

logger = logging.getLogger(__name__)


class EurekaServiceResolver(ServiceResolver):
    """基于 Eureka REST API 的服务名解析器

    直接调用 Eureka REST API (/eureka/apps/{appName}) 获取实例地址。
    不依赖 py_eureka_client 的内存注册表缓存，实时查询。

    Args:
        eureka_server: Eureka Server URL（含认证信息）。
                       如 "https://admin:AdminEureka1234@discovery-dev.ingageapp.com/eureka/"
        static_map: 静态覆盖映射（优先级高于 Eureka）。
    """

    def __init__(
        self,
        eureka_server: str = "",
        static_map: dict[str, str] | None = None,
    ):
        super().__init__(static_map=static_map)
        self._eureka_server = eureka_server.rstrip("/")

    def resolve(self, app_name: str) -> str:
        """从 Eureka REST API 解析服务地址

        优先级：static_map > Eureka REST 查询

        Args:
            app_name: 服务名（Eureka appName，大小写不敏感）。

        Returns:
            服务 HTTP 基础地址，如 "http://192.168.1.100:8002"。

        Raises:
            ValueError: Eureka 中未找到该服务实例时抛出。
        """
        # 优先走 static_map
        if self._static_map and app_name in self._static_map:
            return self._static_map[app_name]

        # 通过 Eureka REST API 查询
        # GET /eureka/apps/{appName} → JSON
        url = f"{self._eureka_server}/apps/{app_name.upper()}"
        try:
            resp = httpx.get(
                url,
                headers={"Accept": "application/json"},
                timeout=5.0,
                verify=False,
            )
            if resp.status_code == 404:
                raise ValueError(f"服务 '{app_name}' 在 Eureka 中未找到 (404)")

            resp.raise_for_status()
            data = resp.json()

            # 解析实例
            app_data = data.get("application", {})
            instances = app_data.get("instance", [])
            if isinstance(instances, dict):
                instances = [instances]

            # 找到 UP 状态的实例
            for inst in instances:
                if inst.get("status") == "UP":
                    host = inst.get("ipAddr") or inst.get("hostName", "")
                    port = inst.get("port", {})
                    port_num = port.get("$", 8080) if isinstance(port, dict) else port
                    result = f"http://{host}:{port_num}"
                    logger.info("Eureka 解析: %s → %s", app_name, result)
                    return result

            raise ValueError(f"服务 '{app_name}' 在 Eureka 中无 UP 状态实例")

        except httpx.HTTPError as e:
            raise ValueError(
                f"Eureka 查询失败: {app_name} → {e}。"
                f"Server: {self._eureka_server}"
            ) from e
