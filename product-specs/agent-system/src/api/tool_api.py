"""Tool 工具管理 REST API

路由前缀：/api/tools

提供：
    - GET    /api/tools              工具列表
    - GET    /api/tools/{api_key}    工具详情
    - POST   /api/tools              创建工具
    - PUT    /api/tools/{api_key}    编辑工具
    - PUT    /api/tools/{api_key}/toggle  启用/禁用
    - DELETE /api/tools/{api_key}    删除工具
"""
from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.store.tool_dao import ToolDefinitionDAO, ToolDefinitionRow
from src.store.snowflake import next_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tools", tags=["tools"])


# ═══════════════════════════════════════════════════════════
# Pydantic 请求模型
# ═══════════════════════════════════════════════════════════

class CreateToolBody(BaseModel):
    api_key: str = Field(..., min_length=2, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    input_schema: dict = Field(default_factory=dict)
    prompt: str = Field(default="")
    category: str = Field(default="", max_length=50)
    tags: list[str] = Field(default_factory=list)
    icon: str = Field(default="", max_length=100)
    read_only: bool = Field(default=True)
    destructive: bool = Field(default=False)


class UpdateToolBody(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    input_schema: dict | None = None
    prompt: str | None = None
    category: str | None = Field(default=None, max_length=50)
    tags: list[str] | None = None
    icon: str | None = Field(default=None, max_length=100)
    read_only: bool | None = None
    destructive: bool | None = None


class ToggleToolBody(BaseModel):
    enabled: bool


# ═══════════════════════════════════════════════════════════
# 列表
# ═══════════════════════════════════════════════════════════

@router.get("")
async def list_tools(tenant_id: int = Query(0), category: str = Query("")):
    """列出所有工具"""
    rows = ToolDefinitionDAO.list_all(tenant_id=tenant_id)
    if category:
        rows = [r for r in rows if r.category == category]
    return {"items": [_row_to_dict(r) for r in rows], "total": len(rows)}


# ═══════════════════════════════════════════════════════════
# 详情
# ═══════════════════════════════════════════════════════════

@router.get("/{api_key}")
async def get_tool(api_key: str, tenant_id: int = Query(0)):
    """获取工具详情"""
    row = ToolDefinitionDAO.get_by_api_key(tenant_id, api_key)
    if row is None:
        raise HTTPException(status_code=404, detail=f"工具 '{api_key}' 不存在")
    return _row_to_detail(row)


# ═══════════════════════════════════════════════════════════
# 创建
# ═══════════════════════════════════════════════════════════

@router.post("", status_code=201)
async def create_tool(body: CreateToolBody, tenant_id: int = Query(0)):
    """创建工具"""
    existing = ToolDefinitionDAO.get_by_api_key(tenant_id, body.api_key)
    if existing is not None:
        raise HTTPException(status_code=400, detail={
            "message": f"工具 '{body.api_key}' 已存在", "code": "DUPLICATE_KEY"
        })

    now = int(time.time() * 1000)
    row = ToolDefinitionRow(
        id=next_id(),
        api_key=body.api_key,
        tenant_id=tenant_id,
        name=body.name,
        description=body.description,
        input_schema=json.dumps(body.input_schema, ensure_ascii=False),
        prompt=body.prompt,
        category=body.category,
        tags=json.dumps(body.tags, ensure_ascii=False),
        icon=body.icon,
        read_only_flg=1 if body.read_only else 0,
        destructive_flg=1 if body.destructive else 0,
        enabled_flg=1,
        system_flg=0,
        sort_num=0,
        delete_flg=0,
        created_at=now,
        updated_at=now,
    )
    ToolDefinitionDAO.create(row)
    return _row_to_dict(row)


# ═══════════════════════════════════════════════════════════
# 编辑
# ═══════════════════════════════════════════════════════════

@router.put("/{api_key}")
async def update_tool(api_key: str, body: UpdateToolBody, tenant_id: int = Query(0)):
    """编辑工具"""
    existing = ToolDefinitionDAO.get_by_api_key(tenant_id, api_key)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"工具 '{api_key}' 不存在")

    now = int(time.time() * 1000)
    updates: dict = {"updated_at": now}

    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if body.input_schema is not None:
        updates["input_schema"] = json.dumps(body.input_schema, ensure_ascii=False)
    if body.prompt is not None:
        updates["prompt"] = body.prompt
    if body.category is not None:
        updates["category"] = body.category
    if body.tags is not None:
        updates["tags"] = json.dumps(body.tags, ensure_ascii=False)
    if body.icon is not None:
        updates["icon"] = body.icon
    if body.read_only is not None:
        updates["read_only_flg"] = 1 if body.read_only else 0
    if body.destructive is not None:
        updates["destructive_flg"] = 1 if body.destructive else 0

    ToolDefinitionDAO.update_fields(tenant_id, api_key, updates)

    row = ToolDefinitionDAO.get_by_api_key(tenant_id, api_key)
    return _row_to_dict(row)


# ═══════════════════════════════════════════════════════════
# 启用/禁用
# ═══════════════════════════════════════════════════════════

@router.put("/{api_key}/toggle")
async def toggle_tool(api_key: str, body: ToggleToolBody, tenant_id: int = Query(0)):
    """启用/禁用工具"""
    existing = ToolDefinitionDAO.get_by_api_key(tenant_id, api_key)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"工具 '{api_key}' 不存在")

    now = int(time.time() * 1000)
    ToolDefinitionDAO.update_fields(tenant_id, api_key, {
        "enabled_flg": 1 if body.enabled else 0,
        "updated_at": now,
    })
    action = "启用" if body.enabled else "禁用"
    return {"api_key": api_key, "enabled": body.enabled, "message": f"工具已{action}"}


# ═══════════════════════════════════════════════════════════
# 删除
# ═══════════════════════════════════════════════════════════

@router.delete("/{api_key}")
async def delete_tool(api_key: str, tenant_id: int = Query(0)):
    """删除工具（系统预置不可删）"""
    existing = ToolDefinitionDAO.get_by_api_key(tenant_id, api_key)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"工具 '{api_key}' 不存在")
    if existing.system_flg == 1:
        raise HTTPException(status_code=400, detail={
            "message": f"系统预置工具 '{api_key}' 不可删除", "code": "SYSTEM_TOOL"
        })

    now = int(time.time() * 1000)
    ToolDefinitionDAO.soft_delete(tenant_id, api_key, now=now)
    return {"message": f"工具 '{api_key}' 已删除"}


# ═══════════════════════════════════════════════════════════
# 序列化
# ═══════════════════════════════════════════════════════════

def _safe_json(s, default=None):
    try:
        return json.loads(s) if s else default
    except (json.JSONDecodeError, TypeError):
        return default


def _row_to_dict(row: ToolDefinitionRow) -> dict:
    return {
        "api_key": row.api_key,
        "name": row.name,
        "description": row.description,
        "category": row.category,
        "tags": _safe_json(row.tags, []),
        "icon": row.icon,
        "read_only": bool(row.read_only_flg),
        "destructive": bool(row.destructive_flg),
        "enabled": bool(row.enabled_flg),
        "system": bool(row.system_flg),
        "sort_num": row.sort_num,
        "tenant_id": row.tenant_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _row_to_detail(row: ToolDefinitionRow) -> dict:
    d = _row_to_dict(row)
    d.update({
        "input_schema": _safe_json(row.input_schema, {}),
        "prompt": row.prompt,
        "ext_info": _safe_json(row.ext_info, {}),
    })
    return d
