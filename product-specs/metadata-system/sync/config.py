"""
数据库连接配置和全局常量
"""

# ── 老库 PostgreSQL（元数据 + 业务数据）──
OLD_DB = dict(
    host='10.65.2.6', port=5432, dbname='crm_cd_data',
    user='xsy_metarepo', password='REDACTED_DB_PASSWORD',
    options='-c search_path=public,xsy_metarepo',
    connect_timeout=10
)

# ── 新库 MySQL（元数据仓库 Common）──
NEW_META_DB = dict(
    host='106.14.194.144', port=3306, db='paas_metarepo_common',
    user='root', password='REDACTED_DB_PASSWORD',
    charset='utf8mb4'
)

# ── 新库 PostgreSQL（业务数据）──
NEW_BIZ_DB = dict(
    host='10.65.2.6', port=5432, dbname='crm_cd_data',
    user='xsy_metarepo', password='REDACTED_DB_PASSWORD',
    options='-c search_path=public'
)

# ── 核心业务对象 ──
CORE_ENTITIES = [
    'account',         # 客户
    'lead',            # 线索
    'opportunity',     # 商机
    'product',         # 商品
    'salesOrder',      # 订单
    'contact',         # 联系人
    'salesOrderItem',  # 订单明细
    'user',            # 用户（从 p_user 迁移）
]

# ── 老表名映射 ──
OLD_TABLE_MAP = {
    'account':        ('a_account',          'account_name'),
    'lead':           ('a_lead',             'lead_name'),
    'opportunity':    ('a_opportunity',      'opportunity_name'),
    'product':        ('a_product',          'product_name'),
    'salesOrder':     ('a_sales_order',      'sales_order_name'),
    'contact':        ('a_contact',          'contact_name'),
    'salesOrderItem': ('a_sales_order_item', 'sales_order_item_name'),
    'user':           ('p_user',             'name'),
}

# ── 老→新 itemType 编码映射 ──
OLD_TO_NEW_ITEM_TYPE = {
    1: 1, 2: 8, 3: 4, 4: 16, 5: 2, 6: 10, 7: 3,
    10: 5, 21: 15, 22: 13, 23: 12, 24: 14, 26: 21,
    27: 6, 29: 19, 31: 9, 32: 18, 33: 11, 34: 17,
    38: 20, 39: 22, 40: 27, 41: 7,
}

# ── 老 itemType → 业务数据大宽表 dbColumnPrefix ──
# ⚠️ 注意：这里使用的是老系统 itemType 编码，不是 ItemTypeEnum 新编码！
# 老编码 2=数字, 3=日期, 4=单选, 5=查找关联, 10=货币 等
# 新编码 2=SELECT, 3=MULTI_SELECT, 5=NUMBER, 10=RELATION_SHIP 等
# 如需新编码映射请使用 NEW_ITEM_TYPE_TO_BIZ_PREFIX
OLD_ITEM_TYPE_TO_BIZ_PREFIX = {
    1: 'dbc_varchar',   2: 'dbc_bigint',    3: 'dbc_bigint',
    4: 'dbc_varchar',   5: 'dbc_bigint',    8: 'dbc_textarea',
    9: 'dbc_smallint',  10: 'dbc_decimal',  11: 'dbc_decimal',
    12: 'dbc_varchar',  13: 'dbc_varchar',  14: 'dbc_varchar',
    15: 'dbc_bigint',   16: 'dbc_array',    17: 'dbc_bigint',
    18: 'dbc_varchar',  19: 'dbc_varchar',  20: 'dbc_varchar',
    22: 'dbc_varchar',
}

# ── 新 ItemTypeEnum → 业务数据大宽表 dbColumnPrefix ──
NEW_ITEM_TYPE_TO_BIZ_PREFIX = {
    1: 'dbc_varchar',    # TEXT
    2: 'dbc_varchar',    # SELECT
    3: 'dbc_array',      # MULTI_SELECT
    4: 'dbc_textarea',   # TEXTAREA
    5: 'dbc_bigint',     # NUMBER
    6: 'dbc_decimal',    # CURRENCY
    7: 'dbc_bigint',     # DATE
    9: 'dbc_varchar',    # AUTONUMBER
    10: 'dbc_bigint',    # RELATION_SHIP
    11: 'dbc_bigint',    # NUMBER_OLD
    13: 'dbc_varchar',   # PHONE_OLD
    15: 'dbc_bigint',    # DATETIME_OLD
    16: 'dbc_varchar',   # MULTI_TAG
    22: 'dbc_varchar',   # PHONE
    23: 'dbc_varchar',   # EMAIL
    24: 'dbc_varchar',   # URL
    29: 'dbc_varchar',   # IMAGE
    31: 'dbc_smallint',  # BOOLEAN
    32: 'dbc_varchar',   # GEO
    33: 'dbc_decimal',   # PERCENT
    34: 'dbc_bigint',    # MULTI_RELATION
    38: 'dbc_bigint',    # DATETIME
    39: 'dbc_varchar',   # FILE
    40: 'dbc_textarea',  # RICHTEXT
    41: 'dbc_bigint',    # MASTER_DETAIL
}

# 向后兼容：保留旧变量名指向老编码映射
ITEM_TYPE_TO_BIZ_PREFIX = OLD_ITEM_TYPE_TO_BIZ_PREFIX

# 虚拟字段类型（不占物理列）
VIRTUAL_TYPES = {6, 7, 21, 27}

# 老 itemType 编码（不应出现在新库中）
OLD_ITEM_TYPE_CODES = {23, 24, 29, 32, 34, 38, 39, 40, 41, 99}

# 同步批次大小
BATCH_SIZE = 5000
INSERT_BATCH = 500

# 测试租户
TEST_TENANT_ID = 292193
