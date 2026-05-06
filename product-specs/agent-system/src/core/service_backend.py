"""
ServiceBackend — 服务调用抽象层，对应产品设计 §3.9
所有业务操作通过此接口路由到对应微服务
"""
from __future__ import annotations

from typing import Any, Protocol


class ServiceBackend(Protocol):
    """服务调用抽象 — 不同部署环境可替换实现"""

    async def query_metadata(self, query_type: str, **params) -> dict: ...
    async def query_data(self, entity: str, filters: dict, **kw) -> dict: ...
    async def mutate_data(self, entity: str, action: str, data: dict, **kw) -> dict: ...
    async def aggregate_data(self, entity: str, metrics: list, **kw) -> dict: ...
    async def query_permission(self, query_type: str, **kw) -> dict: ...


class MockServiceBackend:
    """Mock 后端 — 用于测试和开发"""

    def __init__(self):
        self._responses: dict[str, Any] = {}

    def set_response(self, method: str, response: Any) -> None:
        self._responses[method] = response

    async def query_metadata(self, query_type: str, **params) -> dict:
        return self._responses.get("query_metadata", {"data": {}})

    async def query_data(self, entity: str, filters: dict, **kw) -> dict:
        return self._responses.get("query_data", {"data": {"records": [], "total": 0}})

    async def mutate_data(self, entity: str, action: str, data: dict, **kw) -> dict:
        return self._responses.get("mutate_data", {"data": {"id": "mock_id", "success": True}})

    async def aggregate_data(self, entity: str, metrics: list, **kw) -> dict:
        return self._responses.get("aggregate_data", {"data": {"results": []}})

    async def query_permission(self, query_type: str, **kw) -> dict:
        return self._responses.get("query_permission", {"data": {}})
