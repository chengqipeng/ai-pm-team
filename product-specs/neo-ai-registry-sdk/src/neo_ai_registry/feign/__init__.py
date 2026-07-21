"""FeignClient — 远程调用层"""

from neo_ai_registry.feign.client import ToolFeignClient, MiddlewareFeignClient
from neo_ai_registry.feign.resolver import ServiceResolver
from neo_ai_registry.feign.transport import Transport, HttpxTransport, NeoApiTransport

__all__ = [
    "ToolFeignClient",
    "MiddlewareFeignClient",
    "ServiceResolver",
    "Transport",
    "HttpxTransport",
    "NeoApiTransport",
]
