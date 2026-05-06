#!/usr/bin/env python3
"""
Phase 2: 全量同步引擎
按租户×entity 分批同步业务数据
"""
import sys
import time
import logging
from .config import (CORE_ENTITIES, OLD_TABLE_MAP, BATCH_SIZE,
                     INSERT_BATCH, TEST_TENANT_ID)
from .db import get_pg, get_pg_dict
from .build_mappings import MappingBuilder
from .transform import RowTransformer

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)


class BizDataSyncer:
    """业务数据同步引擎"""

    def __init__(self, tenant_id, entities=None):
        self.tenant_id = tenant_id
        self.entities = entities or CORE_ENTITIES
        self.mb = None
        self.stats = {}

    def run(self):
        log.info("="*60)
        log.info("Phase 2: 业务数据全量同步")
        log.info(f"租户: {self.tenant_id}, 对象: {self.entities}")
        log.info("="*60)

        # 1. 构建映射表
        self.mb = MappingBuilder(self.entities)
        self.mb.build_all()

        # 2. 按依赖顺序同步
        sync_order = self._get_sync_order()
        for entity in sync_order:
            if entity in self.entities:
                self._sync_entity(entity)

        # 3. 输出报告
        self._print_report()

    def _get_sync_order(self):
        """按关联依赖排序"""
        return [
            # 第 1 批: 无外部依赖
            'account', 'product', 'lead',
            # 第 2 批: 依赖第 1 批
            'contact', 'opportunity',
            # 第 3 批: 依赖第 1、2 批
            'salesOrder', 'salesOrderItem',
        ]

    def _sync_entity(self, entity_api_key):
        if entity_api_key not in OLD_TABLE_MAP:
            log.warning(f"[{entity_api_key}] 无老表映射，跳过")
            return

        old_table, name_col = OLD_TABLE_MAP[entity_api_key]
        col_map = self.mb.column_map.get(entity_api_key, {})
        transformer = RowTransformer(entity_api_key, col_map, self.mb)

        log.info(f"\n{'─'*40}")
        log.info(f"同步 {entity_api_key} (老表: {old_table})")

        old_conn, old_cur = get_pg_dict()
        new_conn = get_pg()
        new_cur = new_conn.cursor()

        try:
            # 统计老库数据量
            old_cur.execute(f"""
                SELECT COUNT(*) FROM {old_table}
                WHERE tenant_id = %s AND del_flg = 0
            """, (self.tenant_id,))
            total = old_cur.fetchone()['count']
            log.info(f"  老库数据量: {total}")

            synced = 0
            last_id = 0
            start_time = time.time()

            while True:
                # 分页读取
                old_cur.execute(f"""
                    SELECT * FROM {old_table}
                    WHERE tenant_id = %s AND del_flg = 0 AND id > %s
                    ORDER BY id LIMIT %s
                """, (self.tenant_id, last_id, BATCH_SIZE))
                rows = old_cur.fetchall()
                if not rows:
                    break

                # 转换
                new_rows = []
                for old_row in rows:
                    new_row = transformer.transform(dict(old_row), name_col)
                    new_rows.append(new_row)

                # 批量写入
                self._batch_insert(new_cur, 'p_tenant_data', new_rows)
                new_conn.commit()

                last_id = rows[-1]['id']
                synced += len(rows)

                if synced % 10000 == 0:
                    elapsed = time.time() - start_time
                    speed = synced / elapsed if elapsed > 0 else 0
                    log.info(f"  进度: {synced}/{total} ({synced/max(total,1)*100:.1f}%), "
                             f"速度: {speed:.0f} 行/秒")

            elapsed = time.time() - start_time
            self.stats[entity_api_key] = {
                'old_count': total, 'synced': synced,
                'elapsed': elapsed,
                'unmapped': len(transformer.unmapped_log)
            }
            log.info(f"  ✅ 完成: {synced}/{total}, 耗时 {elapsed:.1f}s, "
                     f"未映射值 {len(transformer.unmapped_log)} 个")

            if transformer.unmapped_log[:5]:
                log.warning(f"  未映射值示例: {transformer.unmapped_log[:5]}")

        except Exception as e:
            log.error(f"  ❌ 同步失败: {e}")
            new_conn.rollback()
            raise
        finally:
            old_cur.close()
            old_conn.close()
            new_cur.close()
            new_conn.close()

    def _batch_insert(self, cur, table, rows):
        """批量 INSERT"""
        if not rows:
            return
        columns = list(rows[0].keys())
        # 过滤 None 值的列（只保留有值的列）
        col_str = ', '.join(columns)
        placeholders = ', '.join(['%s'] * len(columns))
        sql = f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING"

        for i in range(0, len(rows), INSERT_BATCH):
            batch = rows[i:i+INSERT_BATCH]
            values = [tuple(row.get(c) for c in columns) for row in batch]
            try:
                cur.executemany(sql, values)
            except Exception as e:
                # 降级: 逐行插入
                log.warning(f"  批量插入失败，降级逐行: {e}")
                for row in batch:
                    try:
                        vals = tuple(row.get(c) for c in columns)
                        cur.execute(sql, vals)
                    except Exception as e2:
                        log.error(f"  行插入失败 id={row.get('id')}: {e2}")

    def _print_report(self):
        log.info(f"\n{'='*60}")
        log.info("同步报告")
        log.info('='*60)
        total_synced = 0
        for ent, s in self.stats.items():
            log.info(f"  {ent:20s}: {s['synced']:>8d}/{s['old_count']:<8d} "
                     f"({s['elapsed']:.1f}s, 未映射={s['unmapped']})")
            total_synced += s['synced']
        log.info(f"  {'合计':20s}: {total_synced:>8d}")


def main():
    tenant_id = int(sys.argv[1]) if len(sys.argv) > 1 else TEST_TENANT_ID
    entities = sys.argv[2:] if len(sys.argv) > 2 else None
    syncer = BizDataSyncer(tenant_id, entities)
    syncer.run()


if __name__ == '__main__':
    main()
