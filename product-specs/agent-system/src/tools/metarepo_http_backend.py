"""
Metarepo HTTP Backend —— 通过 Feign-style 客户端远程调用 paas-platform-service

对齐 MetamodelBrowseApiService 的 /meta/* 接口，方法签名与 MetarepoSimulatedBackend
完全一致（除方法变为 async）。上层 API 层和 Agent 工具层通过 _maybe_await 包装即可同时
支持两种后端。

环境变量：
  METAREPO_API_BASE   —— paas-platform-service 服务地址，如 http://paas-platform-service:8080
  METAREPO_TENANT_ID  —— 注入 X-Tenant-Id header（框架 AuthTokenInterceptor 的 dev 旁路）
  METAREPO_USER_ID    —— 注入 X-User-Id header
  METAREPO_TOKEN      —— 注入 Authorization: Bearer <token>
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


def _snake_to_camel(s: str) -> str:
    if not s or "_" not in s:
        return s
    # dbc_varchar1 / dbc_bigint8 等物理列保持原样，不走 camelCase 转换
    if s.startswith("dbc_"):
        return s
    parts = s.split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:] if p)


def _walk(obj: Any) -> Any:
    """递归把 snake_case dict key 转为 camelCase，与 sim backend 返回的 shape 对齐。"""
    if isinstance(obj, dict):
        return {_snake_to_camel(k): _walk(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(x) for x in obj]
    return obj


class MetarepoHttpBackend:
    """paas-platform-service 的元模型 / 元数据查询代理。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: float = 10.0,
        *,
        auth_client: Any = None,
    ):
        """
        两种构造方式：
          - 推荐：传 auth_client（共享登录 + 自动 401 重登）
          - 向后兼容：传 base_url + headers（不含登录逻辑，需外部提供 Authorization header）
        """
        if auth_client is not None:
            self._client = auth_client
            self._legacy = None
        else:
            if not base_url:
                raise ValueError("必须提供 auth_client 或 base_url")
            self._legacy = {
                "base": base_url.rstrip("/"),
                "headers": dict(headers or {}),
                "timeout": timeout,
            }
            self._client = None

    # ─── HTTP 基础设施 ────────────────────────────────────────

    async def _get(self, path: str, **params) -> Any:
        if self._client is not None:
            return _walk(await self._client.request("GET", path, params=params))
        # legacy 直连模式（不带登录）
        clean = {k: v for k, v in params.items() if v is not None}
        async with httpx.AsyncClient(
            base_url=self._legacy["base"],
            headers=self._legacy["headers"],
            timeout=self._legacy["timeout"],
        ) as cli:
            try:
                r = await cli.get(path, params=clean)
                r.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("HTTP call failed: %s %s — %s", path, clean, exc)
                raise
            payload = r.json()
            if isinstance(payload, dict) and "code" in payload and "data" in payload:
                payload = payload["data"]
            return _walk(payload)

    # ─── 元模型层 —— 对齐 /meta/* ─────────────────────────────

    async def list_metamodels(self) -> list[dict]:
        data = await self._get("/meta/metamodels")
        return sorted(data or [], key=lambda x: x.get("sortNum") or 0)

    async def get_metamodel(self, metamodel_api_key: str) -> Optional[dict]:
        # paas-platform-service 没有按 apiKey 查单个的接口，客户端自己过滤
        for m in await self.list_metamodels():
            if m.get("apiKey") == metamodel_api_key:
                return m
        return None

    async def list_meta_items(self, metamodel_api_key: str) -> list[dict]:
        data = await self._get("/meta/meta-items", metamodelApiKey=metamodel_api_key)
        return sorted(data or [], key=lambda x: x.get("sortNum") or 0)

    async def get_column_mapping(self, metamodel_api_key: str) -> dict[str, str]:
        # 服务端返回 {"dbc_xxx": "apiKey"} — 列名保持原样，apiKey 已是 camelCase
        data = await self._get("/meta/column-mapping", metamodelApiKey=metamodel_api_key)
        return data or {}

    async def list_meta_links(self, metamodel_api_key: Optional[str] = None) -> list[dict]:
        data = await self._get("/meta/meta-links") or []
        if metamodel_api_key:
            data = [
                l for l in data
                if l.get("parentMetamodelApiKey") == metamodel_api_key
                or l.get("childMetamodelApiKey") == metamodel_api_key
            ]
        return data

    async def list_meta_options(
        self, metamodel_api_key: str, item_api_key: Optional[str] = None
    ) -> list[dict]:
        data = await self._get("/meta/meta-options", metamodelApiKey=metamodel_api_key) or []
        if item_api_key:
            data = [o for o in data if o.get("itemApiKey") == item_api_key]
        return sorted(data, key=lambda x: x.get("optionOrder") or 0)

    async def get_item_type_mapping(self) -> list[dict]:
        return await self._get("/meta/item-type-mapping") or []

    # ─── 元数据实例层 —— 对齐 /meta/metadata/* ────────────────

    async def list_metadata(
        self,
        metamodel_api_key: str,
        entity_api_key: Optional[str] = None,
        item_api_key: Optional[str] = None,
    ) -> list[dict]:
        # 优先使用具体路由（服务端可能做了专用优化），fallback 到 /meta/metadata 通用查询
        if metamodel_api_key == "entity":
            return await self._get("/meta/metadata/entities") or []
        if metamodel_api_key == "item" and entity_api_key:
            return await self._get("/meta/metadata/items", entityApiKey=entity_api_key) or []
        if metamodel_api_key == "entityLink" and entity_api_key:
            return await self._get("/meta/metadata/entity-links", entityApiKey=entity_api_key) or []
        if metamodel_api_key == "checkRule" and entity_api_key:
            return await self._get("/meta/metadata/check-rules", entityApiKey=entity_api_key) or []
        if metamodel_api_key == "busiType" and entity_api_key:
            return await self._get("/meta/metadata/busi-types", entityApiKey=entity_api_key) or []
        if metamodel_api_key == "pickOption" and item_api_key:
            return await self._get("/meta/metadata/pick-options", itemApiKey=item_api_key) or []
        # 通用查询：其他元模型（role / department 等独立元模型）
        return await self._get(
            "/meta/metadata",
            metamodelApiKey=metamodel_api_key,
            entityApiKey=entity_api_key,
        ) or []

    async def get_metadata(
        self,
        metamodel_api_key: str,
        api_key: str,
        entity_api_key: Optional[str] = None,
    ) -> Optional[dict]:
        records = await self.list_metadata(metamodel_api_key, entity_api_key=entity_api_key)
        for r in records:
            if r.get("apiKey") == api_key:
                return r
        return None

    # ─── 便捷封装（与 sim backend 同名，避免 API 层分支）──

    async def list_metadata_entities(self) -> list[dict]:
        return await self.list_metadata("entity")

    async def list_metadata_items(self, entity_api_key: str) -> list[dict]:
        return await self.list_metadata("item", entity_api_key=entity_api_key)

    async def list_metadata_entity_links(self, entity_api_key: str) -> list[dict]:
        return await self.list_metadata("entityLink", entity_api_key=entity_api_key)

    async def list_metadata_check_rules(self, entity_api_key: str) -> list[dict]:
        return await self.list_metadata("checkRule", entity_api_key=entity_api_key)

    async def list_metadata_busi_types(self, entity_api_key: str) -> list[dict]:
        return await self.list_metadata("busiType", entity_api_key=entity_api_key)

    async def list_metadata_pick_options(self, item_api_key: str) -> list[dict]:
        return await self.list_metadata("pickOption", item_api_key=item_api_key)

    # ─── 诊断 ────────────────────────────────────────────────

    async def trace_db_column(self, db_column: str) -> list[dict]:
        """反查 dbc 列被哪些元模型字段占用（需要遍历所有元模型）。"""
        hits: list[dict] = []
        for m in await self.list_metamodels():
            api_key = m.get("apiKey")
            if not api_key:
                continue
            try:
                items = await self.list_meta_items(api_key)
            except Exception:
                continue
            for item in items:
                if item.get("dbColumn") == db_column:
                    hits.append({
                        "metamodelApiKey": api_key,
                        "itemApiKey": item.get("apiKey"),
                        "label": item.get("label"),
                        "itemType": item.get("itemType"),
                    })
        return hits

    async def get_stats(self) -> dict[str, int]:
        models = await self.list_metamodels()
        links = await self.list_meta_links()
        items_total = 0
        options_total = 0
        instances_total = 0
        for m in models:
            api_key = m.get("apiKey")
            if not api_key:
                continue
            try:
                items_total += len(await self.list_meta_items(api_key))
            except Exception:
                logger.exception("get_stats 异常")
            try:
                options_total += len(await self.list_meta_options(api_key))
            except Exception:
                logger.exception("get_stats 异常")
            try:
                instances_total += len(await self.list_metadata(api_key))
            except Exception:
                logger.exception("get_stats 异常")
        return {
            "meta_models": len(models),
            "meta_items_total": items_total,
            "meta_links": len(links),
            "meta_options": options_total,
            "metadata_instances_total": instances_total,
        }
