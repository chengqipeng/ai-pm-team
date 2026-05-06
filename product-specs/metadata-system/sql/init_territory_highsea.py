#!/usr/bin/env python3
"""初始化区域公海：territory 新增字段 + lead 新增关联字段 + 种子数据"""
import psycopg2, psycopg2.extras, time, random

LOCAL = dict(host='127.0.0.1', port=5432, dbname='paas_db', user='postgres', password='123456')
TENANT_ID = 292193
NOW = int(time.time() * 1000)
S_COMMON = 'paas_metarepo_common'
S_ENTITY = 'paas_entity_data'

conn = psycopg2.connect(**LOCAL)
conn.autocommit = False
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

def rid():
    return random.randint(10**15, 10**16 - 1)

def add_item(entity, apiKey, label, itemType, dataType, dbColumn, referEntity=None):
    cur.execute(f"""SELECT api_key FROM {S_COMMON}.p_common_metadata
        WHERE metamodel_api_key = 'item' AND entity_api_key = %s AND api_key = %s AND delete_flg = 0""",
        (entity, apiKey))
    if cur.fetchone():
        print(f"  skip {entity}.{apiKey}")
        return
    cur.execute(f"""INSERT INTO {S_COMMON}.p_common_metadata
        (id, metamodel_api_key, api_key, entity_api_key,
         dbc_int1, dbc_int2, dbc_varchar3, dbc_varchar1, label, namespace, delete_flg, dbc_smallint2,
         created_at, created_by, updated_at, updated_by)
        VALUES (%s, 'item', %s, %s, %s, %s, %s, %s, %s, 'system', 0, 1, %s, 1, %s, 1)""",
        (rid(), apiKey, entity, itemType, dataType, dbColumn, referEntity, label, NOW, NOW))
    print(f"  + {entity}.{apiKey}: {label} ({dbColumn})")

print("=" * 60)
print("1. territory 新增字段")
print("=" * 60)
add_item('territory', 'accountHighSeaFlg', '客户区域公海', 31, 6, 'dbc_smallint4')
add_item('territory', 'leadHighSeaFlg', '线索区域公海', 31, 6, 'dbc_smallint5')
add_item('territory', 'noContactDay', '无联系回收天数', 5, 3, 'dbc_bigint7')
add_item('territory', 'claimMaxCount', '每人最大持有数', 5, 3, 'dbc_bigint8')
add_item('territory', 'description', '描述', 4, 5, 'dbc_textarea1')

print("\n" + "=" * 60)
print("2. lead 新增区域公海关联字段")
print("=" * 60)
add_item('lead', 'territoryLeadHighSeaId', '所属区域线索公海', 10, 3, 'dbc_bigint16', 'territory')

# lead 的 pickOption 补充（如果 leadHighSeaStatus 还没有 territoryAssigned 选项）
# 暂不加，复用现有的 active/inHighSea/claimed 状态

print("\n" + "=" * 60)
print("3. entityLink")
print("=" * 60)
cur.execute(f"""SELECT api_key FROM {S_COMMON}.p_common_metadata
    WHERE metamodel_api_key = 'entityLink' AND api_key = 'territory_to_lead_highsea' AND delete_flg = 0""")
if cur.fetchone():
    print("  skip territory_to_lead_highsea")
else:
    cur.execute(f"""INSERT INTO {S_COMMON}.p_common_metadata
        (id, metamodel_api_key, api_key, dbc_varchar1, dbc_varchar2, dbc_varchar3, dbc_int1,
         label, namespace, delete_flg, created_at, created_by, updated_at, updated_by)
        VALUES (%s, 'entityLink', 'territory_to_lead_highsea',
                'territory', 'lead', 'territoryLeadHighSeaId', 0,
                '区域线索公海', 'system', 0, %s, 1, %s, 1)""", (rid(), NOW, NOW))
    print("  + territory_to_lead_highsea")

print("\n" + "=" * 60)
print("4. 更新 territory 种子数据（标记区域公海开关）")
print("=" * 60)

cur.execute("""SELECT table_index FROM paas_entity_data.p_tenant_data_route
    WHERE tenant_id = %s AND entity_api_key = 'territory'""", (TENANT_ID,))
route = cur.fetchone()
if not route:
    print("  ERROR: territory 无路由")
else:
    ti = route['table_index']
    tbl = f"{S_ENTITY}.p_tenant_data_{ti}"

    cur.execute(f"SELECT id, name FROM {tbl} WHERE entity_api_key='territory' AND delete_flg=0 ORDER BY name")
    territories = cur.fetchall()
    print(f"  现有 territory: {len(territories)} 条")

    # 按名称匹配设置公海开关
    flag_map = {}
    for t in territories:
        n = t['name'] or ''
        # 默认不开启
        acct_flg, lead_flg = 0, 0
        if '华北' in n:
            acct_flg, lead_flg = 1, 1
        elif '华东' in n:
            acct_flg, lead_flg = 1, 1
        elif '华南' in n:
            acct_flg, lead_flg = 1, 0
        elif '西部' in n or '西' in n:
            acct_flg, lead_flg = 0, 1
        flag_map[t['id']] = (acct_flg, lead_flg, n)

    for tid, (af, lf, name) in flag_map.items():
        cur.execute(f"""UPDATE {tbl}
            SET dbc_smallint4 = %s, dbc_smallint5 = %s, updated_at = %s
            WHERE id = %s""", (af, lf, NOW, tid))
        if af or lf:
            print(f"  {name}: accountHighSea={af}, leadHighSea={lf}")

conn.commit()
print("\n" + "=" * 60)
print("DONE")
print("=" * 60)

# 验证
cur.execute(f"""SELECT COUNT(*) as cnt FROM {S_COMMON}.p_common_metadata
    WHERE metamodel_api_key = 'item' AND entity_api_key = 'territory' AND delete_flg = 0""")
print(f"  territory item 字段: {cur.fetchone()['cnt']} 个")

cur.execute(f"""SELECT COUNT(*) as cnt FROM {S_COMMON}.p_common_metadata
    WHERE metamodel_api_key = 'item' AND entity_api_key = 'lead'
      AND api_key = 'territoryLeadHighSeaId' AND delete_flg = 0""")
print(f"  lead.territoryLeadHighSeaId: {'exists' if cur.fetchone()['cnt'] > 0 else 'MISSING'}")

conn.close()
