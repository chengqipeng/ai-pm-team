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
    - GET    /api/skills/{api_key}/export  打包下载为 zip

    版本管理：
    - GET    /api/skills/{api_key}/versions              版本列表
    - GET    /api/skills/{api_key}/versions/{version}    版本详情
    - POST   /api/skills/{api_key}/versions              发布新版本
    - GET    /api/skills/{api_key}/versions/diff         两版本差异对比
    - POST   /api/skills/{api_key}/versions/rollback     回滚到指定版本

    变更日志：
    - GET    /api/skills/{api_key}/change-logs           变更日志列表（分页）

    资源文件管理（knowledge 目录）：
    - GET    /api/skills/{api_key}/resources             获取资源文件树
    - GET    /api/skills/{api_key}/resources/content     读取文件内容
    - PUT    /api/skills/{api_key}/resources/content     保存文件内容
    - POST   /api/skills/{api_key}/resources             创建目录或文件
    - DELETE /api/skills/{api_key}/resources             删除目录或文件
    - PUT    /api/skills/{api_key}/resources/rename      重命名
    - PUT    /api/skills/{api_key}/resources/move        移动到新目录
"""
from __future__ import annotations

import io
import json
import logging
import zipfile
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.skills.service import SkillService, SkillCreateRequest, SkillUpdateRequest, SkillServiceError
from src.skills.version_service import SkillVersionService, CreateVersionRequest, SkillVersionError
from src.store.skill_dao import SkillDAO, SkillDefinitionDAO

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


# 全局 SkillVersionService 实例
_version_service: SkillVersionService | None = None


def get_version_service() -> SkillVersionService:
    global _version_service
    if _version_service is None:
        # 共享 SkillService 的 registry，确保版本切换后运行时同步更新
        skill_svc = get_skill_service()
        registry = getattr(skill_svc, '_skill_registry', None)
        _version_service = SkillVersionService(skill_registry=registry)
    return _version_service


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
    requires_confirmation: bool | None = None
    max_tool_calls: int | None = Field(default=None, ge=1, le=100)
    timeout_ms: int | None = Field(default=None, ge=5000, le=300000)
    owner: str | None = Field(default=None, max_length=100)
    icon: str | None = Field(default=None, max_length=100)
    sort_num: int | None = None
    output_mode: str | None = Field(default=None, pattern="^(text|card|component|table)$")
    component_apikey: str | None = Field(default=None, max_length=100)


class ToggleSkillBody(BaseModel):
    enabled: bool


class CloneSkillBody(BaseModel):
    new_api_key: str = Field(..., min_length=2, max_length=99)


class TestSkillBody(BaseModel):
    arguments: dict[str, str] = Field(default_factory=dict)


class PublishVersionBody(BaseModel):
    """创建新版本请求体"""
    version: str = Field(..., min_length=5, max_length=30,
                         description="版本号（semver 格式，如 1.2.0）")
    changelog: str = Field(default="", max_length=2000,
                           description="变更说明")


class RollbackVersionBody(BaseModel):
    """版本回滚请求体"""
    target_version: str = Field(..., min_length=5, max_length=30,
                                description="要回滚到的目标版本号")


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
    """列出所有 Skill（从 ai_skill 主记录表查询）"""
    rows = SkillDAO.list_all(
        tenant_id=tenant_id,
        keyword=keyword or None,
        category=category or None,
        enabled=enabled,
        include_platform=True,
    )

    # 分页
    total = len(rows)
    start = (page - 1) * page_size
    end = start + page_size
    page_rows = rows[start:end]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_skill_row_to_summary(r) for r in page_rows],
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
    rows = SkillDAO.list_all(tenant_id=tenant_id, include_platform=True)
    total = len(rows)
    enabled_count = sum(1 for r in rows if r.enabled_flg == 1)
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
    """获取 Skill 完整定义（主记录 + 当前版本内容）"""
    skill = SkillDAO.get_by_api_key(tenant_id, api_key)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{api_key}' not found")
    # 获取当前版本的 definition
    definition = SkillDefinitionDAO.get_by_version(tenant_id, api_key, skill.current_version)
    return _skill_to_detail(skill, definition)


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
    # 系统预置技能不允许编辑
    skill = SkillDAO.get_by_api_key(tenant_id, api_key)
    if skill and bool(skill.system_flg):
        raise HTTPException(status_code=403, detail=f"系统预置技能 '{api_key}' 为只读，不允许编辑")

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
        requires_confirmation=body.requires_confirmation,
        max_tool_calls=body.max_tool_calls,
        timeout_ms=body.timeout_ms,
        owner=body.owner,
        icon=body.icon,
        sort_num=body.sort_num,
        output_mode=body.output_mode,
        component_apikey=body.component_apikey,
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
    # 系统预置技能不允许删除
    skill = SkillDAO.get_by_api_key(tenant_id, api_key)
    if skill and bool(skill.system_flg):
        raise HTTPException(status_code=403, detail=f"系统预置技能 '{api_key}' 为只读，不允许删除")

    service = get_skill_service()
    try:
        service.delete(api_key, tenant_id=tenant_id)
        return {"message": f"技能 '{api_key}' 已删除"}
    except SkillServiceError as e:
        status = 404 if e.code == "NOT_FOUND" else 400
        raise HTTPException(status_code=status, detail={"message": str(e), "code": e.code})


# ═══════════════════════════════════════════════════════════
# 打包下载（Export as ZIP）
# ═══════════════════════════════════════════════════════════

@router.get("/{api_key}/export")
async def export_skill_zip(api_key: str, tenant_id: int = Query(0)):
    """将 Skill 定义及其资源文件打包为 zip 下载

    zip 结构:
        {api_key}/
        ├── SKILL.json          # 技能完整定义（元数据 + prompt + 配置）
        ├── SKILL.md            # Prompt 原文（方便阅读）
        ├── scripts/            # Python 脚本（如有）
        │   ├── main.py
        │   └── requirements.txt
        ├── references/         # 方法论/评分标准（如有）
        │   ├── _index.md
        │   └── ...
        └── knowledge/          # 行业知识（如有）
            ├── _index.md
            └── industries/
                └── ...
    """
    from src.store.pg_pool import get_conn

    # 1. 获取 Skill 主记录 + 当前版本定义
    skill = SkillDAO.get_by_api_key(tenant_id, api_key)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{api_key}' not found")

    definition = SkillDefinitionDAO.get_by_version(tenant_id, api_key, skill.current_version)
    detail = _skill_to_detail(skill, definition)

    # 移除前端不需要的内部字段
    for key in ("readonly", "ext_info"):
        detail.pop(key, None)

    # 2. 获取资源文件列表（当前版本）
    version = skill.current_version or "1.0.0"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT path, content, content_type
            FROM ai_skill_resource
            WHERE skill_api_key = %s AND tenant_id = %s AND version = %s
                  AND node_type = 'file' AND delete_flg = 0 AND enabled_flg = 1
            ORDER BY path
        """, (api_key, tenant_id, version))
        resource_rows = cur.fetchall()

    # 3. 生成 zip 文件到内存
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # SKILL.json — 完整定义（含 prompt）
        skill_json = json.dumps(detail, ensure_ascii=False, indent=2)
        zf.writestr(f"{api_key}/SKILL.json", skill_json)

        # SKILL.md — Prompt 原文方便阅读
        prompt_text = detail.get("prompt", "")
        if prompt_text:
            zf.writestr(f"{api_key}/SKILL.md", prompt_text)

        # 资源文件 — 保持原始目录结构（scripts/ / references/ / knowledge/）
        for path, content, content_type in resource_rows:
            # path 已经是相对路径（如 "scripts/main.py", "references/meddic-scoring.md"）
            file_path = f"{api_key}/{path}"
            zf.writestr(file_path, content or "")

    buf.seek(0)

    filename = f"{api_key}_v{skill.current_version}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ═══════════════════════════════════════════════════════════
# 版本管理
# ═══════════════════════════════════════════════════════════

@router.get("/{api_key}/versions")
async def list_versions(api_key: str, tenant_id: int = Query(0)):
    """获取 Skill 的版本历史列表（按时间倒序）

    返回所有已发布的版本快照，标记当前生效版本。
    """
    service = get_version_service()
    try:
        versions = service.list_versions(api_key, tenant_id=tenant_id)
        return {
            "skill_api_key": api_key,
            "total": len(versions),
            "versions": versions,
        }
    except SkillVersionError as e:
        status = 404 if e.code == "NOT_FOUND" else 400
        raise HTTPException(status_code=status, detail={"message": str(e), "code": e.code})


@router.get("/{api_key}/versions/diff")
async def diff_versions(
    api_key: str,
    base_version: str = Query(..., description="基准版本号（旧版本）"),
    target_version: str = Query(..., description="目标版本号（新版本）"),
    tenant_id: int = Query(0),
):
    """对比两个版本的差异

    返回字段级差异列表和 prompt 文本的 unified diff。

    示例：GET /api/skills/my-skill/versions/diff?base_version=1.0.0&target_version=1.1.0
    """
    service = get_version_service()
    try:
        result = service.diff_versions(
            api_key, base_version, target_version, tenant_id=tenant_id
        )
        return {
            "skill_api_key": result.skill_api_key,
            "base_version": result.base_version,
            "target_version": result.target_version,
            "has_changes": result.has_changes,
            "summary": result.summary,
            "field_diffs": [
                {
                    "field": d.field,
                    "field_label": d.field_label,
                    "old_value": d.old_value,
                    "new_value": d.new_value,
                    "diff_type": d.diff_type,
                }
                for d in result.field_diffs
            ],
            "prompt_diff": result.prompt_diff,
            "prompt_old": result.prompt_old,
            "prompt_new": result.prompt_new,
            "resource_diffs": result.resource_diffs,
        }
    except SkillVersionError as e:
        status = 404 if "NOT_FOUND" in e.code else 400
        raise HTTPException(status_code=status, detail={"message": str(e), "code": e.code})


@router.get("/{api_key}/versions/{version}")
async def get_version_detail(api_key: str, version: str, tenant_id: int = Query(0)):
    """获取指定版本的完整快照内容"""
    service = get_version_service()
    try:
        detail = service.get_version_detail(api_key, version, tenant_id=tenant_id)
        return detail
    except SkillVersionError as e:
        status = 404 if "NOT_FOUND" in e.code else 400
        raise HTTPException(status_code=status, detail={"message": str(e), "code": e.code})


@router.post("/{api_key}/versions", status_code=201)
async def publish_version(api_key: str, body: PublishVersionBody, tenant_id: int = Query(0)):
    """创建新版本

    从当前 Skill 定义复制一份快照作为新版本，同时复制关联的资源文件。
    版本号必须为 semver 格式（如 1.2.0）。
    """
    service = get_version_service()
    req = CreateVersionRequest(version=body.version, changelog=body.changelog)
    try:
        result = service.create_version(api_key, req, tenant_id=tenant_id)
        return result
    except SkillVersionError as e:
        status = 404 if e.code == "NOT_FOUND" else 400
        if e.code == "DUPLICATE_VERSION":
            status = 409
        raise HTTPException(status_code=status, detail={"message": str(e), "code": e.code})


@router.post("/{api_key}/versions/rollback")
async def rollback_version(api_key: str, body: RollbackVersionBody, tenant_id: int = Query(0)):
    """切换到指定版本（回滚）

    将目标版本设为当前生效版本，主表字段更新为该版本的快照内容。
    """
    service = get_version_service()
    try:
        result = service.switch_version(
            api_key, body.target_version, tenant_id=tenant_id
        )
        return result
    except SkillVersionError as e:
        status = 404 if "NOT_FOUND" in e.code else 400
        raise HTTPException(status_code=status, detail={"message": str(e), "code": e.code})


@router.get("/{api_key}/versions/{version}/resources")
async def get_version_resources(api_key: str, version: str, tenant_id: int = Query(0)):
    """获取指定版本的资源文件列表"""
    service = get_version_service()
    files = service.get_version_resources(api_key, version, tenant_id=tenant_id)
    return {"skill_api_key": api_key, "version": version, "files": files, "total": len(files)}


@router.get("/{api_key}/versions/{version}/resources/content")
async def get_version_resource_content(
    api_key: str,
    version: str,
    path: str = Query(..., description="资源文件路径"),
    tenant_id: int = Query(0),
):
    """读取指定版本的资源文件内容"""
    service = get_version_service()
    result = service.get_version_resource_content(api_key, version, path, tenant_id=tenant_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Resource '{path}' not found in version '{version}'")
    return {"path": path, "version": version, **result}


@router.delete("/{api_key}/versions/{version}")
async def delete_version(api_key: str, version: str, tenant_id: int = Query(0)):
    """删除历史版本（不能删除当前生效版本）

    同时删除该版本关联的资源文件。
    """
    service = get_version_service()
    try:
        result = service.delete_version(api_key, version, tenant_id=tenant_id)
        return result
    except SkillVersionError as e:
        status = 404 if "NOT_FOUND" in e.code else 400
        if e.code == "CANNOT_DELETE_CURRENT":
            status = 409
        raise HTTPException(status_code=status, detail={"message": str(e), "code": e.code})


# ═══════════════════════════════════════════════════════════
# 变更日志
# ═══════════════════════════════════════════════════════════

@router.get("/{api_key}/change-logs")
async def list_change_logs(
    api_key: str,
    tenant_id: int = Query(0),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """获取技能的变更日志列表（按时间倒序）

    记录每次版本创建、切换、回滚等操作的详细信息。
    用于审计追溯和回滚决策参考。
    """
    from src.store.pg_pool import get_conn

    offset = (page - 1) * page_size

    with get_conn() as conn:
        cur = conn.cursor()

        # 总数
        cur.execute("""
            SELECT COUNT(*) FROM ai_skill_change_log
            WHERE skill_api_key = %s AND tenant_id = %s AND delete_flg = 0
        """, (api_key, tenant_id))
        total = cur.fetchone()[0]

        # 分页查询
        cur.execute("""
            SELECT id, action, from_version, to_version, changelog,
                   change_summary, change_detail, analysis_report,
                   trigger_source, thread_id, operator_id,
                   rollback_flg, rollback_from_log,
                   created_at
            FROM ai_skill_change_log
            WHERE skill_api_key = %s AND tenant_id = %s AND delete_flg = 0
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, (api_key, tenant_id, page_size, offset))
        rows = cur.fetchall()

    items = []
    for row in rows:
        import json as _json
        detail = {}
        try:
            detail = _json.loads(row[6]) if row[6] else {}
        except Exception:
            pass

        items.append({
            "id": row[0],
            "action": row[1],
            "from_version": row[2],
            "to_version": row[3],
            "changelog": row[4],
            "change_summary": row[5],
            "change_detail": detail,
            "analysis_report": row[7],
            "trigger_source": row[8],
            "thread_id": row[9],
            "operator_id": row[10],
            "rollback": bool(row[11]),
            "rollback_from_log": row[12],
            "created_at": row[13],
        })

    return {
        "skill_api_key": api_key,
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


# ═══════════════════════════════════════════════════════════
# 序列化
# ═══════════════════════════════════════════════════════════

def _safe_json_loads(s: str, default: Any = None) -> Any:
    try:
        return json.loads(s) if s else default
    except (json.JSONDecodeError, TypeError):
        return default


def _skill_row_to_summary(row) -> dict:
    """ai_skill 行转列表摘要"""
    return {
        "api_key": row.api_key,
        "name": row.name,
        "description": row.description,
        "category": row.category,
        "tags": _safe_json_loads(row.tags, []),
        "icon": row.icon,
        "version": row.current_version,
        "enabled": bool(row.enabled_flg),
        "system": bool(row.system_flg),
        "owner": row.owner,
        "exec_count": row.exec_count,
        "success_count": row.success_count,
        "avg_duration_ms": row.avg_duration_ms,
        "tenant_id": row.tenant_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _skill_to_detail(skill, definition) -> dict:
    """ai_skill + ai_skill_definition 合并为完整详情"""
    d = _skill_row_to_summary(skill)
    ext = _safe_json_loads(skill.ext_info, {})

    # 系统预置技能为只读（如 create_skill），前端禁止编辑
    d["readonly"] = bool(skill.system_flg)

    if definition:
        d.update({
            "name": definition.name,
            "description": definition.description,
            "category": definition.category,
            "when_to_use": definition.when_to_use,
            "context": definition.context,
            "agent": definition.agent,
            "model": definition.model,
            "allowed_tools": _safe_json_loads(definition.allowed_tools, []),
            "arguments": _safe_json_loads(definition.arguments, []),
            "prompt": definition.prompt,
            "requires_confirmation": bool(definition.requires_confirmation),
            "max_tool_calls": definition.max_tool_calls,
            "timeout_ms": definition.timeout_ms,
            "output_mode": definition.output_mode,
            "component_apikey": definition.component_apikey,
            "post_output_behavior": definition.post_output_behavior,
        })
    else:
        # definition 缺失时给默认值
        d.update({
            "when_to_use": "", "context": "inline", "agent": "", "model": "",
            "allowed_tools": [], "arguments": [], "prompt": "",
            "requires_confirmation": False,
            "max_tool_calls": 20, "timeout_ms": 60000,
            "output_mode": "text", "component_apikey": "", "post_output_behavior": "silent",
        })
    d.update({
        "sort_num": skill.sort_num,
        "argument_descriptions": ext.get("argument_descriptions", {}),
        "argument_config": ext.get("argument_config", {}),
        "ext_info": ext,
    })
    return d


def _save_argument_ext(tenant_id: int, api_key: str,
                       descriptions: dict[str, str] | None,
                       config: dict[str, Any] | None) -> None:
    """将 argument_descriptions 和 argument_config 存入 ai_skill.ext_info"""
    from src.store.pg_pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT ext_info FROM ai_skill WHERE tenant_id = %s AND api_key = %s AND delete_flg = 0",
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

        cur.execute(
            "UPDATE ai_skill SET ext_info = %s WHERE tenant_id = %s AND api_key = %s AND delete_flg = 0",
            (json.dumps(ext, ensure_ascii=False), tenant_id, api_key),
        )


# 保留旧函数名兼容（manage_skill_tool.py 中有引用）
_save_argument_descriptions = lambda tid, ak, descs: _save_argument_ext(tid, ak, descs, None)


# ═══════════════════════════════════════════════════════════
# Skill 资源树 API
# ═══════════════════════════════════════════════════════════

@router.get("/{api_key}/resources")
async def get_skill_resources(api_key: str, tenant_id: int = Query(0)):
    """获取 Skill 当前版本的资源文件树"""
    from src.store.pg_pool import get_conn

    # 获取当前版本号
    skill = SkillDAO.get_by_api_key(tenant_id, api_key)
    version = skill.current_version if skill else "1.0.0"

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, parent_id, node_type, name, path, depth,
                   content_size, description, icon, sort_num, enabled_flg
            FROM ai_skill_resource
            WHERE skill_api_key = %s AND tenant_id = %s AND version = %s AND delete_flg = 0
            ORDER BY depth, sort_num, name
        """, (api_key, tenant_id, version))
        rows = cur.fetchall()

    nodes = []
    for r in rows:
        nodes.append({
            "id": str(r[0]),
            "parent_id": str(r[1]) if r[1] else None,
            "node_type": r[2],
            "name": r[3],
            "path": r[4],
            "depth": r[5],
            "content_size": r[6],
            "description": r[7],
            "icon": r[8],
            "sort_num": r[9],
            "enabled": bool(r[10]),
        })

    return {"skill_api_key": api_key, "nodes": nodes, "total": len(nodes)}


@router.get("/{api_key}/resources/content")
async def get_skill_resource_content(
    api_key: str,
    path: str = Query(..., description="资源文件路径"),
    tenant_id: int = Query(0),
):
    """读取 Skill 当前版本的资源文件内容"""
    from src.store.pg_pool import get_conn

    skill = SkillDAO.get_by_api_key(tenant_id, api_key)
    version = skill.current_version if skill else "1.0.0"

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT content, content_type, content_size, description
            FROM ai_skill_resource
            WHERE skill_api_key = %s AND path = %s AND version = %s AND node_type = 'file'
                  AND tenant_id = %s AND delete_flg = 0 AND enabled_flg = 1
        """, (api_key, path, version, tenant_id))
        row = cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Resource '{path}' not found")

    return {
        "path": path,
        "content": row[0],
        "content_type": row[1],
        "content_size": row[2],
        "description": row[3],
    }


class ResourceContentUpdate(BaseModel):
    path: str
    content: str
    tenant_id: int = 0


@router.put("/{api_key}/resources/content")
async def update_skill_resource_content(api_key: str, body: ResourceContentUpdate):
    """保存 Skill 资源文件内容"""
    import time
    from src.store.pg_pool import get_conn

    with get_conn() as conn:
        cur = conn.cursor()
        now = int(time.time() * 1000)
        content_size = len(body.content.encode("utf-8"))

        cur.execute("""
            UPDATE ai_skill_resource
            SET content = %s, content_size = %s, updated_at = %s
            WHERE skill_api_key = %s AND path = %s AND node_type = 'file'
                  AND tenant_id = %s AND delete_flg = 0
        """, (body.content, content_size, now, api_key, body.path, body.tenant_id))

        if cur.rowcount == 0:
            conn.rollback()
            raise HTTPException(status_code=404, detail=f"Resource '{body.path}' not found")

        conn.commit()

    return {"path": body.path, "content_size": content_size, "updated_at": now}


# ═══════════════════════════════════════════════════════════
# 创建资源节点（目录 / 文件）
# ═══════════════════════════════════════════════════════════

class ResourceCreateRequest(BaseModel):
    """创建目录或文件"""
    parent_path: str = Field("", description="父目录路径（空串表示根级）")
    node_type: str = Field("file", description="dir=目录, file=文件")
    name: str = Field(..., min_length=1, max_length=200, description="节点名称")
    content: str = Field("", description="文件初始内容（目录忽略）")
    content_type: str = Field("md", description="文件类型: md/yaml/json/txt")
    description: str = Field("", max_length=500)
    icon: str = Field("", max_length=50)
    sort_num: int = Field(0)
    tenant_id: int = 0


@router.post("/{api_key}/resources")
async def create_skill_resource(api_key: str, body: ResourceCreateRequest):
    """创建 Skill 资源节点（目录或文件）

    - 目录：node_type='dir'，content 忽略
    - 文件：node_type='file'，可带初始 content
    - 路径自动拼接：parent_path + '/' + name
    - 同路径不可重复（唯一索引保护）
    """
    import time
    from src.store.pg_pool import get_conn
    from src.store.snowflake import next_id

    if body.node_type not in ("dir", "file"):
        raise HTTPException(400, "node_type 必须为 'dir' 或 'file'")

    # 拼接完整路径
    if body.parent_path:
        full_path = f"{body.parent_path.rstrip('/')}/{body.name}"
    else:
        full_path = body.name

    # 计算 depth
    depth = full_path.count("/")

    now = int(time.time() * 1000)
    node_id = next_id()

    with get_conn() as conn:
        cur = conn.cursor()

        # 查找 parent_id（如果有父路径）
        parent_id = None
        if body.parent_path:
            cur.execute("""
                SELECT id FROM ai_skill_resource
                WHERE skill_api_key = %s AND path = %s AND node_type = 'dir'
                      AND tenant_id = %s AND delete_flg = 0
            """, (api_key, body.parent_path.rstrip("/"), body.tenant_id))
            parent_row = cur.fetchone()
            if parent_row is None:
                raise HTTPException(404, f"父目录 '{body.parent_path}' 不存在")
            parent_id = parent_row[0]

        # 检查路径是否已存在
        cur.execute("""
            SELECT id FROM ai_skill_resource
            WHERE skill_api_key = %s AND path = %s
                  AND tenant_id = %s AND delete_flg = 0
        """, (api_key, full_path, body.tenant_id))
        if cur.fetchone():
            raise HTTPException(409, f"路径 '{full_path}' 已存在")

        # 文件内容
        content = body.content if body.node_type == "file" else None
        content_size = len(body.content.encode("utf-8")) if body.node_type == "file" else 0

        cur.execute("""
            INSERT INTO ai_skill_resource (
                id, tenant_id, skill_api_key, parent_id, node_type, name, path, depth,
                content, content_type, content_size, description, icon, sort_num,
                enabled_flg, delete_flg, created_at, created_by, updated_at, updated_by
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                1, 0, %s, 0, %s, 0
            )
        """, (
            node_id, body.tenant_id, api_key, parent_id, body.node_type,
            body.name, full_path, depth,
            content, body.content_type, content_size,
            body.description, body.icon, body.sort_num,
            now, now,
        ))
        conn.commit()

    return {
        "id": str(node_id),
        "node_type": body.node_type,
        "name": body.name,
        "path": full_path,
        "depth": depth,
        "parent_id": str(parent_id) if parent_id else None,
        "created_at": now,
    }


# ═══════════════════════════════════════════════════════════
# 删除资源节点（目录递归删除 / 文件删除）
# ═══════════════════════════════════════════════════════════

class ResourceDeleteRequest(BaseModel):
    path: str = Field(..., description="要删除的节点路径")
    tenant_id: int = 0


@router.delete("/{api_key}/resources")
async def delete_skill_resource(api_key: str, body: ResourceDeleteRequest):
    """删除 Skill 资源节点

    - 文件：直接软删除
    - 目录：递归软删除该目录及其所有子节点（通过 path LIKE 前缀匹配）
    """
    import time
    from src.store.pg_pool import get_conn

    now = int(time.time() * 1000)

    with get_conn() as conn:
        cur = conn.cursor()

        # 确认节点存在
        cur.execute("""
            SELECT id, node_type FROM ai_skill_resource
            WHERE skill_api_key = %s AND path = %s
                  AND tenant_id = %s AND delete_flg = 0
        """, (api_key, body.path, body.tenant_id))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, f"资源 '{body.path}' 不存在")

        node_id, node_type = row[0], row[1]

        if node_type == "dir":
            # 递归软删除：该目录 + 所有子路径
            cur.execute("""
                UPDATE ai_skill_resource
                SET delete_flg = 1, updated_at = %s
                WHERE skill_api_key = %s AND tenant_id = %s AND delete_flg = 0
                      AND (path = %s OR path LIKE %s)
            """, (now, api_key, body.tenant_id, body.path, f"{body.path}/%"))
            deleted_count = cur.rowcount
        else:
            # 单文件软删除
            cur.execute("""
                UPDATE ai_skill_resource
                SET delete_flg = 1, updated_at = %s
                WHERE id = %s AND delete_flg = 0
            """, (now, node_id))
            deleted_count = cur.rowcount

        conn.commit()

    return {
        "path": body.path,
        "node_type": node_type,
        "deleted_count": deleted_count,
        "updated_at": now,
    }


# ═══════════════════════════════════════════════════════════
# 重命名 / 移动资源节点
# ═══════════════════════════════════════════════════════════

class ResourceRenameRequest(BaseModel):
    path: str = Field(..., description="当前节点路径")
    new_name: str = Field(..., min_length=1, max_length=200, description="新名称")
    tenant_id: int = 0


@router.put("/{api_key}/resources/rename")
async def rename_skill_resource(api_key: str, body: ResourceRenameRequest):
    """重命名资源节点

    - 文件：更新 name + path
    - 目录：更新自身 name + path，并级联更新所有子节点的 path 前缀
    """
    import time
    from src.store.pg_pool import get_conn

    now = int(time.time() * 1000)

    with get_conn() as conn:
        cur = conn.cursor()

        # 查找当前节点
        cur.execute("""
            SELECT id, node_type, parent_id, depth FROM ai_skill_resource
            WHERE skill_api_key = %s AND path = %s
                  AND tenant_id = %s AND delete_flg = 0
        """, (api_key, body.path, body.tenant_id))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, f"资源 '{body.path}' 不存在")

        node_id, node_type, parent_id, depth = row

        # 计算新路径
        old_path = body.path
        parts = old_path.rsplit("/", 1)
        if len(parts) == 2:
            new_path = f"{parts[0]}/{body.new_name}"
        else:
            new_path = body.new_name

        # 检查新路径是否冲突
        cur.execute("""
            SELECT id FROM ai_skill_resource
            WHERE skill_api_key = %s AND path = %s
                  AND tenant_id = %s AND delete_flg = 0
        """, (api_key, new_path, body.tenant_id))
        if cur.fetchone():
            raise HTTPException(409, f"路径 '{new_path}' 已存在")

        # 更新自身
        cur.execute("""
            UPDATE ai_skill_resource
            SET name = %s, path = %s, updated_at = %s
            WHERE id = %s
        """, (body.new_name, new_path, now, node_id))

        # 如果是目录，级联更新子节点路径
        children_updated = 0
        if node_type == "dir":
            # 查找所有子节点
            cur.execute("""
                SELECT id, path FROM ai_skill_resource
                WHERE skill_api_key = %s AND tenant_id = %s AND delete_flg = 0
                      AND path LIKE %s
            """, (api_key, body.tenant_id, f"{old_path}/%"))
            children = cur.fetchall()

            for child_id, child_path in children:
                # 替换路径前缀
                updated_child_path = new_path + child_path[len(old_path):]
                cur.execute("""
                    UPDATE ai_skill_resource
                    SET path = %s, updated_at = %s
                    WHERE id = %s
                """, (updated_child_path, now, child_id))
                children_updated += 1

        conn.commit()

    return {
        "old_path": old_path,
        "new_path": new_path,
        "new_name": body.new_name,
        "node_type": node_type,
        "children_updated": children_updated,
        "updated_at": now,
    }


# ═══════════════════════════════════════════════════════════
# 移动资源节点到新目录
# ═══════════════════════════════════════════════════════════

class ResourceMoveRequest(BaseModel):
    path: str = Field(..., description="当前节点路径")
    target_parent_path: str = Field("", description="目标父目录路径（空串表示移到根级）")
    tenant_id: int = 0


@router.put("/{api_key}/resources/move")
async def move_skill_resource(api_key: str, body: ResourceMoveRequest):
    """移动资源节点到新目录

    - 更新 parent_id、path、depth
    - 目录移动时级联更新所有子节点
    """
    import time
    from src.store.pg_pool import get_conn

    now = int(time.time() * 1000)

    with get_conn() as conn:
        cur = conn.cursor()

        # 查找当前节点
        cur.execute("""
            SELECT id, node_type, name FROM ai_skill_resource
            WHERE skill_api_key = %s AND path = %s
                  AND tenant_id = %s AND delete_flg = 0
        """, (api_key, body.path, body.tenant_id))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, f"资源 '{body.path}' 不存在")

        node_id, node_type, name = row

        # 确定目标 parent_id 和新路径
        new_parent_id = None
        if body.target_parent_path:
            cur.execute("""
                SELECT id FROM ai_skill_resource
                WHERE skill_api_key = %s AND path = %s AND node_type = 'dir'
                      AND tenant_id = %s AND delete_flg = 0
            """, (api_key, body.target_parent_path.rstrip("/"), body.tenant_id))
            parent_row = cur.fetchone()
            if parent_row is None:
                raise HTTPException(404, f"目标目录 '{body.target_parent_path}' 不存在")
            new_parent_id = parent_row[0]
            new_path = f"{body.target_parent_path.rstrip('/')}/{name}"
        else:
            new_path = name

        new_depth = new_path.count("/")
        old_path = body.path

        # 防止移动到自身子目录
        if node_type == "dir" and (new_path == old_path or new_path.startswith(f"{old_path}/")):
            raise HTTPException(400, "不能将目录移动到自身或其子目录下")

        # 检查新路径是否冲突
        cur.execute("""
            SELECT id FROM ai_skill_resource
            WHERE skill_api_key = %s AND path = %s
                  AND tenant_id = %s AND delete_flg = 0
        """, (api_key, new_path, body.tenant_id))
        if cur.fetchone():
            raise HTTPException(409, f"目标路径 '{new_path}' 已存在同名节点")

        # 更新自身
        cur.execute("""
            UPDATE ai_skill_resource
            SET parent_id = %s, path = %s, depth = %s, updated_at = %s
            WHERE id = %s
        """, (new_parent_id, new_path, new_depth, now, node_id))

        # 如果是目录，级联更新子节点
        children_updated = 0
        if node_type == "dir":
            cur.execute("""
                SELECT id, path, depth FROM ai_skill_resource
                WHERE skill_api_key = %s AND tenant_id = %s AND delete_flg = 0
                      AND path LIKE %s
            """, (api_key, body.tenant_id, f"{old_path}/%"))
            children = cur.fetchall()

            for child_id, child_path, child_depth in children:
                updated_child_path = new_path + child_path[len(old_path):]
                updated_child_depth = updated_child_path.count("/")
                cur.execute("""
                    UPDATE ai_skill_resource
                    SET path = %s, depth = %s, updated_at = %s
                    WHERE id = %s
                """, (updated_child_path, updated_child_depth, now, child_id))
                children_updated += 1

        conn.commit()

    return {
        "old_path": old_path,
        "new_path": new_path,
        "node_type": node_type,
        "new_parent_id": str(new_parent_id) if new_parent_id else None,
        "children_updated": children_updated,
        "updated_at": now,
    }
