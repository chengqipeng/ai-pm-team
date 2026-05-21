"""Skill DAO — 三表结构

ai_skill            → SkillDAO（主记录 CRUD）
ai_skill_definition → SkillDefinitionDAO（版本内容 CRUD）
ai_skill_resource   → 由 version_service 直接操作
"""
from __future__ import annotations

import dataclasses
import logging
import time
from typing import Any

from .pg_pool import get_conn
from .skill_models import SkillRow, SkillDefinitionRow

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# SkillDAO — ai_skill 主记录
# ═══════════════════════════════════════════════════════════

class SkillDAO:
    """ai_skill 表访问层"""

    _COLUMNS = (
        "id, api_key, tenant_id, name, description, owner, "
        "category, tags, icon, sort_num, current_version, "
        "enabled_flg, system_flg, exec_count, success_count, avg_duration_ms, "
        "ext_info, delete_flg, created_at, created_by, updated_at, updated_by"
    )

    @staticmethod
    def list_all(tenant_id: int | None = None,
                 keyword: str | None = None,
                 category: str | None = None,
                 enabled: bool | None = None,
                 include_platform: bool = True) -> list[SkillRow]:
        """列表查询"""
        sql = f"SELECT {SkillDAO._COLUMNS} FROM ai_skill WHERE delete_flg=0"
        params: list[Any] = []
        if tenant_id is not None:
            if include_platform:
                sql += " AND (tenant_id=%s OR tenant_id=0)"
                params.append(tenant_id)
            else:
                sql += " AND tenant_id=%s"
                params.append(tenant_id)
        if enabled is not None:
            sql += " AND enabled_flg=%s"
            params.append(1 if enabled else 0)
        if category:
            sql += " AND category=%s"
            params.append(category)
        if keyword:
            sql += " AND (api_key ILIKE %s OR name ILIKE %s OR description ILIKE %s)"
            like = f"%{keyword}%"
            params.extend([like, like, like])
        sql += " ORDER BY sort_num DESC, created_at DESC"
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return [_row_to_model(cur.description, r, SkillRow) for r in cur.fetchall()]

    @staticmethod
    def list_active(tenant_id: int | None = None,
                    include_platform: bool = True) -> list[SkillRow]:
        """列出启用的 Skill（供 SkillRegistry 加载）"""
        sql = f"SELECT {SkillDAO._COLUMNS} FROM ai_skill WHERE delete_flg=0 AND enabled_flg=1"
        params: list[Any] = []
        if tenant_id is not None:
            if include_platform:
                sql += " AND (tenant_id=%s OR tenant_id=0)"
                params.append(tenant_id)
            else:
                sql += " AND tenant_id=%s"
                params.append(tenant_id)
        sql += " ORDER BY tenant_id, api_key"
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return [_row_to_model(cur.description, r, SkillRow) for r in cur.fetchall()]

    @staticmethod
    def get_by_api_key(tenant_id: int, api_key: str,
                       include_platform: bool = True) -> SkillRow | None:
        """获取单个 Skill 主记录"""
        if include_platform:
            sql = f"SELECT {SkillDAO._COLUMNS} FROM ai_skill WHERE delete_flg=0 AND api_key=%s AND tenant_id IN (%s, 0)"
        else:
            sql = f"SELECT {SkillDAO._COLUMNS} FROM ai_skill WHERE delete_flg=0 AND api_key=%s AND tenant_id=%s"
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, (api_key, tenant_id))
            rows = [_row_to_model(cur.description, r, SkillRow) for r in cur.fetchall()]
        if not rows:
            return None
        rows.sort(key=lambda r: 0 if r.tenant_id == tenant_id else 1)
        return rows[0]

    @staticmethod
    def insert(row: SkillRow) -> None:
        """插入主记录"""
        with get_conn() as conn:
            conn.cursor().execute("""
                INSERT INTO ai_skill
                (id, api_key, tenant_id, name, description, owner,
                 category, tags, icon, sort_num, current_version,
                 enabled_flg, system_flg, exec_count, success_count, avg_duration_ms,
                 ext_info, delete_flg, created_at, created_by, updated_at, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                row.id, row.api_key, row.tenant_id, row.name, row.description, row.owner,
                row.category, row.tags, row.icon, row.sort_num, row.current_version,
                row.enabled_flg, row.system_flg, row.exec_count, row.success_count, row.avg_duration_ms,
                row.ext_info, row.delete_flg, row.created_at, row.created_by, row.updated_at, row.updated_by,
            ))

    @staticmethod
    def update_fields(tenant_id: int, api_key: str, fields: dict) -> None:
        """动态更新字段"""
        if not fields:
            return
        set_clauses = []
        params = []
        for col, val in fields.items():
            set_clauses.append(f"{col} = %s")
            params.append(val)
        params.extend([tenant_id, api_key])
        sql = f"UPDATE ai_skill SET {', '.join(set_clauses)} WHERE tenant_id=%s AND api_key=%s AND delete_flg=0"
        with get_conn() as conn:
            conn.cursor().execute(sql, params)

    @staticmethod
    def soft_delete(tenant_id: int, api_key: str, updated_by: int = 0) -> None:
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute(
                "UPDATE ai_skill SET delete_flg=1, updated_at=%s, updated_by=%s WHERE tenant_id=%s AND api_key=%s AND delete_flg=0",
                (now, updated_by, tenant_id, api_key))

    @staticmethod
    def incr_exec_count(tenant_id: int, api_key: str, success: bool, duration_ms: int) -> None:
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute("""
                UPDATE ai_skill SET exec_count=exec_count+1, success_count=success_count+%s,
                    avg_duration_ms=CASE WHEN exec_count=0 THEN %s ELSE (avg_duration_ms*exec_count+%s)/(exec_count+1) END,
                    updated_at=%s
                WHERE (tenant_id=%s OR tenant_id=0) AND api_key=%s AND delete_flg=0
            """, (1 if success else 0, duration_ms, duration_ms, now, tenant_id, api_key))


# ═══════════════════════════════════════════════════════════
# SkillDefinitionDAO — ai_skill_definition 版本内容
# ═══════════════════════════════════════════════════════════

class SkillDefinitionDAO:
    """ai_skill_definition 表访问层（每个版本一行）"""

    _COLUMNS = (
        "id, skill_api_key, tenant_id, version, name, description, changelog, "
        "when_to_use, category, context, agent, model, allowed_tools, arguments, prompt, "
        "risk_level, requires_confirmation, max_tool_calls, timeout_ms, "
        "output_mode, component_apikey, post_output_behavior, "
        "published_by, delete_flg, created_at, created_by, updated_at, updated_by"
    )

    @staticmethod
    def get_by_version(tenant_id: int, skill_api_key: str, version: str,
                       include_platform: bool = True) -> SkillDefinitionRow | None:
        """获取指定版本"""
        sql = f"SELECT {SkillDefinitionDAO._COLUMNS} FROM ai_skill_definition WHERE delete_flg=0 AND skill_api_key=%s AND version=%s"
        params: list[Any] = [skill_api_key, version]
        if include_platform:
            sql += " AND tenant_id IN (%s, 0)"
            params.append(tenant_id)
        else:
            sql += " AND tenant_id=%s"
            params.append(tenant_id)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
        if not rows:
            return None
        return _row_to_model(cur.description, rows[0], SkillDefinitionRow)

    @staticmethod
    def list_versions(tenant_id: int, skill_api_key: str,
                      include_platform: bool = True) -> list[SkillDefinitionRow]:
        """列出某 Skill 的所有版本（按时间倒序）"""
        sql = f"SELECT {SkillDefinitionDAO._COLUMNS} FROM ai_skill_definition WHERE delete_flg=0 AND skill_api_key=%s"
        params: list[Any] = [skill_api_key]
        if include_platform:
            sql += " AND tenant_id IN (%s, 0)"
            params.append(tenant_id)
        else:
            sql += " AND tenant_id=%s"
            params.append(tenant_id)
        sql += " ORDER BY created_at DESC"
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return [_row_to_model(cur.description, r, SkillDefinitionRow) for r in cur.fetchall()]

    @staticmethod
    def insert(row: SkillDefinitionRow) -> None:
        """插入版本"""
        with get_conn() as conn:
            conn.cursor().execute("""
                INSERT INTO ai_skill_definition
                (id, skill_api_key, tenant_id, version, name, description, changelog,
                 when_to_use, category, context, agent, model, allowed_tools, arguments, prompt,
                 risk_level, requires_confirmation, max_tool_calls, timeout_ms,
                 output_mode, component_apikey, post_output_behavior,
                 published_by, delete_flg, created_at, created_by, updated_at, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, skill_api_key, version) WHERE delete_flg = 0
                DO NOTHING
            """, (
                row.id, row.skill_api_key, row.tenant_id, row.version,
                row.name, row.description, row.changelog,
                row.when_to_use, row.category, row.context, row.agent, row.model,
                row.allowed_tools, row.arguments, row.prompt,
                row.risk_level, row.requires_confirmation, row.max_tool_calls, row.timeout_ms,
                row.output_mode, row.component_apikey, row.post_output_behavior,
                row.published_by, row.delete_flg, row.created_at, row.created_by,
                row.updated_at, row.updated_by,
            ))

    @staticmethod
    def soft_delete(tenant_id: int, skill_api_key: str, version: str,
                    updated_by: int = 0) -> None:
        """软删除指定版本"""
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute(
                "UPDATE ai_skill_definition SET delete_flg=1, updated_at=%s, updated_by=%s "
                "WHERE tenant_id=%s AND skill_api_key=%s AND version=%s AND delete_flg=0",
                (now, updated_by, tenant_id, skill_api_key, version))

    @staticmethod
    def soft_delete_all(tenant_id: int, skill_api_key: str, updated_by: int = 0) -> None:
        """软删除某 Skill 的所有版本"""
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute(
                "UPDATE ai_skill_definition SET delete_flg=1, updated_at=%s, updated_by=%s "
                "WHERE tenant_id=%s AND skill_api_key=%s AND delete_flg=0",
                (now, updated_by, tenant_id, skill_api_key))


# ═══════════════════════════════════════════════════════════
# 兼容旧引用（SkillVersionDAO → SkillDefinitionDAO）
# ═══════════════════════════════════════════════════════════

SkillVersionDAO = SkillDefinitionDAO


# ═══════════════════════════════════════════════════════════
# 行 → dataclass 映射
# ═══════════════════════════════════════════════════════════

def _row_to_model(desc, row, cls):
    col_names = [d[0] for d in desc]
    field_names = {f.name for f in dataclasses.fields(cls)}
    kwargs = {}
    for i, name in enumerate(col_names):
        if name in field_names:
            kwargs[name] = row[i]
    return cls(**kwargs)
