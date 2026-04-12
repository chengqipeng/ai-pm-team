#!/usr/bin/env python3
"""
Phase 0: 元数据验证
验证 entity/item/pickOption/entityLink/busiType 描述正确性
所有元数据在 PG 的 p_common_metadata 表中
"""
import sys
from .config import (CORE_ENTITIES, OLD_ITEM_TYPE_CODES,
                     ITEM_TYPE_TO_BIZ_PREFIX, VIRTUAL_TYPES)
from .db import get_pg_dict


class MetadataVerifier:
    def __init__(self, entities=None):
        self.entities = entities or CORE_ENTITIES
        self.errors = []
        self.warnings = []

    def run(self):
        conn, self.cur = get_pg_dict()
        try:
            checks = [
                ('V1', 'entity 存在性',          self._v1_entity),
                ('V2', 'item 完整性',             self._v2_item_count),
                ('V3', 'dbColumn 非空',           self._v3_dbcolumn_notnull),
                ('V4', 'dbColumn 格式',           self._v4_dbcolumn_format),
                ('V5', 'itemType 编码',           self._v5_itemtype),
                ('V6', 'dbColumn 唯一性',         self._v6_dbcolumn_unique),
                ('V7', 'pickOption 完整性',       self._v7_pickoption),
                ('V8', 'busiType 完整性',         self._v8_busitype),
                ('V9', 'dbColumn 前缀一致性',     self._v9_prefix),
            ]
            for code, label, fn in checks:
                print(f"\n[{code}] {label}...")
                fn()
            self._print_report()
        finally:
            self.cur.close()
            conn.close()
        return len(self.errors) == 0

    def _q(self, sql, params=None):
        self.cur.execute(sql, params)
        return self.cur.fetchall()

    def _v1_entity(self):
        rows = self._q("""
            SELECT api_key FROM p_common_metadata
            WHERE metamodel_api_key='entity' AND api_key = ANY(%s) AND delete_flg=0
        """, (list(self.entities),))
        found = {r['api_key'] for r in rows}
        missing = set(self.entities) - found
        if missing:
            self.errors.append(f"[V1] entity 缺失: {missing}")
        else:
            print(f"  ✅ {len(found)} 个核心 entity 全部存在")

    def _v2_item_count(self):
        for ent in self.entities:
            rows = self._q("""
                SELECT COUNT(*) AS cnt FROM p_common_metadata
                WHERE metamodel_api_key='item' AND entity_api_key=%s AND delete_flg=0
            """, (ent,))
            cnt = rows[0]['cnt']
            if cnt == 0:
                self.errors.append(f"[V2] {ent} 无任何 item 定义")
            else:
                print(f"  {ent}: {cnt} 个 item")

    def _v3_dbcolumn_notnull(self):
        rows = self._q("""
            SELECT entity_api_key, api_key, dbc_int1
            FROM p_common_metadata
            WHERE metamodel_api_key='item'
              AND dbc_int1 NOT IN (6,7,21,27)
              AND (dbc_varchar3 IS NULL OR dbc_varchar3='')
              AND delete_flg=0 AND entity_api_key = ANY(%s)
        """, (list(self.entities),))
        if rows:
            self.errors.append(
                f"[V3] {len(rows)} 个非虚拟字段 dbColumn 为空, "
                f"示例: {[(r['entity_api_key'], r['api_key']) for r in rows[:3]]}")
        else:
            print("  ✅ 非虚拟字段 dbColumn 全部非空")

    def _v4_dbcolumn_format(self):
        rows = self._q("""
            SELECT entity_api_key, api_key, dbc_varchar3
            FROM p_common_metadata
            WHERE metamodel_api_key='item'
              AND dbc_varchar3 ~ 'dbc_[a-z]+_[0-9]'
              AND delete_flg=0 AND entity_api_key = ANY(%s)
        """, (list(self.entities),))
        if rows:
            self.warnings.append(
                f"[V4] {len(rows)} 个 dbColumn 含下划线格式: "
                f"{[(r['entity_api_key'], r['api_key'], r['dbc_varchar3']) for r in rows[:3]]}")
        else:
            print("  ✅ dbColumn 格式全部正确")

    def _v5_itemtype(self):
        rows = self._q("""
            SELECT dbc_int1 AS t, COUNT(*) AS c FROM p_common_metadata
            WHERE metamodel_api_key='item' AND entity_api_key = ANY(%s) AND delete_flg=0
            GROUP BY dbc_int1
        """, (list(self.entities),))
        old = [(r['t'], r['c']) for r in rows if r['t'] in OLD_ITEM_TYPE_CODES]
        if old:
            self.errors.append(f"[V5] itemType 含老编码: {old}")
        else:
            print("  ✅ 所有 itemType 均为新编码")

    def _v6_dbcolumn_unique(self):
        rows = self._q("""
            SELECT entity_api_key, dbc_varchar3, COUNT(*) AS cnt
            FROM p_common_metadata
            WHERE metamodel_api_key='item' AND dbc_varchar3 IS NOT NULL
              AND delete_flg=0 AND entity_api_key = ANY(%s)
            GROUP BY entity_api_key, dbc_varchar3 HAVING COUNT(*)>1
        """, (list(self.entities),))
        if rows:
            self.errors.append(
                f"[V6] dbColumn 重复: {[(r['entity_api_key'], r['dbc_varchar3'], r['cnt']) for r in rows[:5]]}")
        else:
            print("  ✅ dbColumn 唯一性通过")

    def _v7_pickoption(self):
        for ent in self.entities:
            sel = self._q("""
                SELECT api_key FROM p_common_metadata
                WHERE metamodel_api_key='item' AND entity_api_key=%s
                  AND dbc_int1 IN (4,16) AND delete_flg=0
            """, (ent,))
            if not sel:
                continue
            opts = self._q("""
                SELECT DISTINCT parent_metadata_api_key AS p FROM p_common_metadata
                WHERE metamodel_api_key='pickOption' AND entity_api_key=%s AND delete_flg=0
            """, (ent,))
            with_opts = {r['p'] for r in opts}
            missing = [r['api_key'] for r in sel if r['api_key'] not in with_opts]
            if missing:
                self.warnings.append(f"[V7] {ent}: {len(missing)} 个 SELECT 字段无 pickOption: {missing[:3]}")
            else:
                print(f"  ✅ {ent}: {len(sel)} 个 SELECT 字段全部有 pickOption")

    def _v8_busitype(self):
        rows = self._q("""
            SELECT entity_api_key, COUNT(*) AS cnt FROM p_common_metadata
            WHERE metamodel_api_key='busiType' AND entity_api_key = ANY(%s) AND delete_flg=0
            GROUP BY entity_api_key
        """, (list(self.entities),))
        bt = {r['entity_api_key']: r['cnt'] for r in rows}
        for ent in self.entities:
            if ent not in bt:
                self.warnings.append(f"[V8] {ent}: 无 busiType")
            else:
                print(f"  ✅ {ent}: {bt[ent]} 个 busiType")

    def _v9_prefix(self):
        rows = self._q("""
            SELECT entity_api_key, api_key, dbc_int1, dbc_varchar3
            FROM p_common_metadata
            WHERE metamodel_api_key='item' AND dbc_varchar3 IS NOT NULL
              AND delete_flg=0 AND entity_api_key = ANY(%s)
        """, (list(self.entities),))
        bad = []
        for r in rows:
            itype = r['dbc_int1']
            dcol = r['dbc_varchar3']
            exp = ITEM_TYPE_TO_BIZ_PREFIX.get(itype)
            if exp is None:
                continue
            prefix = ''.join(c for c in dcol if not c.isdigit()).rstrip('_')
            if prefix != exp:
                bad.append((r['entity_api_key'], r['api_key'], itype, dcol, exp))
        if bad:
            self.errors.append(f"[V9] dbColumn 前缀不一致: {len(bad)} 条, 示例: {bad[:3]}")
        else:
            print("  ✅ dbColumn 前缀与 itemType 全部一致")

    def _print_report(self):
        print(f"\n{'='*60}")
        print(f"验证完成: {len(self.errors)} FAIL, {len(self.warnings)} WARN")
        print('='*60)
        if self.errors:
            print("\n❌ 阻断项:")
            for e in self.errors:
                print(f"  {e}")
        if self.warnings:
            print("\n⚠️ 警告项:")
            for w in self.warnings:
                print(f"  {w}")
        if not self.errors and not self.warnings:
            print("\n✅ 全部通过")
