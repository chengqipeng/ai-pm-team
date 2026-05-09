"""Skill 管理 REST API

由 server.py 通过 `app.include_router(skill_router)` 挂载。

路由前缀：/api/skills

提供：
    - GET  /api/skills          列表（支持 keyword / status 筛选）
    - GET  /api/skills/{api_key}  详情（含 prompt 全文）
    - GET  /api/skills/{api_key}/versions  版本历史
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.store.skill_dao import SkillDefinitionDAO, SkillVersionDAO

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skills", tags=["skills"])


# ═══════════════════════════════════════════════════════════
# 列表
# ═══════════════════════════════════════════════════════════

@router.get("")
async def list_skills(
    tenant_id: int = Query(0, description="租户 ID（0=平台级）"),
    status: str = Query("", description="按状态筛选: published/draft/deprecated"),
    keyword: str = Query("", description="模糊搜索 api_key/name/description"),
):
    """列出所有 Skill 定义（不含 prompt 全文，减少传输量）"""
    rows = SkillDefinitionDAO.list_all(
        tenant_id=tenant_id,
        status=status or None,
        keyword=keyword or None,
        include_platform=True,
    )
    return [_row_to_summary(r) for r in rows]


# ═══════════════════════════════════════════════════════════
# 详情
# ═══════════════════════════════════════════════════════════

@router.get("/{api_key}")
async def get_skill(api_key: str, tenant_id: int = Query(0)):
    """获取 Skill 完整定义（含 prompt 全文）"""
    row = SkillDefinitionDAO.get_by_api_key(tenant_id, api_key)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Skill '{api_key}' not found")
    return _row_to_detail(row)


# ═══════════════════════════════════════════════════════════
# 版本历史
# ═══════════════════════════════════════════════════════════

@router.get("/{api_key}/versions")
async def list_versions(api_key: str, tenant_id: int = Query(0)):
    """获取 Skill 的版本历史"""
    rows = SkillVersionDAO.list_by_api_key(tenant_id, api_key)
    return [_version_to_dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════
# 序列化
# ═══════════════════════════════════════════════════════════

def _safe_json_loads(s: str, default: Any = None) -> Any:
    try:
        return json.loads(s) if s else default
    except (json.JSONDecodeError, TypeError):
        return default


def _row_to_summary(row) -> dict:
    return {
        "api_key": row.api_key,
        "name": row.name,
        "description": row.description,
        "when_to_use": row.when_to_use,
        "context": row.context,
        "agent": row.agent,
        "risk_level": row.risk_level,
        "version": row.version,
        "status": row.status,
        "owner": row.owner,
        "arguments": _safe_json_loads(row.arguments, []),
        "allowed_tools": _safe_json_loads(row.allowed_tools, []),
        "exec_count": row.exec_count,
        "success_count": row.success_count,
        "avg_duration_ms": row.avg_duration_ms,
        "tenant_id": row.tenant_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _row_to_detail(row) -> dict:
    d = _row_to_summary(row)
    d.update({
        "prompt": row.prompt,
        "model": row.model,
        "max_tool_calls": row.max_tool_calls,
        "timeout_ms": row.timeout_ms,
        "requires_confirmation": bool(row.requires_confirmation),
        "idempotent": bool(row.idempotent_flg),
        "ext_info": _safe_json_loads(row.ext_info, {}),
        "published_at": row.published_at,
    })
    return d


def _version_to_dict(row) -> dict:
    return {
        "version": row.version,
        "skill_api_key": row.skill_api_key,
        "description": row.description,
        "context": row.context,
        "changelog": row.changelog,
        "created_at": row.created_at,
    }
