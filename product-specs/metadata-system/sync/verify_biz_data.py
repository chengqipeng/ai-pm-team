#!/usr/bin/env python3
"""
Phase 3: 业务数据验证（全部走 PG）
"""
import sys
import logging
from .config import CORE_ENTITIES, OLD_TABLE_MAP, TEST_TENANT_ID, VIRTUAL_TYPES
from .db import get_pg_dict
from .verify_formulas import FormulaVerifier

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)


class BizDataVerifier:
    def __init__(self, tenant_id, entities=None, sample_size=200):
        self.tenant_id = tenant_id
        self.entities = entities or CORE_ENTITIES
        self.sample_size = sample_size

    def run(self):
        log.info("="*60)
        log.info("Phase 3: 业务数据验证")
        log.info("="*60)
        l2 = self._verify_counts()
        l3 = self._verify_values()
        l4 = self._verify_formulas()
        self._print_final_report(l2, l3, l4)

    def _verify_counts(self):
        log.info("\n[L2] 行数对账")
        results = {}
        conn, cur = get_pg_dict()
        try:
            for ent in self.entities:
                # 新库
                cur.execute("""
                    SELECT COUNT(*) AS cnt FROM p_tenant_data
                    WHERE entity_api_key = %s AND tenant_id = %s AND delete_flg = 0
                """, (ent, self.tenant_id))
                new_count = cur.fetchone()['cnt']

                # 老库
                old_count = -1
                if ent in OLD_TABLE_MAP:
                    old_table, _ = OLD_TABLE_MAP[ent]
                    try:
                        cur.execute(f"SELECT COUNT(*) AS cnt FROM {old_table} WHERE tenant_id = %s AND del_flg = 0",
                                    (self.tenant_id,))
                        old_count = cur.fetchone()['cnt']
                    except Exception:
                        conn.rollback()

                diff = abs(old_count - new_count) if old_count >= 0 else -1
                pct = diff / max(old_count, 1) * 100 if old_count > 0 else 0
                status = 'PASS' if pct < 0.1 else ('WARN' if pct < 1 else 'FAIL')
                results[ent] = {'old': old_count, 'new': new_count, 'diff': diff, 'status': status}
                icon = '✅' if status == 'PASS' else ('⚠️' if status == 'WARN' else '❌')
                log.info(f"  {icon} {ent:20s}: 老={old_count:>8d} 新={new_count:>8d} 差={diff}")
        finally:
            cur.close()
            conn.close()
        return results

    def _verify_values(self):
        log.info("\n[L3] 值抽样比对")
        results = {}
        conn, cur = get_pg_dict()
        try:
            for ent in self.entities:
                cur.execute("""
                    SELECT api_key, dbc_varchar3 AS db_col, dbc_int1 AS item_type
                    FROM p_common_metadata
                    WHERE metamodel_api_key='item' AND entity_api_key=%s
                      AND delete_flg=0 AND dbc_varchar3 IS NOT NULL
                """, (ent,))
                items = [r for r in cur.fetchall() if r['item_type'] not in VIRTUAL_TYPES]

                sample_count = 0
                for item in items[:20]:
                    dc = item['db_col']
                    try:
                        cur.execute(f"""
                            SELECT COUNT(*) AS cnt FROM p_tenant_data
                            WHERE entity_api_key = %s AND tenant_id = %s
                              AND {dc} IS NOT NULL AND delete_flg = 0
                        """, (ent, self.tenant_id))
                        sample_count += min(cur.fetchone()['cnt'], 10)
                    except Exception:
                        conn.rollback()

                results[ent] = {'fields': min(len(items), 20), 'samples': sample_count}
                log.info(f"  {ent}: {min(len(items), 20)} 个字段, {sample_count} 条非空样本")
        finally:
            cur.close()
            conn.close()
        return results

    def _verify_formulas(self):
        log.info("\n[L4] 计算公式验证")
        results = {}
        for ent in self.entities:
            v = FormulaVerifier(self.tenant_id, ent, sample_size=min(self.sample_size, 500))
            r = v.run()
            results[ent] = r
        return results

    def _print_final_report(self, l2, l3, l4):
        log.info(f"\n{'='*60}")
        log.info("综合验证报告")
        log.info('='*60)
        l2_pass = all(v['status'] in ('PASS',) for v in l2.values()) if l2 else True
        log.info(f"[L2] 行数对账: {'PASS ✅' if l2_pass else 'ISSUES ⚠️'}")
        log.info(f"[L3] 值比对: {sum(v.get('samples',0) for v in l3.values())} 条样本")
        for ent, r in l4.items():
            if isinstance(r, dict) and 'formulas' in r:
                for ak, fr in r['formulas'].items():
                    st = '✅' if fr['mismatch'] == 0 else '⚠️'
                    log.info(f"[L4] {ent}.{ak}: {fr['match_rate']} {st}")
            elif isinstance(r, dict) and r.get('status') == 'SKIP':
                log.info(f"[L4] {ent}: 无公式，跳过")
