"""FeignClient — 基于可插拔 Transport 的远程调用

传输层抽象：
    - NeoApiTransport: 生产环境（基于 NeoApiClient，自动传递上下文+trace）
    - HttpxTransport: 开发环境（基于 httpx，直连无依赖）

Usage:
    # 开发环境
    from neo_ai_registry.feign import ToolFeignClient, ServiceResolver
    from neo_ai_registry.feign.transport import HttpxTransport

    resolver = ServiceResolver(static_map={"neo-ai-provider-demo": "http://localhost:8002"})
    client = ToolFeignClient(app_name="neo-ai-provider-demo", transport=HttpxTransport(resolver=resolver))
    result = client.execute_tool("query_customer", {"customer_name": "xxx"})

    # 生产环境
    from neo_ai_registry.feign import ToolFeignClient
    from neo_ai_registry.feign.transport import NeoApiTransport

    client = ToolFeignClient(app_name="neo-ai-salescloud-service", transport=NeoApiTransport())
    result = client.execute_tool("query_customer", {"customer_name": "xxx"})
    # → NeoApiClient 自动注入 xsy-tenant-id / sw8 / langfuse_trace_id 等
"""

from neo_ai_registry.feign.client import (
    ToolFeignClient,
    MiddlewareFeignClient,
    FeignClientConfig,
    ServiceResolver,
)
from neo_ai_registry.feign.transport import Transport, HttpxTransport

__all__ = [
    "ToolFeignClient",
    "MiddlewareFeignClient",
    "FeignClientConfig",
    "ServiceResolver",
    "Transport",
    "HttpxTransport",
]
