#!/usr/bin/env python3
"""
字段类型修正执行脚本
目标库：PostgreSQL crm_cd_data（p_common_metadata + p_tenant_data 都在这里）
"""
import psycopg2
import psycopg2.extras

# ── 连接配置（与 sync/config.py OLD_DB 一致）──
PG_DB = dict(
    host='10.65.2.6', port=5432, dbname='crm_cd_data',
    user='xsy_metarepo', password='REDACTED_DB_PASSWORD',
    options='-c search_path=public,xsy_metarepo',
    connect_timeout=10,
)

def run():
    conn = psycopg2.connect(**PG_DB)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # ================================================================
    # 阶段 0：修正前快照
    # ================================================================
    target_keys = [
        'score','visitUnvisitDay','annualRevenue','longitude','latitude',
        'highSeaAccountSource','level','industryId','fState','fCity','fDistrict','highSeaStatus',
        'money','projectBudget','actualCost','discount','reason','status','standardPeriod','actualPeriod',
        'claimTime','expireTime','closeDate','stageUpdatedAt','invoiceDate','paymentDate','customItem167__c',
        'employeeNumber','doNotDisturb','recentActivityRecordTime','winRate','repeatFlg',
        'opportunityType','winReason','commitmentFlg','forecastCategory','oppHealthAssessmentLevel',
        'leadChannel','leadQuality','bdType',
        'customItem150__c','newOppFlg','customItem147__c','customItem153__c',
        'activeDays','gradeLabel','nameInitial','nameLenCategory',
        'wonRatioText','compositeGrade','processedName','srcFlg',
    ]

    snap_sql = """
        SELECT entity_api_key, api_key, dbc_int1, dbc_int2, dbc_varchar3, delete_flg
        FROM p_common_metadata
        WHERE metamodel_api_key = 'item'
          AND entity_api_key IN ('account','opportunity','lead')
          AND api_key = ANY(%s)
        ORDER BY entity_api_key, api_key
    """
    cur.execute(snap_sql, (target_keys,))
    before = {(r['entity_api_key'], r['api_key']): dict(r) for r in cur.fetchall()}

    print(f"=== 修正前快照：{len(before)} 条记录 ===")
    if len(before) == 0:
        print("❌ 未找到任何目标记录，请检查数据库连接和 search_path")
        conn.close()
        return

    for k in sorted(before.keys()):
        r = before[k]
        print(f"  {r['entity_api_key']:15s} {r['api_key']:35s} "
              f"itemType={str(r['dbc_int1']):5s} dataType={str(r['dbc_int2']):5s} "
              f"dbCol={str(r['dbc_varchar3']):20s} del={r['delete_flg']}")

    # ================================================================
    # 阶段 1：动作一 — 修正 itemType / dataType（20 个）
    # ================================================================
    print("\n=== 动作一：修正 itemType / dataType（20 个） ===")

    action1 = [
        ('account', 'score',                5,  3),
        ('account', 'visitUnvisitDay',      27, 3),
        ('account', 'annualRevenue',        6,  4),
        ('account', 'longitude',            6,  3),
        ('account', 'latitude',             6,  3),
        ('account', 'highSeaAccountSource', 2,  1),
        ('account', 'level',                2,  1),
        ('account', 'industryId',           2,  1),
        ('account', 'fState',               2,  1),
        ('account', 'fCity',                2,  1),
        ('account', 'fDistrict',            2,  1),
        ('account', 'highSeaStatus',        2,  1),
        ('opportunity', 'money',            6,  4),
        ('opportunity', 'projectBudget',    6,  4),
        ('opportunity', 'actualCost',       6,  4),
        ('opportunity', 'discount',         33, 4),
        ('opportunity', 'reason',           2,  1),
        ('opportunity', 'status',           2,  1),
        ('opportunity', 'standardPeriod',   5,  3),
        ('opportunity', 'actualPeriod',     5,  3),
    ]

    update_sql = """
        UPDATE p_common_metadata SET dbc_int1 = %s, dbc_int2 = %s
        WHERE metamodel_api_key = 'item' AND entity_api_key = %s
          AND api_key = %s AND delete_flg = 0
    """
    total_a1 = 0
    for entity, apiKey, it, dt in action1:
        cur.execute(update_sql, (it, dt, entity, apiKey))
        total_a1 += cur.rowcount
        s = '✅' if cur.rowcount == 1 else f'⚠️ rows={cur.rowcount}'
        print(f"  {s} {entity}.{apiKey}: itemType→{it}, dataType→{dt}")
    print(f"  合计 {total_a1} 行")

    # ================================================================
    # 阶段 2：动作二 — 修正 dataType 声明（7 个）
    # ================================================================
    print("\n=== 动作二：修正 dataType 声明（7 个） ===")

    action2 = [
        ('account',     'claimTime'),
        ('account',     'expireTime'),
        ('opportunity', 'closeDate'),
        ('opportunity', 'stageUpdatedAt'),
        ('opportunity', 'invoiceDate'),
        ('opportunity', 'paymentDate'),
        ('opportunity', 'customItem167__c'),
    ]

    total_a2 = 0
    for entity, apiKey in action2:
        cur.execute("UPDATE p_common_metadata SET dbc_int2 = 3 "
                    "WHERE metamodel_api_key = 'item' AND entity_api_key = %s "
                    "AND api_key = %s AND delete_flg = 0", (entity, apiKey))
        total_a2 += cur.rowcount
        s = '✅' if cur.rowcount == 1 else f'⚠️ rows={cur.rowcount}'
        print(f"  {s} {entity}.{apiKey}: dataType→3(BIGINT)")
    print(f"  合计 {total_a2} 行")

    # ================================================================
    # 阶段 3：动作三 — 改 dbColumn（5 个，元数据 + 业务数据）
    # ================================================================
    print("\n=== 动作三：改 dbColumn + 数据迁移（5 个） ===")

    update_col_sql = """
        UPDATE p_common_metadata SET dbc_varchar3 = %s, dbc_int1 = %s, dbc_int2 = %s
        WHERE metamodel_api_key = 'item' AND entity_api_key = %s
          AND api_key = %s AND delete_flg = 0
    """

    # 先查有哪些分片表
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'paas_entity_data'
          AND table_name LIKE 'p_tenant_data_%'
        ORDER BY table_name
    """)
    shard_tables = [r['table_name'] for r in cur.fetchall()]
    print(f"  发现 {len(shard_tables)} 个分片表: {shard_tables[:5]}...")

    migrations = [
        # (entity, apiKey, old_col, new_col, cast_expr, new_it, new_dt)
        ('account', 'employeeNumber', 'dbc_bigint4', 'dbc_varchar31',
         'dbc_bigint4::VARCHAR', 2, 1),
        ('account', 'doNotDisturb', 'dbc_varchar22', 'dbc_smallint2',
         "CASE WHEN dbc_varchar22 IN ('true','1','yes') THEN 1 ELSE 0 END", 31, 6),
        ('account', 'recentActivityRecordTime', 'dbc_varchar11', 'dbc_bigint14',
         'dbc_varchar11::BIGINT', 38, 3),
        ('opportunity', 'winRate', 'dbc_bigint7', 'dbc_varchar6',
         'dbc_bigint7::VARCHAR', 2, 1),
        ('opportunity', 'repeatFlg', 'dbc_bigint20', 'dbc_smallint1',
         'dbc_bigint20::SMALLINT', 31, 6),
    ]

    total_a3_data = 0
    total_a3_meta = 0
    for entity, apiKey, old_col, new_col, cast_expr, new_it, new_dt in migrations:
        # 数据迁移：逐分片表
        field_data_total = 0
        for tbl in shard_tables:
            extra_cond = ""
            if old_col == 'dbc_varchar11':
                extra_cond = " AND dbc_varchar11 ~ '^\\d+$'"
            mig_sql = (f"UPDATE paas_entity_data.{tbl} "
                       f"SET {new_col} = {cast_expr} "
                       f"WHERE entity_api_key = %s AND {old_col} IS NOT NULL "
                       f"AND delete_flg = 0{extra_cond}")
            cur.execute(mig_sql, (entity,))
            field_data_total += cur.rowcount
        total_a3_data += field_data_total

        # 元数据更新
        cur.execute(update_col_sql, (new_col, new_it, new_dt, entity, apiKey))
        total_a3_meta += cur.rowcount
        s = '✅' if cur.rowcount == 1 else f'⚠️ meta_rows={cur.rowcount}'
        print(f"  {s} {entity}.{apiKey}: {old_col}→{new_col}, 迁移 {field_data_total} 行数据")

    print(f"  合计: 元数据 {total_a3_meta} 行, 业务数据 {total_a3_data} 行")

    # ================================================================
    # 阶段 4：动作四 — dbc_int → 合法列（8 个）
    # ================================================================
    print("\n=== 动作四：dbc_int → 合法列（8 个） ===")

    # 先检查 dbc_int 列是否存在
    dbc_int_cols = []
    if shard_tables:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'paas_entity_data' AND table_name = %s
              AND column_name LIKE 'dbc\\_int%%'
            ORDER BY column_name
        """, (shard_tables[0],))
        dbc_int_cols = [r['column_name'] for r in cur.fetchall()]
    print(f"  大宽表 dbc_int 列: {dbc_int_cols if dbc_int_cols else '不存在（无分片表或无此列）'}")

    action4 = [
        ('opportunity', 'opportunityType',          'dbc_varchar9',   2,  1),
        ('opportunity', 'winReason',                'dbc_varchar10',  2,  1),
        ('opportunity', 'commitmentFlg',            'dbc_smallint2',  31, 6),
        ('opportunity', 'forecastCategory',         'dbc_varchar11',  2,  1),
        ('opportunity', 'oppHealthAssessmentLevel', 'dbc_varchar12',  2,  1),
        ('lead',        'leadChannel',              'dbc_varchar1',   2,  1),
        ('lead',        'leadQuality',              'dbc_varchar3',   2,  1),
        ('lead',        'bdType',                   'dbc_varchar4',   2,  1),
    ]

    total_a4 = 0
    for entity, apiKey, col, it, dt in action4:
        cur.execute(update_col_sql, (col, it, dt, entity, apiKey))
        total_a4 += cur.rowcount
        s = '✅' if cur.rowcount == 1 else f'⚠️ rows={cur.rowcount}'
        print(f"  {s} {entity}.{apiKey}: dbColumn→{col}, itemType→{it}, dataType→{dt}")

    # 如果 dbc_int 列存在，迁移数据
    if dbc_int_cols:
        print("  ⚠️ dbc_int 列存在，尝试迁移数据...")
        int_migrations = [
            ('opportunity', 'dbc_int1', 'dbc_varchar9'),
            ('opportunity', 'dbc_int8', 'dbc_varchar10'),
            ('opportunity', 'dbc_int3', 'dbc_smallint2'),
            ('opportunity', 'dbc_int7', 'dbc_varchar11'),
            ('opportunity', 'dbc_int9', 'dbc_varchar12'),
            ('lead', 'dbc_int7', 'dbc_varchar1'),
            ('lead', 'dbc_int10', 'dbc_varchar3'),
            ('lead', 'dbc_int11', 'dbc_varchar4'),
        ]
        for entity, old_c, new_c in int_migrations:
            if old_c not in dbc_int_cols:
                continue
            cast = f"{old_c}::SMALLINT" if new_c.startswith('dbc_smallint') else f"{old_c}::VARCHAR"
            for tbl in shard_tables:
                cur.execute(
                    f"UPDATE paas_entity_data.{tbl} SET {new_c} = {cast} "
                    f"WHERE entity_api_key = %s AND {old_c} IS NOT NULL AND delete_flg = 0",
                    (entity,))

    print(f"  合计 {total_a4} 行元数据")

    # ================================================================
    # 阶段 5：动作五 — 软删除废弃字段（12 个）
    # ================================================================
    print("\n=== 动作五：软删除废弃字段（12 个） ===")

    delete_keys = [
        'customItem150__c','newOppFlg','customItem147__c','customItem153__c',
        'activeDays','gradeLabel','nameInitial','nameLenCategory',
        'wonRatioText','compositeGrade','processedName','srcFlg',
    ]
    cur.execute("""
        UPDATE p_common_metadata
        SET delete_flg = 1, updated_at = EXTRACT(EPOCH FROM NOW())::BIGINT * 1000
        WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
          AND api_key = ANY(%s) AND delete_flg = 0
    """, (delete_keys,))
    total_a5 = cur.rowcount
    print(f"  软删除 {total_a5} 行（期望 12）")

    # ================================================================
    # 阶段 6：验证
    # ================================================================
    print("\n" + "=" * 60)
    print("验证阶段")
    print("=" * 60)

    # 验证 1：修正后快照对比
    cur.execute(snap_sql, (target_keys,))
    after = {(r['entity_api_key'], r['api_key']): dict(r) for r in cur.fetchall()}

    print(f"\n--- 验证 1：逐字段对比 ---")
    modified = deleted = unchanged = 0
    for k in sorted(after.keys()):
        a = after[k]
        b = before.get(k, {})
        if a['delete_flg'] == 1 and b.get('delete_flg', 0) == 0:
            deleted += 1
        elif (b.get('dbc_int1') != a['dbc_int1'] or b.get('dbc_int2') != a['dbc_int2']
              or b.get('dbc_varchar3') != a['dbc_varchar3']):
            modified += 1
        else:
            unchanged += 1

    print(f"  MODIFIED={modified}, DELETED={deleted}, UNCHANGED={unchanged}")

    # 验证 2：前缀匹配
    print("\n--- 验证 2：itemType 与 dbColumn 前缀匹配 ---")
    type_rules = {
        1:'dbc_varchar',2:'dbc_varchar',3:'dbc_array',4:'dbc_textarea',
        5:'dbc_bigint',6:'dbc_decimal',7:'dbc_bigint',9:'dbc_varchar',
        10:'dbc_bigint',11:'dbc_bigint',13:'dbc_varchar',15:'dbc_bigint',
        16:'dbc_varchar',22:'dbc_varchar',23:'dbc_varchar',24:'dbc_varchar',
        29:'dbc_varchar',31:'dbc_smallint',32:'dbc_varchar',33:'dbc_decimal',
        34:'dbc_bigint',38:'dbc_bigint',39:'dbc_varchar',40:'dbc_textarea',41:'dbc_bigint',
    }
    cur.execute("""
        SELECT entity_api_key, api_key, dbc_int1, dbc_int2, dbc_varchar3
        FROM p_common_metadata
        WHERE metamodel_api_key = 'item' AND delete_flg = 0
          AND entity_api_key IN ('account','opportunity','lead')
          AND dbc_varchar3 IS NOT NULL AND dbc_int1 IS NOT NULL
    """)
    mismatches = []
    for r in cur.fetchall():
        it = r['dbc_int1']
        if it in (8, 26, 27, 99):
            continue
        if it == 10 and r['dbc_int2'] == 1:
            continue
        exp = type_rules.get(it)
        if exp and r['dbc_varchar3'] and not r['dbc_varchar3'].startswith(exp):
            mismatches.append(r)

    if mismatches:
        # 过滤掉固定列（name, id 等非 dbc 前缀列）
        real_mismatches = [r for r in mismatches if r['dbc_varchar3'] and r['dbc_varchar3'].startswith('dbc_')]
        if real_mismatches:
            print(f"  ❌ {len(real_mismatches)} 个不匹配：")
            for r in real_mismatches:
                print(f"     {r['entity_api_key']}.{r['api_key']}: itemType={r['dbc_int1']}, dbCol={r['dbc_varchar3']}, 期望={type_rules.get(r['dbc_int1'])}")
        else:
            print(f"  ✅ 全部一致（{len(mismatches)} 个固定列字段已排除）")
        mismatches = real_mismatches
    else:
        print("  ✅ 全部一致")

    # 验证 3：dbc_int 引用（只检查目标三个实体）
    print("\n--- 验证 3：dbc_int 引用（account/opportunity/lead） ---")
    cur.execute("""
        SELECT entity_api_key, api_key, dbc_varchar3
        FROM p_common_metadata
        WHERE metamodel_api_key = 'item' AND delete_flg = 0
          AND entity_api_key IN ('account','opportunity','lead')
          AND dbc_varchar3 LIKE 'dbc\\_int%%'
    """)
    refs = cur.fetchall()
    if refs:
        print(f"  ❌ {len(refs)} 个 dbc_int 引用：")
        for r in refs:
            print(f"     {r['entity_api_key']}.{r['api_key']}: {r['dbc_varchar3']}")
    else:
        print("  ✅ 无 dbc_int 引用")

    # 验证 4：跳过（无分片表时无法验证业务数据）
    print("\n--- 验证 4：数据迁移抽样 ---")
    if not shard_tables:
        print("  ⏭️  无分片表，跳过业务数据验证")
    if shard_tables:
        samples = [
            ('account', 'dbc_bigint4', 'dbc_varchar31', 'employeeNumber'),
            ('account', 'dbc_varchar22', 'dbc_smallint2', 'doNotDisturb'),
            ('account', 'dbc_varchar11', 'dbc_bigint14', 'recentActivityRecordTime'),
            ('opportunity', 'dbc_bigint7', 'dbc_varchar6', 'winRate'),
            ('opportunity', 'dbc_bigint20', 'dbc_smallint1', 'repeatFlg'),
        ]
        for entity, old_c, new_c, label in samples:
            tbl = shard_tables[0]
            try:
                cur.execute(
                    f"SELECT COUNT(*) AS cnt FROM paas_entity_data.{tbl} "
                    f"WHERE entity_api_key = %s AND {old_c} IS NOT NULL AND delete_flg = 0",
                    (entity,))
                old_cnt = cur.fetchone()['cnt']
                cur.execute(
                    f"SELECT COUNT(*) AS cnt FROM paas_entity_data.{tbl} "
                    f"WHERE entity_api_key = %s AND {new_c} IS NOT NULL AND delete_flg = 0",
                    (entity,))
                new_cnt = cur.fetchone()['cnt']
                match = '✅' if new_cnt >= old_cnt else '⚠️'
                print(f"  {match} {label}: 旧列({old_c})={old_cnt}行, 新列({new_c})={new_cnt}行")
            except Exception as e:
                print(f"  ⚠️ {label}: 查询失败 - {e}")
                conn.rollback()  # reset transaction state after error

    # ================================================================
    # 决定提交还是回滚
    # ================================================================
    print("\n" + "=" * 60)
    all_ok = len(mismatches) == 0 and len(refs) == 0 and (modified + deleted) > 0
    total = total_a1 + total_a2 + total_a3_meta + total_a4 + total_a5

    if all_ok:
        conn.commit()
        print(f"✅ 验证通过，已 COMMIT（元数据 {total} 行 + 业务数据 {total_a3_data} 行）")
    else:
        conn.rollback()
        print(f"❌ 验证未通过，已 ROLLBACK")
        if mismatches:
            print(f"   原因：仍有 {len(mismatches)} 个前缀不匹配")
        if refs:
            print(f"   原因：仍有 {len(refs)} 个 dbc_int 引用")
        if unchanged > 0:
            print(f"   原因：{unchanged} 个字段未被修改")

    cur.close()
    conn.close()

if __name__ == '__main__':
    run()
