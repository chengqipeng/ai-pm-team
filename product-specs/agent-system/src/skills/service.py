"""Skill 管理业务逻辑层

职责：
- 参数校验 + 业务规则
- 启用/禁用控制
- CRUD 操作
- 热加载通知（启用/禁用后刷新 SkillRegistry）
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from src.store.skill_dao import SkillDefinitionDAO
from src.store.skill_models import SkillDefinitionRow
from src.store.snowflake import next_id

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════

@dataclass
class SkillCreateRequest:
    api_key: str
    name: str
    description: str
    prompt: str
    when_to_use: str = ""
    category: str = ""
    tags: list[str] | None = None
    context: str = "inline"
    agent: str = ""
    model: str = ""
    allowed_tools: list[str] | None = None
    arguments: list[str] | None = None
    risk_level: str = "read_only"
    requires_confirmation: bool = False
    max_tool_calls: int = 20
    timeout_ms: int = 60000
    owner: str = ""
    icon: str = ""
    sort_num: int = 0


@dataclass
class SkillUpdateRequest:
    name: str | None = None
    description: str | None = None
    prompt: str | None = None
    when_to_use: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    context: str | None = None
    agent: str | None = None
    model: str | None = None
    allowed_tools: list[str] | None = None
    arguments: list[str] | None = None
    risk_level: str | None = None
    requires_confirmation: bool | None = None
    max_tool_calls: int | None = None
    timeout_ms: int | None = None
    owner: str | None = None
    icon: str | None = None
    sort_num: int | None = None
    output_mode: str | None = None
    component_apikey: str | None = None


# ═══════════════════════════════════════════════════════════
# 异常
# ═══════════════════════════════════════════════════════════

class SkillServiceError(Exception):
    def __init__(self, message: str, code: str = "SKILL_ERROR"):
        super().__init__(message)
        self.code = code


# ═══════════════════════════════════════════════════════════
# SkillService
# ═══════════════════════════════════════════════════════════

class SkillService:
    """Skill 管理业务逻辑层"""

    def __init__(self, skill_registry: Any = None):
        self._skill_registry = skill_registry

    # ── 创建 ──

    def create(self, req: SkillCreateRequest, tenant_id: int = 0, user_id: int = 0) -> dict:
        """创建新 Skill"""
        # 校验
        self._validate_api_key(req.api_key)
        self._validate_required(req)
        self._validate_prompt_arguments(req.prompt, req.arguments or [])
        self._validate_context(req.context)
        self._validate_risk_level(req.risk_level)

        # 检查 api_key 唯一性
        existing = SkillDefinitionDAO.get_by_api_key(tenant_id, req.api_key, include_platform=False)
        if existing is not None:
            raise SkillServiceError(
                f"api_key '{req.api_key}' 已存在", code="DUPLICATE_API_KEY"
            )

        now = int(time.time() * 1000)
        row = SkillDefinitionRow(
            id=next_id(),
            api_key=req.api_key,
            tenant_id=tenant_id,
            name=req.name,
            description=req.description,
            when_to_use=req.when_to_use,
            owner=req.owner,
            context=req.context,
            agent=req.agent,
            model=req.model,
            allowed_tools=json.dumps(req.allowed_tools or [], ensure_ascii=False),
            arguments=json.dumps(req.arguments or [], ensure_ascii=False),
            prompt=req.prompt,
            risk_level=req.risk_level,
            requires_confirmation=1 if req.requires_confirmation else 0,
            max_tool_calls=req.max_tool_calls,
            timeout_ms=req.timeout_ms,
            idempotent_flg=1,
            version="1.0.0",
            status="published",  # 兼容旧字段
            published_at=now,
            created_at=now,
            created_by=user_id,
            updated_at=now,
            updated_by=user_id,
        )

        # 新增字段通过 ext 方式处理（DAO upsert 会写入）
        # 由于 DAO 目前不支持新字段，我们用扩展方式写入
        SkillDefinitionDAO.upsert(row)

        # 写入新增字段
        self._update_extra_fields(tenant_id, req.api_key, {
            "category": req.category,
            "tags": json.dumps(req.tags or [], ensure_ascii=False),
            "icon": req.icon,
            "sort_num": req.sort_num,
            "enabled_flg": 1,
        })

        # 热加载
        self._reload_registry(tenant_id)

        logger.info("Skill 创建成功: api_key=%s, tenant=%d", req.api_key, tenant_id)
        return self._get_detail(tenant_id, req.api_key)

    # ── 编辑 ──

    def update(self, api_key: str, req: SkillUpdateRequest,
               tenant_id: int = 0, user_id: int = 0) -> dict:
        """编辑 Skill（任何状态都可编辑）"""
        existing = SkillDefinitionDAO.get_by_api_key(tenant_id, api_key)
        if existing is None:
            raise SkillServiceError(f"Skill '{api_key}' 不存在", code="NOT_FOUND")

        # 校验
        if req.context is not None:
            self._validate_context(req.context)
        if req.risk_level is not None:
            self._validate_risk_level(req.risk_level)

        # 如果同时更新了 prompt 和 arguments，校验占位符
        prompt = req.prompt if req.prompt is not None else existing.prompt
        arguments = req.arguments if req.arguments is not None else json.loads(existing.arguments or "[]")
        if req.prompt is not None or req.arguments is not None:
            self._validate_prompt_arguments(prompt, arguments)

        # 构建更新字段
        now = int(time.time() * 1000)
        updates: dict[str, Any] = {"updated_at": now, "updated_by": user_id}

        if req.name is not None:
            updates["name"] = req.name
        if req.description is not None:
            updates["description"] = req.description
        if req.prompt is not None:
            updates["prompt"] = req.prompt
        if req.when_to_use is not None:
            updates["when_to_use"] = req.when_to_use
        if req.context is not None:
            updates["context"] = req.context
        if req.agent is not None:
            updates["agent"] = req.agent
        if req.model is not None:
            updates["model"] = req.model
        if req.allowed_tools is not None:
            updates["allowed_tools"] = json.dumps(req.allowed_tools, ensure_ascii=False)
        if req.arguments is not None:
            updates["arguments"] = json.dumps(req.arguments, ensure_ascii=False)
        if req.risk_level is not None:
            updates["risk_level"] = req.risk_level
        if req.requires_confirmation is not None:
            updates["requires_confirmation"] = 1 if req.requires_confirmation else 0
        if req.max_tool_calls is not None:
            updates["max_tool_calls"] = req.max_tool_calls
        if req.timeout_ms is not None:
            updates["timeout_ms"] = req.timeout_ms
        if req.owner is not None:
            updates["owner"] = req.owner

        # 主表字段更新
        if len(updates) > 2:  # 除了 updated_at/updated_by 外有其他字段
            SkillDefinitionDAO.update_fields(tenant_id, api_key, updates)

        # 扩展字段更新
        extra_updates = {}
        if req.category is not None:
            extra_updates["category"] = req.category
        if req.tags is not None:
            extra_updates["tags"] = json.dumps(req.tags, ensure_ascii=False)
        if req.icon is not None:
            extra_updates["icon"] = req.icon
        if req.sort_num is not None:
            extra_updates["sort_num"] = req.sort_num
        if req.output_mode is not None:
            extra_updates["output_mode"] = req.output_mode
        if req.component_apikey is not None:
            extra_updates["component_apikey"] = req.component_apikey
        if extra_updates:
            self._update_extra_fields(tenant_id, api_key, extra_updates)

        # output_mode 变更时清除文档类 Skill 缓存
        if req.output_mode is not None:
            self._invalidate_document_skills_cache()

        # 热加载
        self._reload_registry(tenant_id)

        logger.info("Skill 更新成功: api_key=%s", api_key)
        return self._get_detail(tenant_id, api_key)

    # ── 启用/禁用 ──

    def toggle(self, api_key: str, enabled: bool,
               tenant_id: int = 0, user_id: int = 0) -> dict:
        """启用或禁用 Skill"""
        existing = SkillDefinitionDAO.get_by_api_key(tenant_id, api_key)
        if existing is None:
            raise SkillServiceError(f"Skill '{api_key}' 不存在", code="NOT_FOUND")

        now = int(time.time() * 1000)
        self._update_extra_fields(tenant_id, api_key, {
            "enabled_flg": 1 if enabled else 0,
        })
        SkillDefinitionDAO.update_fields(tenant_id, api_key, {
            "updated_at": now,
            "updated_by": user_id,
            # 兼容旧 status 字段
            "status": "published" if enabled else "deprecated",
        })

        # 热加载
        self._reload_registry(tenant_id)

        action = "启用" if enabled else "禁用"
        logger.info("Skill %s: api_key=%s", action, api_key)
        return self._get_detail(tenant_id, api_key)

    # ── 克隆 ──

    def clone(self, api_key: str, new_api_key: str,
              tenant_id: int = 0, user_id: int = 0) -> dict:
        """克隆 Skill"""
        self._validate_api_key(new_api_key)

        existing = SkillDefinitionDAO.get_by_api_key(tenant_id, api_key)
        if existing is None:
            raise SkillServiceError(f"Skill '{api_key}' 不存在", code="NOT_FOUND")

        # 检查新 api_key 唯一性
        dup = SkillDefinitionDAO.get_by_api_key(tenant_id, new_api_key, include_platform=False)
        if dup is not None:
            raise SkillServiceError(
                f"api_key '{new_api_key}' 已存在", code="DUPLICATE_API_KEY"
            )

        now = int(time.time() * 1000)
        row = SkillDefinitionRow(
            id=next_id(),
            api_key=new_api_key,
            tenant_id=tenant_id,
            name=f"{existing.name} (副本)",
            description=existing.description,
            when_to_use=existing.when_to_use,
            owner=existing.owner,
            context=existing.context,
            agent=existing.agent,
            model=existing.model,
            allowed_tools=existing.allowed_tools,
            arguments=existing.arguments,
            prompt=existing.prompt,
            risk_level=existing.risk_level,
            requires_confirmation=existing.requires_confirmation,
            max_tool_calls=existing.max_tool_calls,
            timeout_ms=existing.timeout_ms,
            idempotent_flg=existing.idempotent_flg,
            version="1.0.0",
            status="published",
            published_at=now,
            created_at=now,
            created_by=user_id,
            updated_at=now,
            updated_by=user_id,
        )
        SkillDefinitionDAO.upsert(row)

        # 克隆扩展字段
        self._update_extra_fields(tenant_id, new_api_key, {
            "category": getattr(existing, "category", ""),
            "tags": getattr(existing, "tags", "[]"),
            "icon": getattr(existing, "icon", ""),
            "sort_num": getattr(existing, "sort_num", 0),
            "enabled_flg": 0,  # 克隆后默认禁用
        })

        logger.info("Skill 克隆成功: %s → %s", api_key, new_api_key)
        return self._get_detail(tenant_id, new_api_key)

    # ── 删除 ──

    def delete(self, api_key: str, tenant_id: int = 0, user_id: int = 0) -> None:
        """软删除 Skill"""
        existing = SkillDefinitionDAO.get_by_api_key(tenant_id, api_key)
        if existing is None:
            raise SkillServiceError(f"Skill '{api_key}' 不存在", code="NOT_FOUND")

        SkillDefinitionDAO.soft_delete(tenant_id, api_key, updated_by=user_id)

        # 热加载
        self._reload_registry(tenant_id)

        logger.info("Skill 删除成功: api_key=%s", api_key)

    # ── 测试执行 ──

    async def test_execute(self, api_key: str, arguments: dict[str, str],
                           tenant_id: int = 0) -> str:
        """测试执行 Skill（dry-run，不记录执行日志）"""
        from src.skills.base import SkillDefinition, SkillExecutionError

        row = SkillDefinitionDAO.get_by_api_key(tenant_id, api_key)
        if row is None:
            raise SkillServiceError(f"Skill '{api_key}' 不存在", code="NOT_FOUND")

        skill = SkillDefinition.from_db_row(row)
        formatted_prompt = skill.format_prompt(arguments)

        if skill.context == "inline":
            # inline 模式直接返回格式化后的 prompt
            return formatted_prompt
        else:
            # fork 模式返回将要发送给子 Agent 的指令预览
            parts = [f"请执行技能 '{skill.name}': {skill.description}"]
            if arguments:
                args_str = ", ".join(f"{k}={v}" for k, v in arguments.items())
                parts.append(f"参数: {args_str}")
            if formatted_prompt:
                parts.append(f"\n{formatted_prompt}")
            return "\n".join(parts)

    # ── 热加载 ──

    def _reload_registry(self, tenant_id: int) -> int:
        """刷新 SkillRegistry 内存"""
        if self._skill_registry is None:
            return 0
        try:
            count = self._skill_registry.load_from_db(tenant_id=tenant_id)
            logger.info("SkillRegistry 热加载完成: %d 个技能", count)
            return count
        except Exception as e:
            logger.warning("SkillRegistry 热加载失败: %s", e)
            return 0

    @staticmethod
    def _invalidate_document_skills_cache() -> None:
        """清除 server.py 中的 _document_skills_cache（output_mode 变更时调用）"""
        try:
            import sys
            # server 模块在 sys.modules 中（因为是入口模块）
            srv = sys.modules.get("server") or sys.modules.get("__main__")
            if srv and hasattr(srv, "_document_skills_cache"):
                srv._document_skills_cache = None
                logger.info("已清除 _document_skills_cache")
        except Exception as e:
            logger.warning("清除 _document_skills_cache 失败: %s", e)

    # ── 内部方法 ──

    def _get_detail(self, tenant_id: int, api_key: str) -> dict:
        """获取 Skill 详情（含扩展字段）"""
        row = SkillDefinitionDAO.get_by_api_key(tenant_id, api_key)
        if row is None:
            return {}
        return self._row_to_detail(row)

    @staticmethod
    def _row_to_detail(row: SkillDefinitionRow) -> dict:
        """行转详情字典"""
        def _safe_json(s, default=None):
            try:
                return json.loads(s) if s else default
            except (json.JSONDecodeError, TypeError):
                return default

        return {
            "api_key": row.api_key,
            "name": row.name,
            "description": row.description,
            "when_to_use": row.when_to_use,
            "category": getattr(row, "category", ""),
            "tags": _safe_json(getattr(row, "tags", "[]"), []),
            "icon": getattr(row, "icon", ""),
            "context": row.context,
            "agent": row.agent,
            "model": row.model,
            "allowed_tools": _safe_json(row.allowed_tools, []),
            "arguments": _safe_json(row.arguments, []),
            "prompt": row.prompt,
            "risk_level": row.risk_level,
            "requires_confirmation": bool(row.requires_confirmation),
            "max_tool_calls": row.max_tool_calls,
            "timeout_ms": row.timeout_ms,
            "version": row.version,
            "enabled": bool(getattr(row, "enabled_flg", 1)),
            "owner": row.owner,
            "sort_num": getattr(row, "sort_num", 0),
            "output_mode": getattr(row, "output_mode", "text"),
            "component_apikey": getattr(row, "component_apikey", ""),
            "exec_count": row.exec_count,
            "success_count": row.success_count,
            "avg_duration_ms": row.avg_duration_ms,
            "tenant_id": row.tenant_id,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _validate_api_key(api_key: str) -> None:
        if not api_key:
            raise SkillServiceError("api_key 不能为空", code="INVALID_API_KEY")
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_-]{1,98}$', api_key):
            raise SkillServiceError(
                "api_key 必须以字母开头，只能包含字母、数字、下划线、连字符，长度 2-99",
                code="INVALID_API_KEY",
            )

    @staticmethod
    def _validate_required(req: SkillCreateRequest) -> None:
        if not req.description:
            raise SkillServiceError("description 不能为空", code="MISSING_DESCRIPTION")
        if not req.prompt:
            raise SkillServiceError("prompt 不能为空", code="MISSING_PROMPT")
        if not req.name:
            raise SkillServiceError("name 不能为空", code="MISSING_NAME")

    @staticmethod
    def _validate_prompt_arguments(prompt: str, arguments: list[str]) -> None:
        """校验 prompt 中的占位符与 arguments 列表一致"""
        for arg in arguments:
            if f"{{{arg}}}" not in prompt:
                raise SkillServiceError(
                    f"参数 '{arg}' 在 prompt 中未找到对应的 {{{arg}}} 占位符",
                    code="ARGUMENT_NOT_IN_PROMPT",
                )

    @staticmethod
    def _validate_context(context: str) -> None:
        if context not in ("inline", "fork"):
            raise SkillServiceError(
                f"context 必须是 'inline' 或 'fork'，当前值: '{context}'",
                code="INVALID_CONTEXT",
            )

    @staticmethod
    def _validate_risk_level(risk_level: str) -> None:
        if risk_level not in ("read_only", "mutating", "destructive"):
            raise SkillServiceError(
                f"risk_level 必须是 'read_only'/'mutating'/'destructive'，当前值: '{risk_level}'",
                code="INVALID_RISK_LEVEL",
            )

    @staticmethod
    def _update_extra_fields(tenant_id: int, api_key: str, fields: dict) -> None:
        """更新扩展字段（category/tags/icon/sort_num/enabled_flg）"""
        from src.store.pg_pool import get_conn

        set_clauses = []
        params = []
        for col, val in fields.items():
            set_clauses.append(f"{col} = %s")
            params.append(val)

        if not set_clauses:
            return

        params.extend([tenant_id, api_key])
        sql = (
            f"UPDATE ai_skill_definition SET {', '.join(set_clauses)} "
            f"WHERE tenant_id = %s AND api_key = %s AND delete_flg = 0"
        )
        with get_conn() as conn:
            conn.cursor().execute(sql, params)
