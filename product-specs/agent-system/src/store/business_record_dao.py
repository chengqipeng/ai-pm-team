"""agent-system 内部通用业务记录 PostgreSQL DAO。"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any

from .pg_pool import get_conn
from .snowflake import next_id

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False

DDL = """
CREATE TABLE IF NOT EXISTS ai_business_record (
    id BIGINT PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    entity_api_key VARCHAR(100) NOT NULL,
    record_api_key VARCHAR(128) NOT NULL,
    record_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    version INT NOT NULL DEFAULT 1,
    source_action_id VARCHAR(128) NOT NULL DEFAULT '',
    last_action_id VARCHAR(128) NOT NULL DEFAULT '',
    delete_flg SMALLINT NOT NULL DEFAULT 0,
    created_at BIGINT NOT NULL,
    created_by BIGINT NOT NULL DEFAULT 0,
    updated_at BIGINT NOT NULL,
    updated_by BIGINT NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_business_record_key
ON ai_business_record(tenant_id, entity_api_key, record_api_key)
WHERE delete_flg = 0;
CREATE UNIQUE INDEX IF NOT EXISTS uk_business_record_create_action
ON ai_business_record(tenant_id, source_action_id)
WHERE source_action_id != '';
CREATE INDEX IF NOT EXISTS idx_business_record_entity
ON ai_business_record(tenant_id, entity_api_key, updated_at DESC)
WHERE delete_flg = 0;
"""


@dataclass(frozen=True)
class BusinessRecord:
    id: int
    tenant_id: int
    entity_api_key: str
    record_api_key: str
    data: dict[str, Any]
    version: int
    last_action_id: str
    created_at: int
    updated_at: int

    def to_dict(self) -> dict[str, Any]:
        return {**self.data, "recordApiKey": self.record_api_key,
                "entityApiKey": self.entity_api_key, "version": self.version,
                "createdAt": self.created_at, "updatedAt": self.updated_at}


def _from_row(row: tuple | None) -> BusinessRecord | None:
    if row is None:
        return None
    data = row[4] if isinstance(row[4], dict) else json.loads(row[4] or "{}")
    return BusinessRecord(
        id=row[0], tenant_id=row[1], entity_api_key=row[2],
        record_api_key=row[3], data=data, version=row[5],
        last_action_id=row[6], created_at=row[7], updated_at=row[8],
    )


_COLUMNS = (
    "id, tenant_id, entity_api_key, record_api_key, record_data, "
    "version, last_action_id, created_at, updated_at"
)


class BusinessRecordDAO:
    @staticmethod
    def ensure_schema() -> None:
        global _SCHEMA_READY
        if _SCHEMA_READY:
            return
        with _SCHEMA_LOCK:
            if _SCHEMA_READY:
                return
            with get_conn() as conn:
                conn.cursor().execute(DDL)
            _SCHEMA_READY = True

    @staticmethod
    def get(tenant_id: int, entity: str,
            record_api_key: str) -> BusinessRecord | None:
        BusinessRecordDAO.ensure_schema()
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT {_COLUMNS} FROM ai_business_record "
                "WHERE tenant_id=%s AND entity_api_key=%s "
                "AND record_api_key=%s AND delete_flg=0",
                (tenant_id, entity, record_api_key),
            )
            return _from_row(cur.fetchone())

    @staticmethod
    def list_records(tenant_id: int, entity: str, filters: dict[str, Any],
                     page: int, page_size: int) -> tuple[list[BusinessRecord], int]:
        BusinessRecordDAO.ensure_schema()
        where = ["tenant_id=%s", "entity_api_key=%s", "delete_flg=0"]
        params: list[Any] = [tenant_id, entity]
        if filters:
            where.append("record_data @> %s::jsonb")
            params.append(json.dumps(filters, ensure_ascii=False))
        clause = " AND ".join(where)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM ai_business_record WHERE {clause}", params)
            total = int(cur.fetchone()[0])
            cur.execute(
                f"SELECT {_COLUMNS} FROM ai_business_record WHERE {clause} "
                "ORDER BY updated_at DESC LIMIT %s OFFSET %s",
                [*params, page_size, (page - 1) * page_size],
            )
            return ([_from_row(row) for row in cur.fetchall()], total)  # type: ignore[misc]

    @staticmethod
    def create(tenant_id: int, user_id: int, entity: str,
               data: dict[str, Any], action_id: str) -> BusinessRecord:
        BusinessRecordDAO.ensure_schema()
        now, row_id = int(time.time() * 1000), next_id()
        record_key = f"{entity[:3]}_{row_id}"
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO ai_business_record "
                "(id,tenant_id,entity_api_key,record_api_key,record_data,version,"
                "source_action_id,last_action_id,delete_flg,created_at,created_by,updated_at,updated_by) "
                "VALUES (%s,%s,%s,%s,%s::jsonb,1,%s,%s,0,%s,%s,%s,%s) "
                f"ON CONFLICT DO NOTHING RETURNING {_COLUMNS}",
                (row_id, tenant_id, entity, record_key,
                 json.dumps(data, ensure_ascii=False), action_id, action_id,
                 now, user_id, now, user_id),
            )
            record = _from_row(cur.fetchone())
            if record is not None:
                return record
            cur.execute(
                f"SELECT {_COLUMNS} FROM ai_business_record "
                "WHERE tenant_id=%s AND source_action_id=%s LIMIT 1",
                (tenant_id, action_id),
            )
            existing = _from_row(cur.fetchone())
            if existing is None:
                raise RuntimeError("failed to create business record")
            return existing

    @staticmethod
    def update(tenant_id: int, user_id: int, entity: str, record_key: str,
               changes: dict[str, Any], expected_version: int,
               action_id: str) -> BusinessRecord:
        BusinessRecordDAO.ensure_schema()
        current = BusinessRecordDAO.get(tenant_id, entity, record_key)
        if current is None:
            raise LookupError("record not found")
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE ai_business_record SET "
                "record_data=record_data || %s::jsonb, version=version+1, "
                "last_action_id=%s, updated_at=%s, updated_by=%s "
                "WHERE tenant_id=%s AND entity_api_key=%s AND record_api_key=%s "
                "AND version=%s AND delete_flg=0 AND last_action_id<>%s "
                f"RETURNING {_COLUMNS}",
                (json.dumps(changes, ensure_ascii=False), action_id, now, user_id,
                 tenant_id, entity, record_key, expected_version, action_id),
            )
            updated = _from_row(cur.fetchone())
        if updated is not None:
            return updated
        repeated = BusinessRecordDAO.get(tenant_id, entity, record_key)
        if (repeated is not None and repeated.last_action_id == action_id
                and repeated.version == expected_version + 1):
            return repeated
        raise RuntimeError("version conflict")

    @staticmethod
    def soft_delete(tenant_id: int, user_id: int, entity: str,
                    record_key: str, expected_version: int,
                    action_id: str) -> BusinessRecord:
        BusinessRecordDAO.ensure_schema()
        current = BusinessRecordDAO.get(tenant_id, entity, record_key)
        if current is None:
            raise LookupError("record not found")
        now = int(time.time() * 1000)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE ai_business_record SET delete_flg=1, version=version+1, "
                "last_action_id=%s, updated_at=%s, updated_by=%s "
                "WHERE tenant_id=%s AND entity_api_key=%s AND record_api_key=%s "
                "AND version=%s AND delete_flg=0 "
                f"RETURNING {_COLUMNS}",
                (action_id, now, user_id, tenant_id, entity,
                 record_key, expected_version),
            )
            deleted = _from_row(cur.fetchone())
        if deleted is None:
            raise RuntimeError("version conflict")
        return deleted
