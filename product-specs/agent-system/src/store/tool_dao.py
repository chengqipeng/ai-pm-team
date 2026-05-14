"""Tool DAO — ai_tool_definition CRUD"""
from __future__ import annotations

import dataclasses
import logging
from typing import Any

from .pg_pool import get_conn

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class ToolDefinitionRow:
    id: int = 0
    api_key: str = ""
    tenant_id: int = 0
    name: str = ""
    description: str = ""
    input_schema: str = "{}"
    prompt: str = ""
    category: str = ""
    tags: str = "[]"
    icon: str = ""
    read_only_flg: int = 1
    destructive_flg: int = 0
    enabled_flg: int = 1
    system_flg: int = 0
    sort_num: int = 0
    ext_info: str = "{}"
    delete_flg: int = 0
    created_at: int = 0
    created_by: int = 0
    updated_at: int = 0
    updated_by: int = 0


_COLUMNS = (
    "id, api_key, tenant_id, name, description, input_schema, prompt, "
    "category, tags, icon, read_only_flg, destructive_flg, "
    "enabled_flg, system_flg, sort_num, ext_info, "
    "delete_flg, created_at, created_by, updated_at, updated_by"
)


def _row_from_tuple(t: tuple) -> ToolDefinitionRow:
    return ToolDefinitionRow(
        id=t[0], api_key=t[1], tenant_id=t[2],
        name=t[3], description=t[4], input_schema=t[5], prompt=t[6],
        category=t[7], tags=t[8], icon=t[9],
        read_only_flg=t[10], destructive_flg=t[11],
        enabled_flg=t[12], system_flg=t[13], sort_num=t[14], ext_info=t[15],
        delete_flg=t[16], created_at=t[17], created_by=t[18],
        updated_at=t[19], updated_by=t[20],
    )


class ToolDefinitionDAO:
    """ai_tool_definition 表访问层"""

    @staticmethod
    def list_all(tenant_id: int = 0, enabled_only: bool = False) -> list[ToolDefinitionRow]:
        """列出所有工具（含平台级）"""
        sql = f"SELECT {_COLUMNS} FROM ai_tool_definition WHERE delete_flg = 0 AND (tenant_id = %s OR tenant_id = 0)"
        params: list[Any] = [tenant_id]
        if enabled_only:
            sql += " AND enabled_flg = 1"
        sql += " ORDER BY sort_num, created_at"
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return [_row_from_tuple(t) for t in cur.fetchall()]

    @staticmethod
    def get_by_api_key(tenant_id: int, api_key: str) -> ToolDefinitionRow | None:
        sql = f"SELECT {_COLUMNS} FROM ai_tool_definition WHERE delete_flg = 0 AND (tenant_id = %s OR tenant_id = 0) AND api_key = %s LIMIT 1"
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, (tenant_id, api_key))
            t = cur.fetchone()
            return _row_from_tuple(t) if t else None

    @staticmethod
    def create(row: ToolDefinitionRow) -> None:
        sql = f"""
            INSERT INTO ai_tool_definition ({_COLUMNS})
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (tenant_id, api_key) WHERE delete_flg = 0 DO NOTHING
        """
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, (
                row.id, row.api_key, row.tenant_id, row.name, row.description,
                row.input_schema, row.prompt, row.category, row.tags, row.icon,
                row.read_only_flg, row.destructive_flg, row.enabled_flg, row.system_flg,
                row.sort_num, row.ext_info, row.delete_flg,
                row.created_at, row.created_by, row.updated_at, row.updated_by,
            ))

    @staticmethod
    def update_fields(tenant_id: int, api_key: str, fields: dict[str, Any]) -> None:
        if not fields:
            return
        set_clauses = [f"{k} = %s" for k in fields]
        params = list(fields.values())
        params.extend([tenant_id, api_key])
        sql = f"UPDATE ai_tool_definition SET {', '.join(set_clauses)} WHERE (tenant_id = %s OR tenant_id = 0) AND api_key = %s AND delete_flg = 0"
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)

    @staticmethod
    def soft_delete(tenant_id: int, api_key: str, now: int = 0) -> None:
        sql = "UPDATE ai_tool_definition SET delete_flg = 1, updated_at = %s WHERE (tenant_id = %s OR tenant_id = 0) AND api_key = %s AND delete_flg = 0"
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, (now, tenant_id, api_key))
