"""
元模型 / 元数据 / 业务数据 浏览 REST API
—— 对齐 paas-platform-service MetamodelBrowseApiService + EntityDataApiService

挂载路径：/api/meta/*

Backend 切换（通过环境变量）：
  METAREPO_API_BASE         —— 配置后自动切到 HTTP 模式（调用 paas-platform-service）
  METAREPO_TENANT_ID / METAREPO_USER_ID / METAREPO_TOKEN —— HTTP 模式下注入 header
  未配置时回退到 MetarepoSimulatedBackend + CrmSimulatedBackend（零依赖本地运行）

Sim backend 同步方法和 HTTP backend 异步方法通过 _await 桥接，保证 API 层代码统一。
"""
from __future__ import annotations

import inspect
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meta", tags=["metarepo"])


# ─── Backend 工厂 —— 优先直连本地数据库，回退到模拟数据 ───────

_meta_backend: Any = None
_data_backend: Any = None
_backend_mode: str = ""   # "db" | "sim"


def _build_headers() -> dict[str, str]:
    """（保留以备需要时使用）"""
    from src.core.context import DEFAULT_TENANT_ID
    headers = {"Content-Type": "application/json"}
    tenant = os.getenv("METAREPO_TENANT_ID") or str(DEFAULT_TENANT_ID)
    headers["X-Tenant-Id"] = tenant
    token = os.getenv("METAREPO_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_meta_backend():
    """懒加载元模型 / 元数据 backend —— 优先直连数据库。"""
    global _meta_backend, _backend_mode
    if _meta_backend is not None:
        return _meta_backend

    # 优先尝试直连本地 PostgreSQL
    try:
        from src.tools.metarepo_db_backend import MetarepoDbBackend
        backend = MetarepoDbBackend()
        # 验证数据库连通性
        backend.list_metamodels()
        _meta_backend = backend
        _backend_mode = "db"
        logger.info("Metarepo backend: DB 直连 (paas_metarepo_common)")
    except Exception as exc:
        logger.warning("DB 直连失败，降级到模拟后端: %s", exc)
        from src.tools.metarepo_backend import MetarepoSimulatedBackend
        _meta_backend = MetarepoSimulatedBackend()
        _backend_mode = "sim"
        logger.info("Metarepo backend: Simulated (模拟数据)")
    return _meta_backend


def _get_data_backend():
    """懒加载业务数据 backend —— 使用 CRM 模拟后端。"""
    global _data_backend
    if _data_backend is not None:
        return _data_backend
    from src.tools.crm_backend import CrmSimulatedBackend
    _data_backend = CrmSimulatedBackend()
    logger.info("Entity data backend: Simulated (CrmSimulatedBackend)")
    return _data_backend


async def _await(value: Any) -> Any:
    """sim 返回同步值、http 返回 awaitable —— 统一桥接。"""
    if inspect.isawaitable(value):
        return await value
    return value


def _fallback_list_metamodels() -> list[dict]:
    """HTTP 后端不可用时降级到模拟后端。"""
    try:
        from src.tools.metarepo_backend import MetarepoSimulatedBackend
        return MetarepoSimulatedBackend().list_metamodels()
    except Exception as exc:
        logger.error("降级到模拟后端也失败: %s", exc)
        return []


def _is_http_data(backend: Any) -> bool:
    return backend.__class__.__name__ == "EntityDataHttpBackend"


# ═══════════════════════════════════════════════════════════
# 元模型层 —— 对齐 MetamodelBrowseApiService /meta/*
# ═══════════════════════════════════════════════════════════

@router.get("/metamodels")
async def list_metamodels() -> list[dict]:
    try:
        return await _await(_get_meta_backend().list_metamodels())
    except Exception as exc:
        logger.warning("list_metamodels 失败，尝试降级到模拟后端: %s", exc)
        return _fallback_list_metamodels()


@router.get("/metamodels/{metamodel_api_key}")
async def get_metamodel(metamodel_api_key: str) -> dict:
    data = await _await(_get_meta_backend().get_metamodel(metamodel_api_key))
    if data is None:
        raise HTTPException(404, f"元模型 {metamodel_api_key} 未注册")
    return data


@router.get("/meta-items")
async def list_meta_items(metamodel_api_key: str = Query(..., alias="metamodelApiKey")) -> list[dict]:
    return await _await(_get_meta_backend().list_meta_items(metamodel_api_key))


@router.get("/column-mapping")
async def column_mapping(metamodel_api_key: str = Query(..., alias="metamodelApiKey")) -> dict[str, str]:
    return await _await(_get_meta_backend().get_column_mapping(metamodel_api_key))


@router.get("/meta-links")
async def list_meta_links(
    metamodel_api_key: Optional[str] = Query(None, alias="metamodelApiKey"),
) -> list[dict]:
    return await _await(_get_meta_backend().list_meta_links(metamodel_api_key))


@router.get("/meta-options")
async def list_meta_options(
    metamodel_api_key: str = Query(..., alias="metamodelApiKey"),
    item_api_key: Optional[str] = Query(None, alias="itemApiKey"),
) -> list[dict]:
    return await _await(
        _get_meta_backend().list_meta_options(metamodel_api_key, item_api_key=item_api_key)
    )


@router.get("/item-type-mapping")
async def item_type_mapping() -> list[dict]:
    return await _await(_get_meta_backend().get_item_type_mapping())


@router.get("/trace-db-column")
async def trace_db_column(db_column: str = Query(..., alias="dbColumn")) -> list[dict]:
    return await _await(_get_meta_backend().trace_db_column(db_column))


# ═══════════════════════════════════════════════════════════
# 元数据实例层 —— 对齐 /meta/metadata/*
# ═══════════════════════════════════════════════════════════

@router.get("/metadata")
async def list_metadata_auto(
    metamodel_api_key: str = Query(..., alias="metamodelApiKey"),
    entity_api_key: Optional[str] = Query(None, alias="entityApiKey"),
    item_api_key: Optional[str] = Query(None, alias="itemApiKey"),
) -> list[dict]:
    backend = _get_meta_backend()
    if await _await(backend.get_metamodel(metamodel_api_key)) is None:
        raise HTTPException(404, f"元模型 {metamodel_api_key} 未注册")
    return await _await(
        backend.list_metadata(
            metamodel_api_key, entity_api_key=entity_api_key, item_api_key=item_api_key
        )
    )


@router.get("/metadata/entities")
async def list_metadata_entities() -> list[dict]:
    return await _await(_get_meta_backend().list_metadata_entities())


@router.get("/metadata/items")
async def list_metadata_items(entity_api_key: str = Query(..., alias="entityApiKey")) -> list[dict]:
    return await _await(_get_meta_backend().list_metadata_items(entity_api_key))


@router.get("/metadata/entity-links")
async def list_metadata_entity_links(entity_api_key: str = Query(..., alias="entityApiKey")) -> list[dict]:
    return await _await(_get_meta_backend().list_metadata_entity_links(entity_api_key))


@router.get("/metadata/check-rules")
async def list_metadata_check_rules(entity_api_key: str = Query(..., alias="entityApiKey")) -> list[dict]:
    return await _await(_get_meta_backend().list_metadata_check_rules(entity_api_key))


@router.get("/metadata/busi-types")
async def list_metadata_busi_types(entity_api_key: str = Query(..., alias="entityApiKey")) -> list[dict]:
    return await _await(_get_meta_backend().list_metadata_busi_types(entity_api_key))


@router.get("/metadata/pick-options")
async def list_metadata_pick_options(item_api_key: str = Query(..., alias="itemApiKey")) -> list[dict]:
    return await _await(_get_meta_backend().list_metadata_pick_options(item_api_key))


# ═══════════════════════════════════════════════════════════
# 便捷聚合接口 —— 前端一屏展示
# ═══════════════════════════════════════════════════════════

@router.get("/stats")
async def stats() -> dict[str, Any]:
    from src.core.context import DEFAULT_TENANT_ID
    data = await _await(_get_meta_backend().get_stats())
    tenant = os.getenv("METAREPO_TENANT_ID") or str(DEFAULT_TENANT_ID)
    if isinstance(data, dict):
        data = {**data, "backend": _backend_mode or "sim", "tenantId": tenant}
    return data


@router.get("/overview/{metamodel_api_key}")
async def metamodel_overview(metamodel_api_key: str) -> dict:
    backend = _get_meta_backend()
    model = await _await(backend.get_metamodel(metamodel_api_key))
    if model is None:
        raise HTTPException(404, f"元模型 {metamodel_api_key} 未注册")
    items = await _await(backend.list_meta_items(metamodel_api_key))
    col_map = await _await(backend.get_column_mapping(metamodel_api_key))
    options = await _await(backend.list_meta_options(metamodel_api_key))
    links = await _await(backend.list_meta_links(metamodel_api_key))
    meta_records = await _await(backend.list_metadata(metamodel_api_key))
    return {
        "model": model,
        "items": items or [],
        "columnMapping": col_map or {},
        "options": options or [],
        "links": links or [],
        "metadataCount": len(meta_records or []),
    }


@router.get("/entity/{entity_api_key}/overview")
async def entity_overview(entity_api_key: str) -> dict:
    backend = _get_meta_backend()
    entity = await _await(backend.get_metadata("entity", entity_api_key))
    if entity is None:
        raise HTTPException(404, f"业务对象 {entity_api_key} 不存在")
    items = await _await(backend.list_metadata_items(entity_api_key)) or []
    pick_options_by_item: dict[str, list[dict]] = {}
    for item in items:
        if item.get("itemType") == "PICK_LIST":
            api_key = item.get("apiKey")
            if api_key:
                pick_options_by_item[api_key] = await _await(
                    backend.list_metadata_pick_options(api_key)
                )
    links = await _await(backend.list_metadata_entity_links(entity_api_key))
    rules = await _await(backend.list_metadata_check_rules(entity_api_key))
    busi = await _await(backend.list_metadata_busi_types(entity_api_key))
    return {
        "entity": entity,
        "items": items,
        "pickOptionsByItem": pick_options_by_item,
        "entityLinks": links or [],
        "checkRules": rules or [],
        "busiTypes": busi or [],
    }


# ═══════════════════════════════════════════════════════════
# 业务数据层 —— 对齐 /entity/data/*
# ═══════════════════════════════════════════════════════════

async def _list_data_entity_keys() -> list[str]:
    """返回可查询数据的业务对象 apiKey 列表。"""
    if _backend_mode == "http":
        entities = await _await(_get_meta_backend().list_metadata_entities())
        return [e["apiKey"] for e in (entities or []) if e.get("apiKey")]
    from src.tools.crm_backend import ENTITY_SCHEMAS
    return list(ENTITY_SCHEMAS.keys())


async def _has_data_entity(entity_api_key: str) -> bool:
    keys = await _list_data_entity_keys()
    return entity_api_key in keys


def _sim_entity_label(api_key: str) -> str | None:
    try:
        from src.tools.crm_backend import ENTITY_SCHEMAS
        return (ENTITY_SCHEMAS.get(api_key) or {}).get("label")
    except Exception:
        return None


@router.get("/data/entities")
async def list_data_entities() -> list[dict]:
    """列出所有'有业务数据'的业务对象（含记录总数）。"""
    meta_backend = _get_meta_backend()
    data_backend = _get_data_backend()

    keys = await _list_data_entity_keys()

    # 记录数：sim 直接拿 get_stats()，http 批量 count
    totals: dict[str, int] = {}
    if _is_http_data(data_backend):
        totals = await _await(data_backend.get_stats(keys)) or {}
    else:
        sync_stats = data_backend.get_stats()
        if isinstance(sync_stats, dict):
            totals = sync_stats

    # 基本信息：取 entity 元数据实例的 label / namespace
    entity_records = await _await(meta_backend.list_metadata_entities())
    entity_map = {e.get("apiKey"): e for e in (entity_records or []) if e.get("apiKey")}

    result: list[dict] = []
    for k in keys:
        meta = entity_map.get(k, {})
        label = meta.get("label") or _sim_entity_label(k) or k
        result.append({
            "apiKey": k,
            "label": label,
            "namespace": meta.get("namespace", "product"),
            "iconName": meta.get("iconName", ""),
            "total": int(totals.get(k, 0) or 0),
        })
    return result


@router.get("/data/{entity_api_key}/_overview")
async def data_entity_overview(entity_api_key: str) -> dict:
    """业务对象的数据概览 —— 字段结构 + 前 10 条样本数据 + 聚合指标。"""
    if not await _has_data_entity(entity_api_key):
        raise HTTPException(404, f"业务对象 {entity_api_key} 未注册数据后端")

    meta_backend = _get_meta_backend()
    data_backend = _get_data_backend()

    meta_entity = await _await(meta_backend.get_metadata("entity", entity_api_key)) or {}
    items = await _await(meta_backend.list_metadata_items(entity_api_key)) or []

    sample = await _await(data_backend.query_data(entity_api_key, filters={}, page=1, page_size=10))
    sample_data = sample.get("data", {}) if isinstance(sample, dict) else {}

    numeric_metrics: list[dict] = []
    for it in items:
        if it.get("itemType") in {"DECIMAL", "INTEGER", "LONG"}:
            api_key = it.get("apiKey")
            if not api_key or api_key in {"id", "sortNum"}:
                continue
            try:
                agg = await _await(data_backend.aggregate_data(
                    entity_api_key,
                    [
                        {"field": api_key, "function": "sum"},
                        {"field": api_key, "function": "avg"},
                        {"field": api_key, "function": "max"},
                    ],
                ))
            except Exception as exc:
                logger.warning("aggregate failed: %s.%s — %s", entity_api_key, api_key, exc)
                continue
            row = ((agg or {}).get("data") or {}).get("results", [{}])[0]
            numeric_metrics.append({
                "field": api_key,
                "label": it.get("label"),
                "sum": row.get(f"sum_{api_key}"),
                "avg": row.get(f"avg_{api_key}"),
                "max": row.get(f"max_{api_key}"),
            })

    return {
        "entityApiKey": entity_api_key,
        "label": meta_entity.get("label") or _sim_entity_label(entity_api_key) or entity_api_key,
        "namespace": meta_entity.get("namespace"),
        "items": items,
        "total": sample_data.get("total", 0),
        "sample": sample_data.get("records", []),
        "numericMetrics": numeric_metrics,
    }


@router.get("/data/{entity_api_key}")
async def list_data_records(
    entity_api_key: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200, alias="pageSize"),
    order_by: Optional[str] = Query(None, alias="orderBy"),
) -> dict:
    """分页查询业务数据（对齐 GET /entity/data/{entityApiKey}）。"""
    if not await _has_data_entity(entity_api_key):
        raise HTTPException(404, f"业务对象 {entity_api_key} 未注册数据后端")
    data_backend = _get_data_backend()
    result = await _await(data_backend.query_data(
        entity_api_key,
        filters={},
        page=page,
        page_size=page_size,
        order_by=order_by,
    ))
    data = (result or {}).get("data") or {}
    return {
        "entityApiKey": entity_api_key,
        "page": page,
        "pageSize": page_size,
        "total": data.get("total", 0),
        "records": data.get("records", []),
    }


@router.get("/data/{entity_api_key}/{record_id}")
async def get_data_record(entity_api_key: str, record_id: str) -> dict:
    """查询单条业务数据（对齐 GET /entity/data/{entityApiKey}/{id}）。"""
    if not await _has_data_entity(entity_api_key):
        raise HTTPException(404, f"业务对象 {entity_api_key} 未注册数据后端")
    data_backend = _get_data_backend()
    if _is_http_data(data_backend):
        record = await _await(data_backend.get_by_id(entity_api_key, record_id))
    else:
        resp = await _await(data_backend.query_data(entity_api_key, filters={"id": record_id}))
        records = ((resp or {}).get("data") or {}).get("records", [])
        record = records[0] if records else None
    if record is None:
        raise HTTPException(404, f"{entity_api_key} 记录 {record_id} 不存在")
    return record
