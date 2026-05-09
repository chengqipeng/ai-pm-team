"""
业务数据 HTTP Backend —— 对齐 paas-platform-service EntityDataApiService /entity/data/*

提供与 CrmSimulatedBackend 相同的查询接口（同名方法 + async 版本），用于页面与 Agent
对"第三层 业务数据"的访问。

环境变量：
  ENTITY_DATA_API_BASE  —— paas-platform-service 地址（与 MetarepoHttpBackend 通常共用一个）
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


def _snake_to_camel(s: str) -> str:
    if not s or "_" not in s:
        return s
    if s.startswith("dbc_"):
        return s
    parts = s.split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:] if p)


def _walk(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {_snake_to_camel(k): _walk(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(x) for x in obj]
    return obj


class EntityDataHttpBackend:
    """paas-platform-service /entity/data/* 的只读查询代理。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: float = 10.0,
        *,
        auth_client: Any = None,
    ):
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

    async def _get(self, path: str, **params) -> Any:
        if self._client is not None:
            return _walk(await self._client.request("GET", path, params=params))
        clean = {k: v for k, v in params.items() if v is not None}
        async with httpx.AsyncClient(
            base_url=self._legacy["base"],
            headers=self._legacy["headers"],
            timeout=self._legacy["timeout"],
        ) as cli:
            r = await cli.get(path, params=clean)
            r.raise_for_status()
            payload = r.json()
            if isinstance(payload, dict) and "code" in payload and "data" in payload:
                payload = payload["data"]
            return _walk(payload)

    # ─── CrmSimulatedBackend 接口对齐 ───────────────────────

    async def query_data(
        self,
        entity: str,
        filters: dict | None = None,
        *,
        page: int = 1,
        page_size: int = 20,
        order_by: Optional[str] = None,
        fields: Optional[list[str]] = None,
    ) -> dict:
        """
        查询业务数据列表（对齐 GET /entity/data/{entityApiKey}）。
        过滤条件里支持：
          - 按固定列 name / owner_id 等：框架侧 listPage 的 conditions 已支持
          - 按 dbc_xxx 列：加 filter_dbc_xxx 前缀
        """
        filters = filters or {}
        params: dict[str, Any] = {"page": page, "size": page_size}
        if order_by:
            params["sort"] = order_by.lstrip("-") + (",desc" if order_by.startswith("-") else ",asc")
        # 单条 id 查询：走 get 接口更高效
        if len(filters) == 1 and "id" in filters:
            try:
                single = await self.get_by_id(entity, filters["id"])
                return {"data": {"records": [single] if single else [], "total": 1 if single else 0}}
            except Exception:
                return {"data": {"records": [], "total": 0}}
        # 其他过滤条件透传给服务端
        for k, v in filters.items():
            if v is None or v == "":
                continue
            if k.startswith("dbc_"):
                params[f"filter_{k}"] = v
            else:
                params[k] = v

        try:
            resp = await self._get(f"/entity/data/{entity}", **params)
        except httpx.HTTPError as exc:
            logger.warning("query_data failed: entity=%s err=%s", entity, exc)
            return {"data": {"records": [], "total": 0}, "error": str(exc)}
        records = resp.get("records", []) or []
        if fields:
            records = [{k: r.get(k) for k in ["id", *fields] if k in r} for r in records]
        return {"data": {"records": records, "total": resp.get("total", 0)}}

    async def get_by_id(self, entity: str, record_id: Any) -> Optional[dict]:
        try:
            return await self._get(f"/entity/data/{entity}/{record_id}")
        except httpx.HTTPError as exc:
            logger.warning("get_by_id failed: entity=%s id=%s err=%s", entity, record_id, exc)
            return None

    async def aggregate_data(
        self,
        entity: str,
        metrics: list[dict],
        *,
        group_by: Optional[str] = None,
        filters: Optional[dict] = None,
    ) -> dict:
        """
        paas-platform-service 没有独立的聚合接口；为与 sim backend 对齐，用客户端计算兜底：
        - 拉取（已过滤后的）数据
        - 在 Python 侧按 metrics / group_by 求值
        真正生产环境可接入 /data/v2.0/query （XOQL）或专用报表接口替换本实现。
        """
        filters = filters or {}
        data = await self.query_data(entity, filters, page=1, page_size=1000)
        records = (data.get("data") or {}).get("records", [])
        results: list[dict] = []
        if group_by:
            groups: dict[str, list[dict]] = {}
            for r in records:
                k = str(r.get(group_by, "未知"))
                groups.setdefault(k, []).append(r)
            for key, grows in groups.items():
                row = {group_by: key}
                for m in metrics:
                    row[f"{m['function']}_{m['field']}"] = _calc(grows, m["field"], m["function"])
                results.append(row)
        else:
            row = {}
            for m in metrics:
                row[f"{m['function']}_{m['field']}"] = _calc(records, m["field"], m["function"])
            results.append(row)
        return {"data": {"results": results, "total_records": len(records)}}

    async def get_stats(self, entities: list[str]) -> dict[str, int]:
        """用于左侧列表"记录数"徽章。每个实体发一次 count。"""
        stats: dict[str, int] = {}
        for e in entities:
            try:
                resp = await self._get(f"/entity/data/{e}", page=1, size=1)
                stats[e] = int(resp.get("total", 0))
            except httpx.HTTPError:
                stats[e] = 0
        return stats


# ─── 聚合工具 ────────────────────────────────────────────────

def _calc(records: list[dict], field: str, func: str) -> Any:
    if func == "count":
        return len(records)
    values = [r.get(field) for r in records if r.get(field) is not None]
    nums: list[float] = []
    for v in values:
        try:
            nums.append(float(v))
        except (TypeError, ValueError):
            pass
    if not nums:
        return 0
    if func == "sum":
        return round(sum(nums), 2)
    if func == "avg":
        return round(sum(nums) / len(nums), 2)
    if func == "min":
        return min(nums)
    if func == "max":
        return max(nums)
    return len(records)
