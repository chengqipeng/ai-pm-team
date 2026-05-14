"""Skill 分类管理 REST API

路由前缀：/api/skill-categories

提供：
    - GET    /api/skill-categories              分类列表
    - POST   /api/skill-categories              创建分类
    - PUT    /api/skill-categories/{api_key}    编辑分类
    - DELETE /api/skill-categories/{api_key}    删除分类
    - PUT    /api/skill-categories/sort         批量更新排序
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.store.skill_category_dao import SkillCategoryDAO

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skill-categories", tags=["skill-categories"])


# ═══════════════════════════════════════════════════════════
# Pydantic 请求模型
# ═══════════════════════════════════════════════════════════

class CreateCategoryBody(BaseModel):
    api_key: str = Field(..., min_length=2, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    icon: str = Field(default="", max_length=100)
    color: str = Field(default="", max_length=20)
    sort_num: int = Field(default=0)


class UpdateCategoryBody(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    icon: str | None = Field(default=None, max_length=100)
    color: str | None = Field(default=None, max_length=20)
    sort_num: int | None = None
    enabled: bool | None = None


class SortCategoryBody(BaseModel):
    """批量排序：传入 api_key 列表，按顺序分配 sort_num"""
    items: list[str] = Field(..., description="按排序顺序排列的 api_key 列表")


# ═══════════════════════════════════════════════════════════
# 列表
# ═══════════════════════════════════════════════════════════

@router.get("")
async def list_categories(tenant_id: int = Query(0)):
    """获取分类列表（含每个分类下的技能数量）"""
    rows = SkillCategoryDAO.list_all(tenant_id=tenant_id)
    return {"items": [_row_to_dict(r) for r in rows]}


# ═══════════════════════════════════════════════════════════
# 创建
# ═══════════════════════════════════════════════════════════

@router.post("", status_code=201)
async def create_category(body: CreateCategoryBody, tenant_id: int = Query(0)):
    """创建新分类"""
    # 检查 api_key 唯一性
    existing = SkillCategoryDAO.get_by_api_key(tenant_id, body.api_key)
    if existing is not None:
        raise HTTPException(status_code=400, detail={
            "message": f"分类 '{body.api_key}' 已存在",
            "code": "DUPLICATE_KEY",
        })

    now = int(time.time() * 1000)
    row = SkillCategoryDAO.create(
        tenant_id=tenant_id,
        api_key=body.api_key,
        name=body.name,
        description=body.description,
        icon=body.icon,
        color=body.color,
        sort_num=body.sort_num,
        now=now,
    )
    return _row_to_dict(row)


# ═══════════════════════════════════════════════════════════
# 编辑
# ═══════════════════════════════════════════════════════════

@router.put("/{api_key}")
async def update_category(api_key: str, body: UpdateCategoryBody, tenant_id: int = Query(0)):
    """编辑分类"""
    existing = SkillCategoryDAO.get_by_api_key(tenant_id, api_key)
    if existing is None:
        raise HTTPException(status_code=404, detail={
            "message": f"分类 '{api_key}' 不存在",
            "code": "NOT_FOUND",
        })

    updates: dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if body.icon is not None:
        updates["icon"] = body.icon
    if body.color is not None:
        updates["color"] = body.color
    if body.sort_num is not None:
        updates["sort_num"] = body.sort_num
    if body.enabled is not None:
        updates["enabled_flg"] = 1 if body.enabled else 0

    if not updates:
        return _row_to_dict(existing)

    now = int(time.time() * 1000)
    row = SkillCategoryDAO.update(tenant_id, api_key, updates, now=now)
    return _row_to_dict(row)


# ═══════════════════════════════════════════════════════════
# 删除
# ═══════════════════════════════════════════════════════════

@router.delete("/{api_key}")
async def delete_category(api_key: str, tenant_id: int = Query(0)):
    """删除分类（系统预置分类不可删除）"""
    existing = SkillCategoryDAO.get_by_api_key(tenant_id, api_key)
    if existing is None:
        raise HTTPException(status_code=404, detail={
            "message": f"分类 '{api_key}' 不存在",
            "code": "NOT_FOUND",
        })

    if getattr(existing, "system_flg", 0) == 1:
        raise HTTPException(status_code=400, detail={
            "message": f"系统预置分类 '{api_key}' 不可删除",
            "code": "SYSTEM_CATEGORY",
        })

    now = int(time.time() * 1000)
    SkillCategoryDAO.soft_delete(tenant_id, api_key, now=now)
    return {"message": f"分类 '{api_key}' 已删除"}


# ═══════════════════════════════════════════════════════════
# 批量排序
# ═══════════════════════════════════════════════════════════

@router.put("/sort")
async def sort_categories(body: SortCategoryBody, tenant_id: int = Query(0)):
    """批量更新分类排序"""
    now = int(time.time() * 1000)
    for idx, api_key in enumerate(body.items):
        sort_num = (idx + 1) * 10
        SkillCategoryDAO.update(tenant_id, api_key, {"sort_num": sort_num}, now=now)
    return {"message": "排序已更新", "count": len(body.items)}


# ═══════════════════════════════════════════════════════════
# 序列化
# ═══════════════════════════════════════════════════════════

def _row_to_dict(row) -> dict:
    return {
        "api_key": row.api_key,
        "name": row.name,
        "name_key": getattr(row, "name_key", ""),
        "description": getattr(row, "description", ""),
        "icon": getattr(row, "icon", ""),
        "color": getattr(row, "color", ""),
        "sort_num": getattr(row, "sort_num", 0),
        "enabled": bool(getattr(row, "enabled_flg", 1)),
        "system": bool(getattr(row, "system_flg", 0)),
        "skill_count": getattr(row, "skill_count", 0),
        "tenant_id": row.tenant_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
