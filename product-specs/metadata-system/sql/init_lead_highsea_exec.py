#!/usr/bin/env python3
"""
初始化线索公海（leadHighSea）元数据 + 种子数据 + lead 公海字段补充。
在本地开发库执行。
"""
import psycopg2, psycopg2.extras, time, random

LOCAL = dict(host='127.0.0.1', port=5432, dbname='paas_db',
             user='postgres', password='123456', connect_timeout=5)
TENANT_ID = 292193
NOW = int(time.time() * 1000)

conn = psycopg2.connect(**LOCAL)
conn.autocommit = False
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

S_COMMON = 'paas_metarepo_common'
S_TENANT = 'paas_metarepo'
S_ENTITY = 'paas_entity_data'

def rid():
    return random.randint(10**15, 10**16 - 1)

print("=" * 60)
print("1. 注册 leadHighSea entity 元数据")
print("=" * 60)

# 检查是否已注册
cur.execute(f"""SELECT api_key FROM {S_COMMON}.p_common_metadata
    WHERE metamodel_api_key = 'entity' AND api_key = 'leadHighSea' AND delete_flg = 0""")
if cur.fetchone():
    print("  ⏭️  leadHighSea entity 已存在，跳过")
else:
    cur.execute(f"""INSERT INTO {S_COMMON}.p_common_metadata
        (id, metamodel_api_key, api_key, label, namespace, delete_flg,
         dbc_int1, dbc_smallint1, dbc_smallint2, dbc_smallint3,
         created_at, created_by, updated_at, updated_by)
        VALUES (%s, 'entity', 'leadHighSea', '线索公海', 'system', 0,
                0, 1, 0, 1,
                %s, 1, %s, 1)""", (rid(), NOW, NOW))
    print("  ✅ 注册 leadHighSea entity")

print("\n" + "=" * 60)
print("2. 注册 leadHighSea item 字段（12 个）")
print("=" * 60)

LEAD_HS_ITEMS = [
    # (apiKey, label, itemType, dataType, dbColumn)
    ('leadHighSeaName', '公海池名称',     1,  1, 'name'),
    ('assignRule',      '领取规则',       2,  1, 'dbc_smallint1'),
    ('recycleRule',     '回收规则',       2,  1, 'dbc_smallint2'),
    ('transferRule',    '转移规则',       2,  1, 'dbc_smallint3'),
    ('noActivitiesDay', '无跟进回收天数', 5,  3, 'dbc_bigint1'),
    ('noContactDay',    '无联系回收天数', 5,  3, 'dbc_bigint2'),
    ('remindDay',       '提前提醒天数',   5,  3, 'dbc_bigint3'),
    ('claimLimitDay',   '回收后禁领天数', 5,  3, 'dbc_bigint4'),
    ('releaseLimit',    '退回次数限制',   5,  3, 'dbc_bigint5'),
    ('claimMaxCount',   '每人最大持有数', 5,  3, 'dbc_bigint6'),
    ('enableFlg',       '是否启用',       31, 6, 'dbc_smallint4'),
    ('description',     '描述',           4,  5, 'dbc_textarea1'),
]

for apiKey, label, itemType, dataType, dbColumn in LEAD_HS_ITEMS:
    cur.execute(f"""SELECT api_key FROM {S_COMMON}.p_common_metadata
        WHERE metamodel_api_key = 'item' AND entity_api_key = 'leadHighSea'
          AND api_key = %s AND delete_flg = 0""", (apiKey,))
    if cur.fetchone():
        print(f"  ⏭️  {apiKey} 已存在")
        continue
    cur.execute(f"""INSERT INTO {S_COMMON}.p_common_metadata
        (id, metamodel_api_key, api_key, entity_api_key,
         dbc_int1, dbc_int2, dbc_varchar3, label, namespace, delete_flg,
         dbc_smallint2,
         created_at, created_by, updated_at, updated_by)
        VALUES (%s, 'item', %s, 'leadHighSea',
                %s, %s, %s, %s, 'system', 0,
                1,
                %s, 1, %s, 1)""",
        (rid(), apiKey, itemType, dataType, dbColumn, label, NOW, NOW))
    print(f"  ✅ {apiKey}: {label} ({dbColumn})")

print("\n" + "=" * 60)
print("3. 注册 leadHighSea busiType")
print("=" * 60)

cur.execute(f"""SELECT api_key FROM {S_COMMON}.p_common_metadata
    WHERE metamodel_api_key = 'busiType' AND entity_api_key = 'leadHighSea' AND delete_flg = 0""")
if cur.fetchone():
    print("  ⏭️  已存在")
else:
    cur.execute(f"""INSERT INTO {S_COMMON}.p_common_metadata
        (id, metamodel_api_key, api_key, entity_api_key,
         label, dbc_smallint1, namespace, delete_flg,
         created_at, created_by, updated_at, updated_by)
        VALUES (%s, 'busiType', 'defaultBusiType', 'leadHighSea',
                '默认业务类型', 1, 'system', 0,
                %s, 1, %s, 1)""", (rid(), NOW, NOW))
    print("  ✅ 注册 defaultBusiType")

print("\n" + "=" * 60)
print("4. 注册 leadHighSea pickOption")
print("=" * 60)

PICK_OPTIONS = [
    ('opt_self_claim',    'assignRule',   '自行领取'),
    ('opt_manual_assign', 'assignRule',   '手动分配'),
    ('opt_auto_recycle',  'recycleRule',  '自动回收'),
    ('opt_manual_recycle','recycleRule',  '手动回收'),
    ('opt_admin_only',    'transferRule', '仅管理员'),
    ('opt_member_can',    'transferRule', '成员可转移'),
]

for apiKey, itemApiKey, label in PICK_OPTIONS:
    cur.execute(f"""SELECT api_key FROM {S_COMMON}.p_common_metadata
        WHERE metamodel_api_key = 'pickOption' AND entity_api_key = 'leadHighSea'
          AND api_key = %s AND delete_flg = 0""", (apiKey,))
    if cur.fetchone():
        print(f"  ⏭️  {apiKey} 已存在")
        continue
    cur.execute(f"""INSERT INTO {S_COMMON}.p_common_metadata
        (id, metamodel_api_key, api_key, entity_api_key,
         label, dbc_varchar2, namespace, delete_flg,
         created_at, created_by, updated_at, updated_by)
        VALUES (%s, 'pickOption', %s, 'leadHighSea',
                %s, %s, 'system', 0,
                %s, 1, %s, 1)""",
        (rid(), apiKey, label, itemApiKey, NOW, NOW))
    print(f"  ✅ {apiKey}: {label}")

print("\n" + "=" * 60)
print("5. 补充 lead 公海关联字段（4 个）")
print("=" * 60)

LEAD_NEW_ITEMS = [
    ('leadHighSeaId',     '所属线索公海', 10, 3, 'dbc_bigint5',  'leadHighSea'),
    ('leadHighSeaStatus', '公海状态',     2,  1, 'dbc_varchar9', None),
    ('claimTime',         '认领日期',     7,  3, 'dbc_bigint6',  None),
    ('expireTime',        '到期时间',     7,  3, 'dbc_bigint7',  None),
]

for apiKey, label, itemType, dataType, dbColumn, referEntity in LEAD_NEW_ITEMS:
    cur.execute(f"""SELECT api_key FROM {S_COMMON}.p_common_metadata
        WHERE metamodel_api_key = 'item' AND entity_api_key = 'lead'
          AND api_key = %s AND delete_flg = 0""", (apiKey,))
    if cur.fetchone():
        print(f"  ⏭️  lead.{apiKey} 已存在")
        continue
    cur.execute(f"""INSERT INTO {S_COMMON}.p_common_metadata
        (id, metamodel_api_key, api_key, entity_api_key,
         dbc_int1, dbc_int2, dbc_varchar3, dbc_varchar1, label, namespace, delete_flg,
         dbc_smallint2,
         created_at, created_by, updated_at, updated_by)
        VALUES (%s, 'item', %s, 'lead',
                %s, %s, %s, %s, %s, 'system', 0,
                1,
                %s, 1, %s, 1)""",
        (rid(), apiKey, itemType, dataType, dbColumn, referEntity, label, NOW, NOW))
    print(f"  ✅ lead.{apiKey}: {label} ({dbColumn})")

print("\n" + "=" * 60)
print("6. 注册 lead 公海状态 pickOption")
print("=" * 60)

LEAD_STATUS_OPTIONS = [
    ('active',    'leadHighSeaStatus', '活跃'),
    ('inHighSea', 'leadHighSeaStatus', '公海中'),
    ('claimed',   'leadHighSeaStatus', '已领取'),
    ('converted', 'leadHighSeaStatus', '已转化'),
    ('invalid',   'leadHighSeaStatus', '无效'),
]

for apiKey, itemApiKey, label in LEAD_STATUS_OPTIONS:
    cur.execute(f"""SELECT api_key FROM {S_COMMON}.p_common_metadata
        WHERE metamodel_api_key = 'pickOption' AND entity_api_key = 'lead'
          AND api_key = %s AND dbc_varchar2 = %s AND delete_flg = 0""", (apiKey, itemApiKey))
    if cur.fetchone():
        print(f"  ⏭️  lead.{apiKey} 已存在")
        continue
    cur.execute(f"""INSERT INTO {S_COMMON}.p_common_metadata
        (id, metamodel_api_key, api_key, entity_api_key,
         label, dbc_varchar2, namespace, delete_flg,
         created_at, created_by, updated_at, updated_by)
        VALUES (%s, 'pickOption', %s, 'lead',
                %s, %s, 'system', 0,
                %s, 1, %s, 1)""",
        (rid(), apiKey, label, itemApiKey, NOW, NOW))
    print(f"  ✅ lead.{apiKey}: {label}")

print("\n" + "=" * 60)
print("7. 注册 entityLink")
print("=" * 60)

cur.execute(f"""SELECT api_key FROM {S_COMMON}.p_common_metadata
    WHERE metamodel_api_key = 'entityLink' AND api_key = 'leadHighSea_to_lead' AND delete_flg = 0""")
if cur.fetchone():
    print("  ⏭️  leadHighSea_to_lead 已存在")
else:
    cur.execute(f"""INSERT INTO {S_COMMON}.p_common_metadata
        (id, metamodel_api_key, api_key,
         dbc_varchar1, dbc_varchar2, dbc_varchar3, dbc_int1,
         label, namespace, delete_flg,
         created_at, created_by, updated_at, updated_by)
        VALUES (%s, 'entityLink', 'leadHighSea_to_lead',
                'leadHighSea', 'lead', 'leadHighSeaId', 0,
                '公海线索', 'system', 0,
                %s, 1, %s, 1)""", (rid(), NOW, NOW))
    print("  ✅ leadHighSea_to_lead")

print("\n" + "=" * 60)
print("8. 分配分表路由")
print("=" * 60)

cur.execute(f"""SELECT table_index FROM {S_ENTITY}.p_tenant_data_route
    WHERE tenant_id = %s AND entity_api_key = 'leadHighSea'""", (TENANT_ID,))
route = cur.fetchone()
if route:
    TI = route['table_index']
    print(f"  ⏭️  已有路由: p_tenant_data_{TI}")
else:
    # 找一个空闲的分片表
    cur.execute(f"""SELECT MAX(table_index) as mx FROM {S_ENTITY}.p_tenant_data_route
        WHERE tenant_id = %s""", (TENANT_ID,))
    mx = cur.fetchone()['mx'] or 0
    TI = mx + 1
    cur.execute(f"""INSERT INTO {S_ENTITY}.p_tenant_data_route
        (id, tenant_id, entity_api_key, table_index, delete_flg, created_at)
        VALUES (%s, %s, 'leadHighSea', %s, 0, %s)""",
        (rid(), TENANT_ID, TI, NOW))
    print(f"  ✅ 分配路由: p_tenant_data_{TI}")

print("\n" + "=" * 60)
print("9. 创建线索公海种子数据（5 个）")
print("=" * 60)

# 获取路由
cur.execute(f"""SELECT table_index FROM {S_ENTITY}.p_tenant_data_route
    WHERE tenant_id = %s AND entity_api_key = 'leadHighSea'""", (TENANT_ID,))
TI = cur.fetchone()['table_index']
TABLE = f"{S_ENTITY}.p_tenant_data_{TI}"

# 检查是否已有数据
cur.execute(f"SELECT COUNT(*) as cnt FROM {TABLE} WHERE entity_api_key = 'leadHighSea' AND delete_flg = 0")
existing = cur.fetchone()['cnt']
if existing > 0:
    print(f"  ⏭️  已有 {existing} 条数据，跳过")
else:
    # 获取部门 apiKey
    cur.execute(f"SELECT api_key FROM {S_TENANT}.p_tenant_department WHERE delete_flg = 0 AND tenant_id = %s LIMIT 1", (TENANT_ID,))
    dept = cur.fetchone()
    dept_ak = dept['api_key'] if dept else 'root'

    # 获取用户 ID
    cur.execute("SELECT id FROM paas_auth.p_user WHERE status = 1 AND (delete_flg IS NULL OR delete_flg = 0) LIMIT 1")
    user = cur.fetchone()
    uid = user['id'] if user else 1

    POOLS = [
        # (name, assignRule, recycleRule, transferRule, noAct, noContact, remind, claimLimit, releaseLimit, claimMax, dept)
        ("默认线索公海",   0, 0, 0, 15, 10, 3, 7,  5, 50,  'salesCenter'),
        ("VIP线索公海",    1, 1, 0, 0,  0,  0, 0,  0, 0,   'salesKA'),
        ("广告线索公海",   0, 0, 1, 7,  5,  2, 3,  3, 100, 'marketingCenter'),
        ("渠道线索公海",   0, 0, 0, 10, 7,  3, 5,  5, 80,  'salesChannel'),
        ("大客户线索公海", 1, 0, 0, 30, 20, 5, 10, 0, 30,  'salesKA'),
    ]

    for name, assign, recycle, transfer, noAct, noCont, remind, claimLim, relLim, claimMax, dept_key in POOLS:
        pool_id = rid()
        cur.execute(f"""INSERT INTO {TABLE}
            (id, tenant_id, entity_api_key, name, owner_id, depart_api_key,
             busitype_api_key, delete_flg, lock_status,
             dbc_smallint1, dbc_smallint2, dbc_smallint3, dbc_smallint4,
             dbc_bigint1, dbc_bigint2, dbc_bigint3, dbc_bigint4, dbc_bigint5, dbc_bigint6,
             created_at, created_by, updated_at, updated_by)
            VALUES (%s, %s, 'leadHighSea', %s, %s, %s,
                    'defaultBusiType', 0, 1,
                    %s, %s, %s, 1,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s)""",
            (pool_id, TENANT_ID, name, uid, dept_key,
             assign, recycle, transfer,
             noAct, noCont, remind, claimLim, relLim, claimMax,
             NOW, uid, NOW, uid))
        print(f"  ✅ {name} (id={pool_id}, dept={dept_key})")

print("\n" + "=" * 60)
print("10. 注册 dataPermission")
print("=" * 60)

cur.execute(f"""SELECT api_key FROM {S_COMMON}.p_common_metadata
    WHERE metamodel_api_key = 'dataPermission' AND entity_api_key = 'leadHighSea' AND delete_flg = 0""")
if cur.fetchone():
    print("  ⏭️  已存在")
else:
    cur.execute(f"""INSERT INTO {S_COMMON}.p_common_metadata
        (id, metamodel_api_key, api_key, entity_api_key,
         label, dbc_smallint1, dbc_smallint2, dbc_smallint3, namespace, delete_flg,
         created_at, created_by, updated_at, updated_by)
        VALUES (%s, 'dataPermission', 'leadHighSea', 'leadHighSea',
                '线索公海权限', 2, 2, 0, 'system', 0,
                %s, 1, %s, 1)""", (rid(), NOW, NOW))
    print("  ✅ 注册 dataPermission（全员可见）")

# ============================================================
# 提交
# ============================================================
conn.commit()
print("\n" + "=" * 60)
print("✅ 全部完成，已 COMMIT")
print("=" * 60)

# 验证
cur.execute(f"""SELECT COUNT(*) as cnt FROM {S_COMMON}.p_common_metadata
    WHERE metamodel_api_key = 'item' AND entity_api_key = 'leadHighSea' AND delete_flg = 0""")
print(f"  leadHighSea item 字段: {cur.fetchone()['cnt']} 个")

cur.execute(f"SELECT COUNT(*) as cnt FROM {TABLE} WHERE entity_api_key = 'leadHighSea' AND delete_flg = 0")
print(f"  leadHighSea 种子数据: {cur.fetchone()['cnt']} 条")

cur.execute(f"""SELECT COUNT(*) as cnt FROM {S_COMMON}.p_common_metadata
    WHERE metamodel_api_key = 'item' AND entity_api_key = 'lead'
      AND api_key IN ('leadHighSeaId','leadHighSeaStatus','claimTime','expireTime')
      AND delete_flg = 0""")
print(f"  lead 新增公海字段: {cur.fetchone()['cnt']} 个")

conn.close()
