"""Skill 管理业务逻辑层（三表结构）

操作对象：
  ai_skill            → 主记录（CRUD、启用/禁用、统计）
  ai_skill_definition → 当前版本内容（编辑时更新当前版本的 definition）
  ai_skill_resource   → 当前版本资源文件
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from src.store.skill_dao import SkillDAO, SkillDefinitionDAO
from src.store.skill_models import SkillRow, SkillDefinitionRow
from src.store.snowflake import next_id

logger = logging.getLogger(__name__)


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
    requires_confirmation: bool = False
    max_tool_calls: int = 20
    timeout_ms: int = 60000
    owner: str = ""
    icon: str = ""
    sort_num: int = 0
    output_mode: str = "text"


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
    requires_confirmation: bool | None = None
    max_tool_calls: int | None = None
    timeout_ms: int | None = None
    owner: str | None = None
    icon: str | None = None
    sort_num: int | None = None
    output_mode: str | None = None
    component_apikey: str | None = None


class SkillServiceError(Exception):
    def __init__(self, message: str, code: str = "SKILL_ERROR"):
        super().__init__(message)
        self.code = code


class SkillService:
    """Skill 管理业务逻辑层"""

    def __init__(self, skill_registry: Any = None):
        self._skill_registry = skill_registry

    # ── 创建 ──

    def create(self, req: SkillCreateRequest, tenant_id: int = 0, user_id: int = 0) -> dict:
        """创建新 Skill（同时创建主记录 + 初始版本 definition）"""
        self._validate_api_key(req.api_key)
        self._validate_required(req)
        self._validate_prompt_arguments(req.prompt, req.arguments or [])
        self._validate_context(req.context)

        if SkillDAO.get_by_api_key(tenant_id, req.api_key, include_platform=False):
            raise SkillServiceError(f"api_key '{req.api_key}' 已存在", code="DUPLICATE_API_KEY")

        now = int(time.time() * 1000)
        version = "1.0.0"

        # 1. 创建 ai_skill 主记录
        skill_row = SkillRow(
            id=next_id(), api_key=req.api_key, tenant_id=tenant_id,
            name=req.name, description=req.description, owner=req.owner,
            category=req.category, tags=json.dumps(req.tags or [], ensure_ascii=False),
            icon=req.icon, sort_num=req.sort_num, current_version=version,
            enabled_flg=1, system_flg=0,
            created_at=now, created_by=user_id, updated_at=now, updated_by=user_id,
        )
        SkillDAO.insert(skill_row)

        # 2. 创建 ai_skill_definition 初始版本
        def_row = SkillDefinitionRow(
            id=next_id(), skill_api_key=req.api_key, tenant_id=tenant_id,
            version=version, name=req.name, description=req.description,
            changelog="初始版本", category=req.category,
            when_to_use=req.when_to_use, context=req.context,
            agent=req.agent, model=req.model,
            allowed_tools=json.dumps(req.allowed_tools or [], ensure_ascii=False),
            arguments=json.dumps(req.arguments or [], ensure_ascii=False),
            prompt=req.prompt,
            requires_confirmation=1 if req.requires_confirmation else 0,
            max_tool_calls=req.max_tool_calls, timeout_ms=req.timeout_ms,
            output_mode=req.output_mode,
            published_by=user_id,
            created_at=now, created_by=user_id, updated_at=now, updated_by=user_id,
        )
        SkillDefinitionDAO.insert(def_row)

        self._reload_registry(tenant_id)
        logger.info("Skill 创建: api_key=%s", req.api_key)
        return self._get_detail(tenant_id, req.api_key)

    # ── 编辑 ──

    def update(self, api_key: str, req: SkillUpdateRequest,
               tenant_id: int = 0, user_id: int = 0) -> dict:
        """编辑 Skill（更新主记录 + 当前版本 definition）"""
        skill = SkillDAO.get_by_api_key(tenant_id, api_key)
        if skill is None:
            raise SkillServiceError(f"Skill '{api_key}' 不存在", code="NOT_FOUND")

        cur_def = SkillDefinitionDAO.get_by_version(tenant_id, api_key, skill.current_version)

        if req.context is not None:
            self._validate_context(req.context)

        # 校验 prompt + arguments
        prompt = req.prompt if req.prompt is not None else (cur_def.prompt if cur_def else "")
        arguments = req.arguments if req.arguments is not None else (
            json.loads(cur_def.arguments or "[]") if cur_def else [])
        if req.prompt is not None or req.arguments is not None:
            self._validate_prompt_arguments(prompt, arguments)

        now = int(time.time() * 1000)

        # 更新 ai_skill 主记录字段
        skill_updates: dict[str, Any] = {"updated_at": now, "updated_by": user_id}
        if req.name is not None:
            skill_updates["name"] = req.name
        if req.description is not None:
            skill_updates["description"] = req.description
        if req.owner is not None:
            skill_updates["owner"] = req.owner
        if req.category is not None:
            skill_updates["category"] = req.category
        if req.tags is not None:
            skill_updates["tags"] = json.dumps(req.tags, ensure_ascii=False)
        if req.icon is not None:
            skill_updates["icon"] = req.icon
        if req.sort_num is not None:
            skill_updates["sort_num"] = req.sort_num
        SkillDAO.update_fields(tenant_id, api_key, skill_updates)

        # 更新 ai_skill_definition 当前版本
        if cur_def:
            def_updates: dict[str, Any] = {"updated_at": now, "updated_by": user_id}
            if req.name is not None:
                def_updates["name"] = req.name
            if req.description is not None:
                def_updates["description"] = req.description
            if req.category is not None:
                def_updates["category"] = req.category
            if req.prompt is not None:
                def_updates["prompt"] = req.prompt
            if req.when_to_use is not None:
                def_updates["when_to_use"] = req.when_to_use
            if req.context is not None:
                def_updates["context"] = req.context
            if req.agent is not None:
                def_updates["agent"] = req.agent
            if req.model is not None:
                def_updates["model"] = req.model
            if req.allowed_tools is not None:
                def_updates["allowed_tools"] = json.dumps(req.allowed_tools, ensure_ascii=False)
            if req.arguments is not None:
                def_updates["arguments"] = json.dumps(req.arguments, ensure_ascii=False)
            if req.requires_confirmation is not None:
                def_updates["requires_confirmation"] = 1 if req.requires_confirmation else 0
            if req.max_tool_calls is not None:
                def_updates["max_tool_calls"] = req.max_tool_calls
            if req.timeout_ms is not None:
                def_updates["timeout_ms"] = req.timeout_ms
            if req.output_mode is not None:
                def_updates["output_mode"] = req.output_mode
            if req.component_apikey is not None:
                def_updates["component_apikey"] = req.component_apikey
            self._update_definition_fields(tenant_id, api_key, skill.current_version, def_updates)

        self._reload_registry(tenant_id)
        logger.info("Skill 更新: api_key=%s", api_key)
        return self._get_detail(tenant_id, api_key)

    # ── 启用/禁用 ──

    def toggle(self, api_key: str, enabled: bool,
               tenant_id: int = 0, user_id: int = 0) -> dict:
        skill = SkillDAO.get_by_api_key(tenant_id, api_key)
        if skill is None:
            raise SkillServiceError(f"Skill '{api_key}' 不存在", code="NOT_FOUND")
        now = int(time.time() * 1000)
        SkillDAO.update_fields(tenant_id, api_key, {
            "enabled_flg": 1 if enabled else 0,
            "updated_at": now, "updated_by": user_id,
        })
        self._reload_registry(tenant_id)
        return self._get_detail(tenant_id, api_key)

    # ── 克隆 ──

    def clone(self, api_key: str, new_api_key: str,
              tenant_id: int = 0, user_id: int = 0) -> dict:
        self._validate_api_key(new_api_key)
        skill = SkillDAO.get_by_api_key(tenant_id, api_key)
        if skill is None:
            raise SkillServiceError(f"Skill '{api_key}' 不存在", code="NOT_FOUND")
        if SkillDAO.get_by_api_key(tenant_id, new_api_key, include_platform=False):
            raise SkillServiceError(f"api_key '{new_api_key}' 已存在", code="DUPLICATE_API_KEY")

        now = int(time.time() * 1000)
        version = "1.0.0"

        # 克隆主记录
        new_skill = SkillRow(
            id=next_id(), api_key=new_api_key, tenant_id=tenant_id,
            name=f"{skill.name} (副本)", description=skill.description, owner=skill.owner,
            category=skill.category, tags=skill.tags, icon=skill.icon,
            sort_num=skill.sort_num, current_version=version,
            enabled_flg=0, system_flg=0,
            created_at=now, created_by=user_id, updated_at=now, updated_by=user_id,
        )
        SkillDAO.insert(new_skill)

        # 克隆当前版本 definition
        cur_def = SkillDefinitionDAO.get_by_version(tenant_id, api_key, skill.current_version)
        if cur_def:
            new_def = SkillDefinitionRow(
                id=next_id(), skill_api_key=new_api_key, tenant_id=tenant_id,
                version=version, name=new_skill.name, description=skill.description,
                changelog="从 " + api_key + " 克隆", category=cur_def.category,
                when_to_use=cur_def.when_to_use, context=cur_def.context,
                agent=cur_def.agent, model=cur_def.model,
                allowed_tools=cur_def.allowed_tools, arguments=cur_def.arguments,
                prompt=cur_def.prompt,
                requires_confirmation=cur_def.requires_confirmation,
                max_tool_calls=cur_def.max_tool_calls, timeout_ms=cur_def.timeout_ms,
                output_mode=cur_def.output_mode, component_apikey=cur_def.component_apikey,
                post_output_behavior=cur_def.post_output_behavior,
                published_by=user_id,
                created_at=now, created_by=user_id, updated_at=now, updated_by=user_id,
            )
            SkillDefinitionDAO.insert(new_def)

        logger.info("Skill 克隆: %s → %s", api_key, new_api_key)
        return self._get_detail(tenant_id, new_api_key)

    # ── 删除 ──

    def delete(self, api_key: str, tenant_id: int = 0, user_id: int = 0) -> None:
        skill = SkillDAO.get_by_api_key(tenant_id, api_key)
        if skill is None:
            raise SkillServiceError(f"Skill '{api_key}' 不存在", code="NOT_FOUND")
        SkillDAO.soft_delete(tenant_id, api_key, updated_by=user_id)
        SkillDefinitionDAO.soft_delete_all(tenant_id, api_key, updated_by=user_id)
        self._reload_registry(tenant_id)
        logger.info("Skill 删除: api_key=%s", api_key)

    # ── 测试执行 ──

    async def test_execute(self, api_key: str, arguments: dict[str, str],
                           tenant_id: int = 0) -> str:
        from src.skills.base import SkillDefinition
        skill = SkillDAO.get_by_api_key(tenant_id, api_key)
        if skill is None:
            raise SkillServiceError(f"Skill '{api_key}' 不存在", code="NOT_FOUND")
        cur_def = SkillDefinitionDAO.get_by_version(tenant_id, api_key, skill.current_version)
        if cur_def is None:
            raise SkillServiceError(f"当前版本定义缺失", code="NOT_FOUND")

        # 构建临时 SkillDefinition 用于格式化
        sd = SkillDefinition(
            name=api_key, description=skill.description,
            prompt=cur_def.prompt, context=cur_def.context,
            arguments=json.loads(cur_def.arguments or "[]"),
        )
        formatted = sd.format_prompt(arguments)
        if cur_def.context == "inline":
            return formatted
        parts = [f"请执行技能 '{skill.name}': {skill.description}"]
        if arguments:
            parts.append(f"参数: {', '.join(f'{k}={v}' for k, v in arguments.items())}")
        if formatted:
            parts.append(f"\n{formatted}")
        return "\n".join(parts)

    # ── 内部方法 ──

    def _reload_registry(self, tenant_id: int) -> int:
        if self._skill_registry is None:
            return 0
        try:
            count = self._skill_registry.load_from_db(tenant_id=tenant_id)
            return count
        except Exception as e:
            logger.warning("SkillRegistry 热加载失败: %s", e)
            return 0

    def _get_detail(self, tenant_id: int, api_key: str) -> dict:
        """获取完整详情（主记录 + 当前版本 definition）"""
        skill = SkillDAO.get_by_api_key(tenant_id, api_key)
        if skill is None:
            return {}
        cur_def = SkillDefinitionDAO.get_by_version(tenant_id, api_key, skill.current_version)
        return self._merge_detail(skill, cur_def)

    @staticmethod
    def _merge_detail(skill: SkillRow, definition: SkillDefinitionRow | None) -> dict:
        def _j(s, d=None):
            try: return json.loads(s) if s else d
            except: return d
        d = {
            "api_key": skill.api_key, "name": skill.name,
            "description": skill.description, "owner": skill.owner,
            "category": skill.category, "tags": _j(skill.tags, []),
            "icon": skill.icon, "sort_num": skill.sort_num,
            "version": skill.current_version,
            "enabled": bool(skill.enabled_flg), "system": bool(skill.system_flg),
            "exec_count": skill.exec_count, "success_count": skill.success_count,
            "avg_duration_ms": skill.avg_duration_ms,
            "tenant_id": skill.tenant_id,
            "created_at": skill.created_at, "updated_at": skill.updated_at,
        }
        if definition:
            d.update({
                "when_to_use": definition.when_to_use,
                "context": definition.context, "agent": definition.agent,
                "model": definition.model,
                "allowed_tools": _j(definition.allowed_tools, []),
                "arguments": _j(definition.arguments, []),
                "prompt": definition.prompt,
                "requires_confirmation": bool(definition.requires_confirmation),
                "max_tool_calls": definition.max_tool_calls,
                "timeout_ms": definition.timeout_ms,
                "output_mode": definition.output_mode,
                "component_apikey": definition.component_apikey,
            })
        return d

    @staticmethod
    def _update_definition_fields(tenant_id: int, api_key: str, version: str, fields: dict) -> None:
        """更新指定版本的 definition 字段"""
        from src.store.pg_pool import get_conn
        if not fields:
            return
        set_clauses = [f"{col} = %s" for col in fields]
        params = list(fields.values()) + [tenant_id, api_key, version]
        sql = (f"UPDATE ai_skill_definition SET {', '.join(set_clauses)} "
               f"WHERE tenant_id=%s AND skill_api_key=%s AND version=%s AND delete_flg=0")
        with get_conn() as conn:
            conn.cursor().execute(sql, params)

    @staticmethod
    def _validate_api_key(api_key: str) -> None:
        if not api_key or not re.match(r'^[a-zA-Z][a-zA-Z0-9_-]{1,98}$', api_key):
            raise SkillServiceError("api_key 格式无效", code="INVALID_API_KEY")

    @staticmethod
    def _validate_required(req: SkillCreateRequest) -> None:
        if not req.name: raise SkillServiceError("name 不能为空", code="MISSING_NAME")
        if not req.description: raise SkillServiceError("description 不能为空", code="MISSING_DESCRIPTION")
        if not req.prompt: raise SkillServiceError("prompt 不能为空", code="MISSING_PROMPT")

    # 系统保留变量名（通过 ${VAR} 语法注入，不需要在 arguments 中声明）
    _SYSTEM_VARS = frozenset({"SKILL_DIR", "SKILL_NAME"})

    @staticmethod
    def _validate_prompt_arguments(prompt: str, arguments: list[str]) -> None:
        """校验每个声明的参数在 prompt 中都有 {arg} 占位符

        特殊处理：
        - 系统变量（SKILL_DIR、SKILL_NAME）跳过校验
        - 当 prompt 中包含 ${SKILL_DIR} 时，表示有脚本执行场景，
          参数可能通过脚本命令行传入，此时放宽校验（不强制要求占位符）
        """
        # 如果 prompt 中引用了 ${SKILL_DIR}，说明是脚本执行模式，
        # 参数可能通过脚本参数传递而非直接嵌入 prompt 模板
        has_skill_dir = "${SKILL_DIR}" in prompt

        for arg in arguments:
            if arg in SkillService._SYSTEM_VARS:
                continue
            if has_skill_dir:
                # 脚本执行模式：参数可能通过命令行传入，不强制要求 {arg} 占位符
                continue
            if f"{{{arg}}}" not in prompt:
                raise SkillServiceError(
                    f"参数 '{arg}' 在 prompt 中未找到 {{{arg}}} 占位符",
                    code="ARGUMENT_NOT_IN_PROMPT"
                )

    @staticmethod
    def _validate_context(context: str) -> None:
        if context not in ("inline", "fork"):
            raise SkillServiceError(f"context 无效: '{context}'", code="INVALID_CONTEXT")
