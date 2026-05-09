"""Skill DAO — ai_skill_definition / ai_skill_version CRUD

运行时只需 `SkillDefinitionDAO.list_active` 一个方法把 DB 中的 Skill 全量读进
SkillRegistry；写入接口（insert/upsert/publish）供 SkillInstaller、SkillOptimizer、
SkillGenerator 以及运营管理 API 使用。
"""
from __future__ import annotations

import dataclasses
import logging
import time
from typing import Any

from .pg_pool import get_conn
from .skill_models import SkillDefinitionRow, SkillVersionRow

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# SkillDefinitionDAO
# ═══════════════════════════════════════════════════════════

class SkillDefinitionDAO:
    """ai_skill_definition 表访问层"""

    _ALL_COLUMNS = (
        "id, api_key, tenant_id, name, description, when_to_use, owner, "
        "context, agent, model, allowed_tools, arguments, prompt, "
        "risk_level, requires_confirmation, max_tool_calls, timeout_ms, idempotent_flg, "
        "version, status, published_at, "
        "exec_count, success_count, avg_duration_ms, ext_info, "
        "delete_flg, created_at, created_by, updated_at, updated_by"
    )

    # ── 查询 ──

    @staticmethod
    def list_active(tenant_id: int | None = None,
                     include_platform: bool = True) -> list[SkillDefinitionRow]:
        """列出 status='published' 且未删除的技能

        Args:
            tenant_id: 目标租户；None 表示读所有租户
            include_platform: 是否把 tenant_id=0 的平台级技能也纳入结果
        """
        sql = (
            f"SELECT {SkillDefinitionDAO._ALL_COLUMNS} "
            f"FROM ai_skill_definition WHERE delete_flg=0 AND status='published'"
        )
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
            return [_row_to_def(cur.description, r) for r in cur.fetchall()]

    @staticmethod
    def list_all(tenant_id: int | None = None,
                  status: str | None = None,
                  keyword: str | None = None,
                  include_platform: bool = True) -> list[SkillDefinitionRow]:
        """列表查询（供运营管理页面使用）"""
        sql = f"SELECT {SkillDefinitionDAO._ALL_COLUMNS} FROM ai_skill_definition WHERE delete_flg=0"
        params: list[Any] = []
        if tenant_id is not None:
            if include_platform:
                sql += " AND (tenant_id=%s OR tenant_id=0)"
                params.append(tenant_id)
            else:
                sql += " AND tenant_id=%s"
                params.append(tenant_id)
        if status:
            sql += " AND status=%s"
            params.append(status)
        if keyword:
            sql += " AND (api_key ILIKE %s OR name ILIKE %s OR description ILIKE %s)"
            like = f"%{keyword}%"
            params.extend([like, like, like])
        sql += " ORDER BY tenant_id, api_key"
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return [_row_to_def(cur.description, r) for r in cur.fetchall()]

    @staticmethod
    def get_by_api_key(tenant_id: int, api_key: str,
                        include_platform: bool = True) -> SkillDefinitionRow | None:
        """优先取租户自有技能；找不到时 fallback 到平台级（tenant_id=0）"""
        sql = (
            f"SELECT {SkillDefinitionDAO._ALL_COLUMNS} "
            f"FROM ai_skill_definition WHERE delete_flg=0 AND api_key=%s "
            f"AND tenant_id IN (%s, 0)" if include_platform else
            f"SELECT {SkillDefinitionDAO._ALL_COLUMNS} "
            f"FROM ai_skill_definition WHERE delete_flg=0 AND api_key=%s AND tenant_id=%s"
        )
        params = (api_key, tenant_id) if include_platform else (api_key, tenant_id)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = [_row_to_def(cur.description, r) for r in cur.fetchall()]
        if not rows:
            return None
        # 租户自有优先
        rows.sort(key=lambda r: 0 if r.tenant_id == tenant_id else 1)
        return rows[0]

    # ── 写入 ──

    @staticmethod
    def upsert(row: SkillDefinitionRow) -> None:
        """按 (tenant_id, api_key) 做 upsert；已存在时更新所有可变字段"""
        now = int(time.time() * 1000)
        row.updated_at = now
        with get_conn() as conn:
            conn.cursor().execute(
                """
                INSERT INTO ai_skill_definition
                (id, api_key, tenant_id, name, description, when_to_use, owner,
                 context, agent, model, allowed_tools, arguments, prompt,
                 risk_level, requires_confirmation, max_tool_calls, timeout_ms, idempotent_flg,
                 version, status, published_at,
                 exec_count, success_count, avg_duration_ms, ext_info,
                 delete_flg, created_at, created_by, updated_at, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0
                DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    when_to_use = EXCLUDED.when_to_use,
                    owner = EXCLUDED.owner,
                    context = EXCLUDED.context,
                    agent = EXCLUDED.agent,
                    model = EXCLUDED.model,
                    allowed_tools = EXCLUDED.allowed_tools,
                    arguments = EXCLUDED.arguments,
                    prompt = EXCLUDED.prompt,
                    risk_level = EXCLUDED.risk_level,
                    requires_confirmation = EXCLUDED.requires_confirmation,
                    max_tool_calls = EXCLUDED.max_tool_calls,
                    timeout_ms = EXCLUDED.timeout_ms,
                    idempotent_flg = EXCLUDED.idempotent_flg,
                    version = EXCLUDED.version,
                    status = EXCLUDED.status,
                    published_at = EXCLUDED.published_at,
                    ext_info = EXCLUDED.ext_info,
                    updated_at = EXCLUDED.updated_at,
                    updated_by = EXCLUDED.updated_by
                """,
                (row.id, row.api_key, row.tenant_id, row.name, row.description,
                 row.when_to_use, row.owner, row.context, row.agent, row.model,
                 row.allowed_tools, row.arguments, row.prompt,
                 row.risk_level, row.requires_confirmation, row.max_tool_calls,
                 row.timeout_ms, row.idempotent_flg,
                 row.version, row.status, row.published_at,
                 row.exec_count, row.success_count, row.avg_duration_ms, row.ext_info,
                 row.delete_flg, row.created_at, row.created_by, row.updated_at, row.updated_by)
            )
        logger.info("Skill upserted: tenant=%d api_key=%s version=%s status=%s",
                    row.tenant_id, row.api_key, row.version, row.status)

    @staticmethod
    def soft_delete(tenant_id: int, api_key: str, updated_by: int = 0) -> None:
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute(
                "UPDATE ai_skill_definition SET delete_flg=1, updated_at=%s, updated_by=%s "
                "WHERE tenant_id=%s AND api_key=%s AND delete_flg=0",
                (now, updated_by, tenant_id, api_key),
            )

    @staticmethod
    def incr_exec_count(tenant_id: int, api_key: str,
                         success: bool, duration_ms: int) -> None:
        now = int(time.time() * 1000)
        with get_conn() as conn:
            conn.cursor().execute(
                """
                UPDATE ai_skill_definition
                SET exec_count = exec_count + 1,
                    success_count = success_count + %s,
                    avg_duration_ms = CASE
                        WHEN exec_count = 0 THEN %s
                        ELSE (avg_duration_ms * exec_count + %s) / (exec_count + 1)
                    END,
                    updated_at = %s
                WHERE (tenant_id=%s OR tenant_id=0) AND api_key=%s AND delete_flg=0
                """,
                (1 if success else 0, duration_ms, duration_ms, now, tenant_id, api_key),
            )


# ═══════════════════════════════════════════════════════════
# SkillVersionDAO
# ═══════════════════════════════════════════════════════════

class SkillVersionDAO:
    _ALL_COLUMNS = (
        "id, tenant_id, skill_api_key, version, description, when_to_use, "
        "context, agent, model, allowed_tools, arguments, prompt, "
        "risk_level, requires_confirmation, max_tool_calls, timeout_ms, "
        "changelog, published_by, delete_flg, created_at, created_by, updated_at, updated_by"
    )

    @staticmethod
    def insert(row: SkillVersionRow) -> None:
        with get_conn() as conn:
            conn.cursor().execute(
                """
                INSERT INTO ai_skill_version
                (id, tenant_id, skill_api_key, version, description, when_to_use,
                 context, agent, model, allowed_tools, arguments, prompt,
                 risk_level, requires_confirmation, max_tool_calls, timeout_ms,
                 changelog, published_by,
                 delete_flg, created_at, created_by, updated_at, updated_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, skill_api_key, version) WHERE delete_flg = 0
                DO NOTHING
                """,
                (row.id, row.tenant_id, row.skill_api_key, row.version,
                 row.description, row.when_to_use, row.context, row.agent, row.model,
                 row.allowed_tools, row.arguments, row.prompt,
                 row.risk_level, row.requires_confirmation, row.max_tool_calls,
                 row.timeout_ms, row.changelog, row.published_by,
                 row.delete_flg, row.created_at, row.created_by,
                 row.updated_at, row.updated_by)
            )

    @staticmethod
    def list_by_api_key(tenant_id: int, api_key: str,
                         include_platform: bool = True) -> list[SkillVersionRow]:
        sql = (
            f"SELECT {SkillVersionDAO._ALL_COLUMNS} "
            f"FROM ai_skill_version WHERE delete_flg=0 AND skill_api_key=%s"
        )
        params: list[Any] = [api_key]
        if tenant_id is not None:
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
            return [_row_to_version(cur.description, r) for r in cur.fetchall()]


# ═══════════════════════════════════════════════════════════
# 行 → dataclass 映射
# ═══════════════════════════════════════════════════════════

def _row_to_def(desc, row) -> SkillDefinitionRow:
    return _row_to_model(desc, row, SkillDefinitionRow)


def _row_to_version(desc, row) -> SkillVersionRow:
    return _row_to_model(desc, row, SkillVersionRow)


def _row_to_model(desc, row, cls):
    col_names = [d[0] for d in desc]
    field_names = {f.name for f in dataclasses.fields(cls)}
    kwargs = {}
    for i, name in enumerate(col_names):
        if name in field_names:
            kwargs[name] = row[i]
    return cls(**kwargs)
