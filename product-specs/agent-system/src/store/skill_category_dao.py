"""Skill Category DAO — ai_skill_category CRUD"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any

from .pg_pool import get_conn

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class SkillCategoryRow:
    id: int = 0
    api_key: str = ""
    tenant_id: int = 0
    name: str = ""
    name_key: str = ""
    description: str = ""
    icon: str = ""
    color: str = ""
    sort_num: int = 0
    enabled_flg: int = 1
    system_flg: int = 0
    delete_flg: int = 0
    created_at: int = 0
    created_by: int = 0
    updated_at: int = 0
    updated_by: int = 0
    skill_count: int = 0


_COLUMNS = (
    "id, api_key, tenant_id, name, name_key, description, icon, color, "
    "sort_num, enabled_flg, system_flg, "
    "delete_flg, created_at, created_by, updated_at, updated_by"
)


def _row_from_tuple(t: tuple) -> SkillCategoryRow:
    return SkillCategoryRow(
        id=t[0], api_key=t[1], tenant_id=t[2],
        name=t[3], name_key=t[4], description=t[5],
        icon=t[6], color=t[7], sort_num=t[8],
        enabled_flg=t[9], system_flg=t[10],
        delete_flg=t[11], created_at=t[12], created_by=t[13],
        updated_at=t[14], updated_by=t[15],
    )


class SkillCategoryDAO:
    """ai_skill_category 表访问层"""

    @staticmethod
    def _next_id() -> int:
        """简易雪花 ID 生成（生产环境应使用分布式 ID 生成器）"""
        import time
        import random
        ts = int(time.time() * 1000)
        return (ts << 20) | random.randint(0, (1 << 20) - 1)

    @staticmethod
    def list_all(tenant_id: int = 0) -> list[SkillCategoryRow]:
        """列出所有分类（含平台级 + 租户级），按 sort_num 排序，附带 skill_count"""
        sql = f"""
            SELECT {_COLUMNS}, COALESCE(sc.cnt, 0) AS skill_count
            FROM ai_skill_category c
            LEFT JOIN (
                SELECT category, COUNT(*) AS cnt
                FROM ai_skill_definition
                WHERE delete_flg = 0
                  AND (tenant_id = %s OR tenant_id = 0)
                GROUP BY category
            ) sc ON sc.category = c.api_key
            WHERE c.delete_flg = 0
              AND (c.tenant_id = %s OR c.tenant_id = 0)
            ORDER BY c.sort_num, c.created_at
        """
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, (tenant_id, tenant_id))
            rows = []
            for t in cur.fetchall():
                row = _row_from_tuple(t[:16])
                row.skill_count = t[16] if len(t) > 16 else 0
                rows.append(row)
            return rows

    @staticmethod
    def get_by_api_key(tenant_id: int, api_key: str) -> SkillCategoryRow | None:
        """按 api_key 查询单条分类"""
        sql = f"""
            SELECT {_COLUMNS}
            FROM ai_skill_category
            WHERE delete_flg = 0
              AND (tenant_id = %s OR tenant_id = 0)
              AND api_key = %s
            LIMIT 1
        """
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, (tenant_id, api_key))
            t = cur.fetchone()
            if t is None:
                return None
            return _row_from_tuple(t)

    @staticmethod
    def create(
        tenant_id: int,
        api_key: str,
        name: str,
        description: str = "",
        icon: str = "",
        color: str = "",
        sort_num: int = 0,
        now: int = 0,
    ) -> SkillCategoryRow:
        """创建分类"""
        row_id = SkillCategoryDAO._next_id()
        sql = """
            INSERT INTO ai_skill_category
            (id, api_key, tenant_id, name, name_key, description, icon, color,
             sort_num, enabled_flg, system_flg,
             delete_flg, created_at, created_by, updated_at, updated_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1, 0, 0, %s, 0, %s, 0)
        """
        name_key = f"skill.category.{api_key}"
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, (
                row_id, api_key, tenant_id, name, name_key,
                description, icon, color, sort_num, now, now,
            ))
        return SkillCategoryRow(
            id=row_id, api_key=api_key, tenant_id=tenant_id,
            name=name, name_key=name_key, description=description,
            icon=icon, color=color, sort_num=sort_num,
            enabled_flg=1, system_flg=0,
            delete_flg=0, created_at=now, created_by=0,
            updated_at=now, updated_by=0,
        )

    @staticmethod
    def update(
        tenant_id: int,
        api_key: str,
        updates: dict[str, Any],
        now: int = 0,
    ) -> SkillCategoryRow:
        """更新分类字段"""
        updates["updated_at"] = now
        set_clauses = ", ".join(f"{k} = %s" for k in updates)
        values = list(updates.values())
        values.extend([tenant_id, api_key])

        sql = f"""
            UPDATE ai_skill_category
            SET {set_clauses}
            WHERE (tenant_id = %s OR tenant_id = 0)
              AND api_key = %s
              AND delete_flg = 0
        """
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, values)

        # 返回更新后的记录
        return SkillCategoryDAO.get_by_api_key(tenant_id, api_key)  # type: ignore

    @staticmethod
    def soft_delete(tenant_id: int, api_key: str, now: int = 0) -> None:
        """软删除分类"""
        sql = """
            UPDATE ai_skill_category
            SET delete_flg = 1, updated_at = %s
            WHERE (tenant_id = %s OR tenant_id = 0)
              AND api_key = %s
              AND delete_flg = 0
        """
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, (now, tenant_id, api_key))
