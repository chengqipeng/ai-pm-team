"""Skill 管理 REST API

由 server.py 通过 `app.include_router(skill_router)` 挂载。

路由前缀：/api/skills

提供：
    - GET    /api/skills                列表（支持分页、筛选、搜索）
    - GET    /api/skills/categories     分类列表
    - GET    /api/skills/stats          执行统计概览
    - GET    /api/skills/{api_key}      详情
    - POST   /api/skills                创建
    - PUT    /api/skills/{api_key}      编辑
    - PUT    /api/skills/{api_key}/toggle  启用/禁用
    - POST   /api/skills/{api_key}/clone   克隆
    - POST   /api/skills/{api_key}/test    测试执行
    - DELETE /api/skills/{api_key}      软删除
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.skills.service import SkillService, SkillCreateRequest, SkillUpdateRequest, SkillServiceError
from src.store.skill_dao import SkillDefinitionDAO

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skills", tags=["skills"])

# 全局 SkillService 实例（server.py 启动后可注入 skill_registry）
_skill_service: SkillService | None = None


def get_skill_service() -> SkillService:
    global _skill_service
    if _skill_service is None:
        _skill_service = SkillService()
    return _skill_service


def set_skill_service(service: SkillService) -> None:
    global _skill_service
    _skill_service = service


# ═══════════════════════════════════════════════════════════
# Pydantic 请求模型
# ═══════════════════════════════════════════════════════════

class CreateSkillBody(BaseModel):
    api_key: str = Field(..., min_length=2, max_length=99)
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=1000)
    prompt: str = Field(..., min_length=1)
    when_to_use: str = Field(default="", max_length=500)
    category: str = Field(default="", max_length=50)
    tags: list[str] = Field(default_factory=list)
    context: str = Field(default="inline")
    agent: str = Field(default="", max_length=100)
    model: str = Field(default="", max_length=100)
    allowed_tools: list[str] = Field(default_factory=list)
    arguments: list[str] = Field(default_factory=list)
    argument_descriptions: dict[str, str] = Field(default_factory=dict)
    argument_config: dict[str, Any] = Field(default_factory=dict)
    risk_level: str = Field(default="read_only")
    requires_confirmation: bool = Field(default=False)
    max_tool_calls: int = Field(default=20, ge=1, le=100)
    timeout_ms: int = Field(default=60000, ge=5000, le=300000)
    owner: str = Field(default="", max_length=100)
    icon: str = Field(default="", max_length=100)
    sort_num: int = Field(default=0)


class UpdateSkillBody(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    prompt: str | None = None
    when_to_use: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=50)
    tags: list[str] | None = None
    context: str | None = None
    agent: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    allowed_tools: list[str] | None = None
    arguments: list[str] | None = None
    argument_descriptions: dict[str, str] | None = None
    argument_config: dict[str, Any] | None = None
    risk_level: str | None = None
    requires_confirmation: bool | None = None
    max_tool_calls: int | None = Field(default=None, ge=1, le=100)
    timeout_ms: int | None = Field(default=None, ge=5000, le=300000)
    owner: str | None = Field(default=None, max_length=100)
    icon: str | None = Field(default=None, max_length=100)
    sort_num: int | None = None


class ToggleSkillBody(BaseModel):
    enabled: bool


class CloneSkillBody(BaseModel):
    new_api_key: str = Field(..., min_length=2, max_length=99)


class TestSkillBody(BaseModel):
    arguments: dict[str, str] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
# 列表
# ═══════════════════════════════════════════════════════════

@router.get("")
async def list_skills(
    tenant_id: int = Query(0, description="租户 ID（0=平台级）"),
    enabled: bool | None = Query(None, description="按启用状态筛选"),
    category: str = Query("", description="按分类筛选"),
    keyword: str = Query("", description="模糊搜索 api_key/name/description"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """列出所有 Skill 定义"""
    # 构建筛选条件
    status_filter = None
    if enabled is True:
        status_filter = "published"
    elif enabled is False:
        status_filter = "deprecated"

    rows = SkillDefinitionDAO.list_all(
        tenant_id=tenant_id,
        status=status_filter,
        keyword=keyword or None,
        include_platform=True,
    )

    # 按 category 过滤（如果指定）
    if category:
        rows = [r for r in rows if getattr(r, "category", "") == category]

    # 分页
    total = len(rows)
    start = (page - 1) * page_size
    end = start + page_size
    page_rows = rows[start:end]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_row_to_summary(r) for r in page_rows],
    }


# ═══════════════════════════════════════════════════════════
# 分类列表
# ═══════════════════════════════════════════════════════════

@router.get("/categories")
async def list_categories():
    """获取所有分类及其技能数量（从 ai_skill_category 表动态读取）"""
    from src.store.skill_category_dao import SkillCategoryDAO
    rows = SkillCategoryDAO.list_all(tenant_id=0)
    return [
        {
            "key": r.api_key,
            "label": r.name,
            "icon": r.icon,
            "color": r.color,
            "enabled": bool(r.enabled_flg),
            "system": bool(r.system_flg),
            "skill_count": r.skill_count,
        }
        for r in rows
    ]


# ═══════════════════════════════════════════════════════════
# 统计概览
# ═══════════════════════════════════════════════════════════

@router.get("/stats")
async def get_stats(tenant_id: int = Query(0)):
    """获取 Skill 执行统计概览"""
    rows = SkillDefinitionDAO.list_all(tenant_id=tenant_id, include_platform=True)
    total = len(rows)
    enabled_count = sum(1 for r in rows if getattr(r, "enabled_flg", 1) == 1)
    total_exec = sum(r.exec_count for r in rows)
    total_success = sum(r.success_count for r in rows)
    return {
        "total_skills": total,
        "enabled_count": enabled_count,
        "disabled_count": total - enabled_count,
        "total_executions": total_exec,
        "total_success": total_success,
        "success_rate": round(total_success / max(total_exec, 1), 3),
    }


# ═══════════════════════════════════════════════════════════
# 详情
# ═══════════════════════════════════════════════════════════

@router.get("/{api_key}")
async def get_skill(api_key: str, tenant_id: int = Query(0)):
    """获取 Skill 完整定义"""
    row = SkillDefinitionDAO.get_by_api_key(tenant_id, api_key)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Skill '{api_key}' not found")
    return _row_to_detail(row)


# ═══════════════════════════════════════════════════════════
# 创建
# ═══════════════════════════════════════════════════════════

@router.post("", status_code=201)
async def create_skill(body: CreateSkillBody, tenant_id: int = Query(0)):
    """创建新 Skill"""
    service = get_skill_service()
    req = SkillCreateRequest(
        api_key=body.api_key,
        name=body.name,
        description=body.description,
        prompt=body.prompt,
        when_to_use=body.when_to_use,
        category=body.category,
        tags=body.tags,
        context=body.context,
        agent=body.agent,
        model=body.model,
        allowed_tools=body.allowed_tools,
        arguments=body.arguments,
        risk_level=body.risk_level,
        requires_confirmation=body.requires_confirmation,
        max_tool_calls=body.max_tool_calls,
        timeout_ms=body.timeout_ms,
        owner=body.owner,
        icon=body.icon,
        sort_num=body.sort_num,
    )
    try:
        result = service.create(req, tenant_id=tenant_id)
        # 存储 argument_descriptions 和 argument_config 到 ext_info
        if body.argument_descriptions or body.argument_config:
            _save_argument_ext(tenant_id, body.api_key, body.argument_descriptions, body.argument_config)
            result["argument_descriptions"] = body.argument_descriptions
            result["argument_config"] = body.argument_config
        return result
    except SkillServiceError as e:
        raise HTTPException(status_code=400, detail={"message": str(e), "code": e.code})


# ═══════════════════════════════════════════════════════════
# 编辑
# ═══════════════════════════════════════════════════════════

@router.put("/{api_key}")
async def update_skill(api_key: str, body: UpdateSkillBody, tenant_id: int = Query(0)):
    """编辑 Skill"""
    service = get_skill_service()
    req = SkillUpdateRequest(
        name=body.name,
        description=body.description,
        prompt=body.prompt,
        when_to_use=body.when_to_use,
        category=body.category,
        tags=body.tags,
        context=body.context,
        agent=body.agent,
        model=body.model,
        allowed_tools=body.allowed_tools,
        arguments=body.arguments,
        risk_level=body.risk_level,
        requires_confirmation=body.requires_confirmation,
        max_tool_calls=body.max_tool_calls,
        timeout_ms=body.timeout_ms,
        owner=body.owner,
        icon=body.icon,
        sort_num=body.sort_num,
    )
    try:
        result = service.update(api_key, req, tenant_id=tenant_id)
        # 存储 argument_descriptions 和 argument_config 到 ext_info
        if body.argument_descriptions is not None or body.argument_config is not None:
            _save_argument_ext(tenant_id, api_key, body.argument_descriptions, body.argument_config)
            if body.argument_descriptions is not None:
                result["argument_descriptions"] = body.argument_descriptions
            if body.argument_config is not None:
                result["argument_config"] = body.argument_config
        return result
    except SkillServiceError as e:
        status = 404 if e.code == "NOT_FOUND" else 400
        raise HTTPException(status_code=status, detail={"message": str(e), "code": e.code})


# ═══════════════════════════════════════════════════════════
# 启用/禁用
# ═══════════════════════════════════════════════════════════

@router.put("/{api_key}/toggle")
async def toggle_skill(api_key: str, body: ToggleSkillBody, tenant_id: int = Query(0)):
    """启用或禁用 Skill"""
    service = get_skill_service()
    try:
        result = service.toggle(api_key, body.enabled, tenant_id=tenant_id)
        action = "启用" if body.enabled else "禁用"
        return {**result, "message": f"技能已{action}"}
    except SkillServiceError as e:
        status = 404 if e.code == "NOT_FOUND" else 400
        raise HTTPException(status_code=status, detail={"message": str(e), "code": e.code})


# ═══════════════════════════════════════════════════════════
# 克隆
# ═══════════════════════════════════════════════════════════

@router.post("/{api_key}/clone", status_code=201)
async def clone_skill(api_key: str, body: CloneSkillBody, tenant_id: int = Query(0)):
    """克隆 Skill"""
    service = get_skill_service()
    try:
        return service.clone(api_key, body.new_api_key, tenant_id=tenant_id)
    except SkillServiceError as e:
        status = 404 if e.code == "NOT_FOUND" else 400
        raise HTTPException(status_code=status, detail={"message": str(e), "code": e.code})


# ═══════════════════════════════════════════════════════════
# 测试执行
# ═══════════════════════════════════════════════════════════

@router.post("/{api_key}/test")
async def test_skill(api_key: str, body: TestSkillBody, tenant_id: int = Query(0)):
    """测试执行 Skill（dry-run，返回格式化后的 prompt）"""
    service = get_skill_service()
    try:
        result = await service.test_execute(api_key, body.arguments, tenant_id=tenant_id)
        return {"api_key": api_key, "output": result}
    except SkillServiceError as e:
        status = 404 if e.code == "NOT_FOUND" else 400
        raise HTTPException(status_code=status, detail={"message": str(e), "code": e.code})


# ═══════════════════════════════════════════════════════════
# 删除
# ═══════════════════════════════════════════════════════════

@router.delete("/{api_key}")
async def delete_skill(api_key: str, tenant_id: int = Query(0)):
    """软删除 Skill"""
    service = get_skill_service()
    try:
        service.delete(api_key, tenant_id=tenant_id)
        return {"message": f"技能 '{api_key}' 已删除"}
    except SkillServiceError as e:
        status = 404 if e.code == "NOT_FOUND" else 400
        raise HTTPException(status_code=status, detail={"message": str(e), "code": e.code})


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
        "category": getattr(row, "category", ""),
        "tags": _safe_json_loads(getattr(row, "tags", "[]"), []),
        "context": row.context,
        "agent": row.agent,
        "risk_level": row.risk_level,
        "version": row.version,
        "enabled": bool(getattr(row, "enabled_flg", 1)),
        "system": bool(getattr(row, "system_flg", 0)),
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
    ext = _safe_json_loads(row.ext_info, {})
    d.update({
        "prompt": row.prompt,
        "model": row.model,
        "max_tool_calls": row.max_tool_calls,
        "timeout_ms": row.timeout_ms,
        "requires_confirmation": bool(row.requires_confirmation),
        "idempotent": bool(row.idempotent_flg),
        "icon": getattr(row, "icon", ""),
        "sort_num": getattr(row, "sort_num", 0),
        "argument_descriptions": ext.get("argument_descriptions", {}),
        "argument_config": ext.get("argument_config", {}),
        "ext_info": ext,
    })
    return d


def _save_argument_ext(tenant_id: int, api_key: str,
                       descriptions: dict[str, str] | None,
                       config: dict[str, Any] | None) -> None:
    """将 argument_descriptions 和 argument_config 存入 ext_info JSON 字段"""
    from src.store.pg_pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        # 读取当前 ext_info
        cur.execute(
            "SELECT ext_info FROM ai_skill_definition WHERE tenant_id = %s AND api_key = %s AND delete_flg = 0",
            (tenant_id, api_key),
        )
        row = cur.fetchone()
        if row is None:
            return

        ext = _safe_json_loads(row[0], {})
        if descriptions is not None:
            ext["argument_descriptions"] = descriptions
        if config is not None:
            ext["argument_config"] = config

        # 写回
        cur.execute(
            "UPDATE ai_skill_definition SET ext_info = %s WHERE tenant_id = %s AND api_key = %s AND delete_flg = 0",
            (json.dumps(ext, ensure_ascii=False), tenant_id, api_key),
        )


# 保留旧函数名兼容（manage_skill_tool.py 中有引用）
_save_argument_descriptions = lambda tid, ak, descs: _save_argument_ext(tid, ak, descs, None)
