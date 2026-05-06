#!/usr/bin/env python3
"""
Phase 2 核心: 行转换逻辑
将老库一行业务数据转换为新库格式
"""
import json
import logging
from decimal import Decimal, ROUND_HALF_UP

log = logging.getLogger(__name__)


class RowTransformer:
    """单行数据转换器"""

    def __init__(self, entity_api_key, column_map, mapping_builder):
        """
        entity_api_key: 对象 apiKey
        column_map: {apiKey: (oldCol, newCol, itemType)}
        mapping_builder: MappingBuilder 实例（提供 SELECT/busiType 映射）
        """
        self.entity = entity_api_key
        self.col_map = column_map
        self.mb = mapping_builder
        self.unmapped_log = []

    def transform(self, old_row, name_col='name'):
        """
        old_row: dict，老库一行数据
        name_col: 老库名称列名（如 account_name）
        返回: dict，新库一行数据
        """
        new = {}

        # ── 固定列 ──
        new['id'] = old_row.get('id')
        new['tenant_id'] = old_row.get('tenant_id')
        new['entity_api_key'] = self.entity
        new['name'] = old_row.get(name_col) or old_row.get('name')
        new['owner_id'] = old_row.get('owner_id')
        new['depart_id'] = old_row.get('dim_depart')
        new['delete_flg'] = old_row.get('del_flg', 0) or 0
        new['created_at'] = old_row.get('created_at')
        new['created_by'] = old_row.get('created_by')
        new['updated_at'] = old_row.get('updated_at')
        new['updated_by'] = old_row.get('updated_by')
        new['lock_status'] = old_row.get('lock_status', 1) or 1
        new['approval_status'] = old_row.get('approval_status')
        new['applicant_id'] = old_row.get('applicant_id')

        # ── busitype 转换 ──
        old_et = old_row.get('entity_type')
        if old_et:
            new['busitype_api_key'] = self.mb.get_busitype_apikey(self.entity, old_et)
        else:
            new['busitype_api_key'] = self.mb.default_busitype.get(self.entity)

        # ── 扩展列 ──
        for api_key, (old_col, new_col, item_type) in self.col_map.items():
            if new_col is None:
                continue  # 虚拟字段
            if old_col is None:
                continue  # 无老列映射

            old_val = old_row.get(old_col)
            if old_val is None:
                continue

            new_val = self._convert_value(api_key, item_type, old_val)
            if new_val is not None:
                new[new_col] = new_val

        return new

    def _convert_value(self, api_key, item_type, old_val):
        """按 itemType 转换值"""

        # SELECT(4): 数字→apiKey
        if item_type == 4:
            return self._convert_select(api_key, old_val)

        # MULTI_SELECT(16): 逗号分隔→JSON 数组
        if item_type == 16:
            return self._convert_multiselect(api_key, old_val)

        # BOOLEAN(9)
        if item_type == 9:
            return 1 if old_val in (1, True, '1', 'true') else 0

        # CURRENCY(10) / PERCENT(11)
        if item_type in (10, 11):
            try:
                return Decimal(str(old_val)).quantize(
                    Decimal('0.0001'), rounding=ROUND_HALF_UP)
            except Exception:
                return None

        # DATE(3) / DATETIME(15): 确保毫秒
        if item_type in (3, 15):
            try:
                ts = int(old_val)
                if 0 < ts < 10_000_000_000:
                    ts *= 1000
                return ts
            except (ValueError, TypeError):
                return None

        # NUMBER(2) / RELATION_SHIP(5) / MASTER_DETAIL(17): BIGINT
        if item_type in (2, 5, 17):
            try:
                return int(old_val)
            except (ValueError, TypeError):
                return None

        # TEXT(1)/EMAIL(12)/PHONE(13)/URL(14)/IMAGE(19)/GEO(18)/AUDIO(22)/AUTONUMBER(20)
        if item_type in (1, 12, 13, 14, 18, 19, 20, 22):
            return str(old_val)[:300]

        # TEXTAREA(8)
        if item_type == 8:
            return str(old_val)

        # 其他: 原样
        return old_val

    def _convert_select(self, api_key, old_val):
        if old_val is None or old_val == 0:
            return None
        try:
            code = int(old_val)
        except (ValueError, TypeError):
            return str(old_val)  # 已经是字符串
        result = self.mb.get_select_value(self.entity, api_key, code)
        if result == str(code):
            self.unmapped_log.append(('SELECT', self.entity, api_key, code))
        return result

    def _convert_multiselect(self, api_key, old_val):
        if not old_val:
            return None
        codes = [c.strip() for c in str(old_val).split(',') if c.strip()]
        api_keys = []
        for cs in codes:
            try:
                code = int(cs)
                ak = self.mb.get_select_value(self.entity, api_key, code)
                api_keys.append(ak)
            except ValueError:
                api_keys.append(cs)
        return json.dumps(api_keys)
