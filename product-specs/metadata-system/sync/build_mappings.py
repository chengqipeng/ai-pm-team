#!/usr/bin/env python3
"""
Phase 1: 构建映射表（全部走 PG）
"""
from .config import CORE_ENTITIES, VIRTUAL_TYPES
from .db import get_pg_dict


class MappingBuilder:
    def __init__(self, entities=None):
        self.entities = entities or CORE_ENTITIES
        self.column_map = {}
        self.select_map = {}
        self.busitype_map = {}
        self.default_busitype = {}

    def build_all(self):
        print("="*60)
        print("Phase 1: 构建映射表")
        print("="*60)
        conn, cur = get_pg_dict()
        try:
            self._build_column_map(cur)
            self._build_select_map(cur)
            self._build_busitype_map(cur)
        finally:
            cur.close()
            conn.close()
        self._print_summary()
        return self

    def _build_column_map(self, cur):
        print("\n[1/3] 构建列映射...")
        for ent in self.entities:
            cur.execute("""
                SELECT api_key, dbc_varchar3 AS db_column, dbc_int1 AS item_type
                FROM p_common_metadata
                WHERE metamodel_api_key='item' AND entity_api_key=%s
                  AND delete_flg=0 AND api_key IS NOT NULL
            """, (ent,))
            ent_map = {}
            for r in cur.fetchall():
                new_col = r['db_column']
                item_type = r['item_type']
                if item_type in VIRTUAL_TYPES:
                    new_col = None
                ent_map[r['api_key']] = (None, new_col, item_type)
            self.column_map[ent] = ent_map
            print(f"  {ent}: {len(ent_map)} 个字段映射")

        # 跳过老库 b_item 补充（网络不稳定时会卡住）
        # 如需补充 oldDbColumn，可单独运行 supplement_old_columns()

    def _build_select_map(self, cur):
        print("\n[2/3] 构建 SELECT 值映射...")
        for ent in self.entities:
            select_items = [ak for ak, (_, _, it) in self.column_map.get(ent, {}).items()
                            if it in (4, 16)]
            if not select_items:
                continue
            cur.execute("""
                SELECT parent_metadata_api_key AS item_ak,
                       dbc_int1 AS option_code, api_key AS option_ak
                FROM p_common_metadata
                WHERE metamodel_api_key='pickOption'
                  AND entity_api_key=%s AND delete_flg=0
                  AND dbc_int1 IS NOT NULL AND api_key IS NOT NULL
            """, (ent,))
            for r in cur.fetchall():
                key = (ent, r['item_ak'])
                self.select_map.setdefault(key, {})
                self.select_map[key][r['option_code']] = r['option_ak']
            mapped = sum(1 for si in select_items if (ent, si) in self.select_map)
            print(f"  {ent}: {mapped}/{len(select_items)} 个 SELECT 字段有映射")

    def _build_busitype_map(self, cur):
        print("\n[3/3] 构建 busiType 映射...")
        for ent in self.entities:
            cur.execute("""
                SELECT id, api_key, dbc_smallint2 AS default_flg
                FROM p_common_metadata
                WHERE metamodel_api_key='busiType' AND entity_api_key=%s AND delete_flg=0
            """, (ent,))
            ent_bt = {}
            default_ak = None
            for r in cur.fetchall():
                ent_bt[r['id']] = r['api_key']
                if r['default_flg'] == 1:
                    default_ak = r['api_key']
            self.busitype_map[ent] = ent_bt
            self.default_busitype[ent] = default_ak or (
                list(ent_bt.values())[0] if ent_bt else None)
            print(f"  {ent}: {len(ent_bt)} 个 busiType, 默认={self.default_busitype[ent]}")

    def _print_summary(self):
        print(f"\n{'='*60}")
        total_cols = sum(len(v) for v in self.column_map.values())
        total_opts = sum(len(v) for v in self.select_map.values())
        total_bt = sum(len(v) for v in self.busitype_map.values())
        print(f"  列映射: {total_cols} 个字段")
        print(f"  SELECT 映射: {total_opts} 个选项值")
        print(f"  busiType 映射: {total_bt} 个业务类型")

    def get_select_value(self, entity, item_apikey, code):
        mapping = self.select_map.get((entity, item_apikey), {})
        return mapping.get(code, str(code))

    def get_busitype_apikey(self, entity, old_id):
        mapping = self.busitype_map.get(entity, {})
        return mapping.get(old_id, self.default_busitype.get(entity))
