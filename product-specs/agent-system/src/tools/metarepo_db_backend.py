"""
Metarepo DB Backend —— 直接查询本地 PostgreSQL 数据库

直连 paas_metarepo_common / paas_metarepo schema，读取元模型定义和元数据实例。
方法签名与 MetarepoSimulatedBackend 完全一致（同步方法），上层 API 通过 _await 桥接。

数据库 schema 说明：
  paas_metarepo_common —— 元模型定义（p_meta_model / p_meta_item / p_meta_link / p_meta_option）
                          + Common 级元数据（p_common_metadata 大宽表）
  paas_metarepo        —— Tenant 级元数据（p_tenant_entity / p_tenant_item / ...）

环境变量（复用 pg_pool 的配置）：
  PG_HOST / PG_PORT / PG_DB / PG_USER / PG_PASSWORD
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Generator, Optional

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pg_pool

logger = logging.getLogger(__name__)

# ─── 连接池（独立于 paas_ai schema 的连接池）───

_metarepo_pool: pg_pool.ThreadedConnectionPool | None = None


def _get_metarepo_pool() -> pg_pool.ThreadedConnectionPool:
    global _metarepo_pool
    if _metarepo_pool is not None:
        return _metarepo_pool

    _metarepo_pool = pg_pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=5,
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", "5432")),
        dbname=os.environ.get("PG_DB", "paas_db"),
        user=os.environ.get("PG_USER", "postgres"),
        password=os.environ.get("PG_PASSWORD", "123456"),
        # 不设置 search_path，SQL 中显式指定 schema
    )
    logger.info(
        "Metarepo DB 连接池初始化: %s:%s/%s",
        os.environ.get("PG_HOST", "127.0.0.1"),
        os.environ.get("PG_PORT", "5432"),
        os.environ.get("PG_DB", "paas_db"),
    )
    return _metarepo_pool


@contextmanager
def _get_conn() -> Generator:
    p = _get_metarepo_pool()
    conn = p.getconn()
    try:
        yield conn
    finally:
        p.putconn(conn)


def _snake_to_camel(s: str) -> str:
    """snake_case → camelCase，dbc_ 前缀列保持原样。"""
    if not s or "_" not in s:
        return s
    if s.startswith("dbc_"):
        return s
    parts = s.split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:] if p)


def _rows_to_camel(rows: list[dict]) -> list[dict]:
    """将查询结果的 snake_case key 转为 camelCase。"""
    return [{_snake_to_camel(k): v for k, v in row.items()} for row in rows]


# ─── 元模型字段定义中 item_type 的编码映射 ───

ITEM_TYPE_MAPPING: list[dict[str, Any]] = [
    {"code": "VARCHAR", "name": "VARCHAR", "description": "短文本", "dbColumnPrefix": "dbc_varchar", "isCompute": False, "isVirtual": False, "dataTypeCode": "STRING", "dataTypeLabel": "字符串", "javaType": "String"},
    {"code": "TEXT", "name": "TEXT", "description": "长文本", "dbColumnPrefix": "dbc_text", "isCompute": False, "isVirtual": False, "dataTypeCode": "STRING", "dataTypeLabel": "字符串", "javaType": "String"},
    {"code": "INTEGER", "name": "INTEGER", "description": "整数", "dbColumnPrefix": "dbc_int", "isCompute": False, "isVirtual": False, "dataTypeCode": "INT", "dataTypeLabel": "整数", "javaType": "Integer"},
    {"code": "LONG", "name": "LONG", "description": "长整数", "dbColumnPrefix": "dbc_bigint", "isCompute": False, "isVirtual": False, "dataTypeCode": "LONG", "dataTypeLabel": "长整数", "javaType": "Long"},
    {"code": "DECIMAL", "name": "DECIMAL", "description": "金额/小数", "dbColumnPrefix": "dbc_decimal", "isCompute": False, "isVirtual": False, "dataTypeCode": "DECIMAL", "dataTypeLabel": "小数", "javaType": "BigDecimal"},
    {"code": "DATE", "name": "DATE", "description": "日期", "dbColumnPrefix": "dbc_date", "isCompute": False, "isVirtual": False, "dataTypeCode": "DATE", "dataTypeLabel": "日期", "javaType": "LocalDate"},
    {"code": "DATETIME", "name": "DATETIME", "description": "日期时间", "dbColumnPrefix": "dbc_datetime", "isCompute": False, "isVirtual": False, "dataTypeCode": "DATETIME", "dataTypeLabel": "日期时间", "javaType": "LocalDateTime"},
    {"code": "BOOLEAN_FLG", "name": "BOOLEAN_FLG", "description": "布尔标记", "dbColumnPrefix": "dbc_smallint", "isCompute": False, "isVirtual": False, "dataTypeCode": "INT", "dataTypeLabel": "整数", "javaType": "Integer"},
    {"code": "PICK_LIST", "name": "PICK_LIST", "description": "选项集", "dbColumnPrefix": "dbc_varchar", "isCompute": False, "isVirtual": False, "dataTypeCode": "STRING", "dataTypeLabel": "字符串", "javaType": "String"},
    {"code": "RELATIONSHIP", "name": "RELATIONSHIP", "description": "关联字段", "dbColumnPrefix": "dbc_varchar", "isCompute": False, "isVirtual": False, "dataTypeCode": "STRING", "dataTypeLabel": "字符串", "javaType": "String"},
    {"code": "FORMULA", "name": "FORMULA", "description": "公式计算字段", "dbColumnPrefix": "", "isCompute": True, "isVirtual": True, "dataTypeCode": "DECIMAL", "dataTypeLabel": "小数", "javaType": "BigDecimal"},
    {"code": "AGGREGATION", "name": "AGGREGATION", "description": "汇总累计", "dbColumnPrefix": "", "isCompute": True, "isVirtual": True, "dataTypeCode": "DECIMAL", "dataTypeLabel": "小数", "javaType": "BigDecimal"},
]

# Common schema
S_COMMON = "paas_metarepo_common"
# Tenant schema
S_TENANT = "paas_metarepo"


class MetarepoDbBackend:
    """直连 PostgreSQL 查询元模型和元数据，方法签名与 MetarepoSimulatedBackend 一致。"""

    def __init__(self, tenant_id: int | None = None):
        from src.core.context import DEFAULT_TENANT_ID
        self._tenant_id = tenant_id or int(os.environ.get("DEFAULT_TENANT_ID", str(DEFAULT_TENANT_ID)))

    # ─── 内部查询工具 ───

    def _query(self, sql: str, params: tuple = ()) -> list[dict]:
        with _get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]

    # ─── 元模型层 ───

    def list_metamodels(self) -> list[dict[str, Any]]:
        sql = f"""
            SELECT * FROM {S_COMMON}.p_meta_model
            WHERE delete_flg = 0
            ORDER BY created_at
        """
        rows = self._query(sql)
        return _rows_to_camel(rows)

    def get_metamodel(self, metamodel_api_key: str) -> Optional[dict[str, Any]]:
        sql = f"""
            SELECT * FROM {S_COMMON}.p_meta_model
            WHERE api_key = %s AND delete_flg = 0
        """
        rows = self._query(sql, (metamodel_api_key,))
        if not rows:
            return None
        return _rows_to_camel(rows)[0]

    def list_meta_items(self, metamodel_api_key: str) -> list[dict[str, Any]]:
        sql = f"""
            SELECT * FROM {S_COMMON}.p_meta_item
            WHERE metamodel_api_key = %s AND delete_flg = 0
            ORDER BY created_at
        """
        rows = self._query(sql, (metamodel_api_key,))
        return _rows_to_camel(rows)

    def get_column_mapping(self, metamodel_api_key: str) -> dict[str, str]:
        sql = f"""
            SELECT db_column, api_key FROM {S_COMMON}.p_meta_item
            WHERE metamodel_api_key = %s AND delete_flg = 0
              AND db_column IS NOT NULL AND db_column != ''
        """
        rows = self._query(sql, (metamodel_api_key,))
        return {r["db_column"]: r["api_key"] for r in rows}

    def list_meta_links(self, metamodel_api_key: Optional[str] = None) -> list[dict[str, Any]]:
        if metamodel_api_key:
            sql = f"""
                SELECT * FROM {S_COMMON}.p_meta_link
                WHERE delete_flg = 0
                  AND (parent_metamodel_api_key = %s OR child_metamodel_api_key = %s)
            """
            rows = self._query(sql, (metamodel_api_key, metamodel_api_key))
        else:
            sql = f"""
                SELECT * FROM {S_COMMON}.p_meta_link
                WHERE delete_flg = 0
            """
            rows = self._query(sql)
        return _rows_to_camel(rows)

    def list_meta_options(
        self,
        metamodel_api_key: str,
        item_api_key: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        if item_api_key:
            sql = f"""
                SELECT * FROM {S_COMMON}.p_meta_option
                WHERE metamodel_api_key = %s AND item_api_key = %s AND delete_flg = 0
                ORDER BY COALESCE(option_order, 0)
            """
            rows = self._query(sql, (metamodel_api_key, item_api_key))
        else:
            sql = f"""
                SELECT * FROM {S_COMMON}.p_meta_option
                WHERE metamodel_api_key = %s AND delete_flg = 0
                ORDER BY COALESCE(option_order, 0)
            """
            rows = self._query(sql, (metamodel_api_key,))
        return _rows_to_camel(rows)

    def get_item_type_mapping(self) -> list[dict[str, Any]]:
        return list(ITEM_TYPE_MAPPING)

    # ─── 元数据实例层（Common + Tenant 合并） ───

    def _get_db_table(self, metamodel_api_key: str) -> Optional[str]:
        """查询元模型对应的 Tenant 级存储表名。"""
        sql = f"""
            SELECT db_table FROM {S_COMMON}.p_meta_model
            WHERE api_key = %s AND delete_flg = 0
        """
        rows = self._query(sql, (metamodel_api_key,))
        if rows:
            return rows[0].get("db_table")
        return None

    def _get_meta_items_for_mapping(self, metamodel_api_key: str) -> list[dict]:
        """获取元模型字段定义，用于 dbc 列 → apiKey 映射。"""
        sql = f"""
            SELECT api_key, db_column FROM {S_COMMON}.p_meta_item
            WHERE metamodel_api_key = %s AND delete_flg = 0
              AND db_column IS NOT NULL AND db_column != ''
        """
        return self._query(sql, (metamodel_api_key,))

    def _map_dbc_to_api_key(self, row: dict, col_mapping: dict[str, str]) -> dict[str, Any]:
        """将大宽表行的 dbc_xxxN 列转换为 apiKey 字段名。"""
        result: dict[str, Any] = {}
        # 保留固定列
        fixed_cols = {"id", "api_key", "metamodel_api_key", "entity_api_key",
                      "parent_metadata_api_key", "namespace", "custom_flg",
                      "delete_flg", "created_at", "created_by", "updated_at", "updated_by",
                      "tenant_id", "sort_num"}
        for k, v in row.items():
            if k in fixed_cols:
                result[_snake_to_camel(k)] = v
            elif k.startswith("dbc_") and k in col_mapping:
                result[col_mapping[k]] = v
            # 跳过未映射的 dbc 列
        return result

    def list_metadata(
        self,
        metamodel_api_key: str,
        entity_api_key: Optional[str] = None,
        item_api_key: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """查询元数据实例（Common + Tenant 合并）。

        策略：
        1. 查 Common 大宽表 p_common_metadata
        2. 查 Tenant 级快捷表（如果有 db_table）
        3. 合并：Tenant 覆盖 Common（按 api_key 去重）
        """
        col_items = self._get_meta_items_for_mapping(metamodel_api_key)
        col_mapping = {r["db_column"]: r["api_key"] for r in col_items}

        # 1. Common 级
        common_records = self._query_common_metadata(metamodel_api_key, entity_api_key, item_api_key)
        common_mapped = [self._map_dbc_to_api_key(r, col_mapping) for r in common_records]

        # 2. Tenant 级
        db_table = self._get_db_table(metamodel_api_key)
        tenant_mapped: list[dict] = []
        if db_table:
            tenant_records = self._query_tenant_table(db_table, metamodel_api_key, entity_api_key, item_api_key)
            tenant_mapped = [self._map_dbc_to_api_key(r, col_mapping) for r in tenant_records]

        # 3. 合并（Tenant 覆盖 Common）
        merged_map: dict[str, dict] = {}
        for r in common_mapped:
            key = r.get("apiKey", "")
            if key:
                merged_map[key] = r
        for r in tenant_mapped:
            key = r.get("apiKey", "")
            if key:
                merged_map[key] = r

        result = list(merged_map.values())
        result.sort(key=lambda r: r.get("sortNum") or r.get("optionOrder") or 0)
        return result

    def _query_common_metadata(
        self, metamodel_api_key: str, entity_api_key: Optional[str], item_api_key: Optional[str]
    ) -> list[dict]:
        conditions = ["metamodel_api_key = %s", "delete_flg = 0"]
        params: list = [metamodel_api_key]
        if entity_api_key:
            conditions.append("entity_api_key = %s")
            params.append(entity_api_key)
        sql = f"""
            SELECT * FROM {S_COMMON}.p_common_metadata
            WHERE {' AND '.join(conditions)}
        """
        rows = self._query(sql, tuple(params))
        # item_api_key 过滤需要知道哪个 dbc 列存储了 itemApiKey
        if item_api_key and rows:
            # 找到 itemApiKey 对应的 dbc 列
            item_col = None
            for ci in self._get_meta_items_for_mapping(metamodel_api_key):
                if ci["api_key"] == "itemApiKey":
                    item_col = ci["db_column"]
                    break
            if item_col:
                rows = [r for r in rows if r.get(item_col) == item_api_key]
        return rows

    def _query_tenant_table(
        self, db_table: str, metamodel_api_key: str,
        entity_api_key: Optional[str], item_api_key: Optional[str]
    ) -> list[dict]:
        """查询 Tenant 级快捷表。"""
        conditions = ["delete_flg = 0", "tenant_id = %s"]
        params: list = [self._tenant_id]
        if entity_api_key:
            conditions.append("entity_api_key = %s")
            params.append(entity_api_key)
        # 安全检查：表名只允许字母数字下划线
        if not all(c.isalnum() or c == '_' for c in db_table):
            logger.warning("非法表名: %s", db_table)
            return []
        sql = f"""
            SELECT * FROM {S_TENANT}.{db_table}
            WHERE {' AND '.join(conditions)}
        """
        try:
            rows = self._query(sql, tuple(params))
        except Exception as exc:
            # 表可能不存在（如新注册的元模型还没建表）
            logger.debug("查询 Tenant 表 %s 失败: %s", db_table, exc)
            return []
        if item_api_key and rows:
            item_col = None
            for ci in self._get_meta_items_for_mapping(metamodel_api_key):
                if ci["api_key"] == "itemApiKey":
                    item_col = ci["db_column"]
                    break
            if item_col:
                rows = [r for r in rows if r.get(item_col) == item_api_key]
        return rows

    def get_metadata(
        self,
        metamodel_api_key: str,
        api_key: str,
        entity_api_key: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        records = self.list_metadata(metamodel_api_key, entity_api_key=entity_api_key)
        for r in records:
            if r.get("apiKey") == api_key:
                return r
        return None

    # ─── 便捷封装 ───

    def list_metadata_entities(self) -> list[dict[str, Any]]:
        return self.list_metadata("entity")

    def list_metadata_items(self, entity_api_key: str) -> list[dict[str, Any]]:
        return self.list_metadata("item", entity_api_key=entity_api_key)

    def list_metadata_entity_links(self, entity_api_key: str) -> list[dict[str, Any]]:
        return self.list_metadata("entityLink", entity_api_key=entity_api_key)

    def list_metadata_check_rules(self, entity_api_key: str) -> list[dict[str, Any]]:
        return self.list_metadata("checkRule", entity_api_key=entity_api_key)

    def list_metadata_busi_types(self, entity_api_key: str) -> list[dict[str, Any]]:
        return self.list_metadata("busiType", entity_api_key=entity_api_key)

    def list_metadata_pick_options(self, item_api_key: str) -> list[dict[str, Any]]:
        return self.list_metadata("pickOption", item_api_key=item_api_key)

    # ─── 诊断辅助 ───

    def trace_db_column(self, db_column: str) -> list[dict[str, Any]]:
        sql = f"""
            SELECT metamodel_api_key, api_key, label, item_type
            FROM {S_COMMON}.p_meta_item
            WHERE db_column = %s AND delete_flg = 0
        """
        rows = self._query(sql, (db_column,))
        return [{
            "metamodelApiKey": r["metamodel_api_key"],
            "itemApiKey": r["api_key"],
            "label": r.get("label"),
            "itemType": r.get("item_type"),
        } for r in rows]

    def get_stats(self) -> dict[str, int]:
        stats = {}
        try:
            rows = self._query(f"SELECT COUNT(*) as cnt FROM {S_COMMON}.p_meta_model WHERE delete_flg = 0")
            stats["meta_models"] = rows[0]["cnt"] if rows else 0
        except Exception:
            stats["meta_models"] = 0
        try:
            rows = self._query(f"SELECT COUNT(*) as cnt FROM {S_COMMON}.p_meta_item WHERE delete_flg = 0")
            stats["meta_items_total"] = rows[0]["cnt"] if rows else 0
        except Exception:
            stats["meta_items_total"] = 0
        try:
            rows = self._query(f"SELECT COUNT(*) as cnt FROM {S_COMMON}.p_meta_link WHERE delete_flg = 0")
            stats["meta_links"] = rows[0]["cnt"] if rows else 0
        except Exception:
            stats["meta_links"] = 0
        try:
            rows = self._query(f"SELECT COUNT(*) as cnt FROM {S_COMMON}.p_meta_option WHERE delete_flg = 0")
            stats["meta_options"] = rows[0]["cnt"] if rows else 0
        except Exception:
            stats["meta_options"] = 0
        try:
            rows = self._query(f"SELECT COUNT(*) as cnt FROM {S_COMMON}.p_common_metadata WHERE delete_flg = 0")
            stats["metadata_instances_total"] = rows[0]["cnt"] if rows else 0
        except Exception:
            stats["metadata_instances_total"] = 0
        return stats
