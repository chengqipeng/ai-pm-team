-- ================================================================
-- 线索公海（leadHighSea）实体初始化
-- ================================================================

-- 1. 注册 entity
INSERT INTO p_common_metadata
    (metamodel_api_key, api_key, entity_api_key, dbc_varchar1, dbc_int1, delete_flg,
     created_at, created_by, updated_at, updated_by)
VALUES
    ('entity', 'leadHighSea', NULL, '线索公海', 0, 0,
     EXTRACT(EPOCH FROM NOW())::BIGINT * 1000, 1,
     EXTRACT(EPOCH FROM NOW())::BIGINT * 1000, 1);

-- 2. 注册 item 字段定义（12 个）
INSERT INTO p_common_metadata
    (metamodel_api_key, api_key, entity_api_key,
     dbc_int1, dbc_int2, dbc_varchar3, dbc_varchar30,
     delete_flg, created_at, created_by, updated_at, updated_by)
VALUES
    -- dbc_int1=itemType, dbc_int2=dataType, dbc_varchar3=dbColumn, dbc_varchar30=label
    ('item', 'leadHighSeaName',  'leadHighSea', 1,  1, 'name',          '公海池名称',     0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('item', 'assignRule',       'leadHighSea', 2,  1, 'dbc_smallint1', '领取规则',       0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('item', 'recycleRule',      'leadHighSea', 2,  1, 'dbc_smallint2', '回收规则',       0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('item', 'transferRule',     'leadHighSea', 2,  1, 'dbc_smallint3', '转移规则',       0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('item', 'noActivitiesDay',  'leadHighSea', 5,  3, 'dbc_bigint1',   '无跟进回收天数',  0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('item', 'noContactDay',     'leadHighSea', 5,  3, 'dbc_bigint2',   '无联系回收天数',  0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('item', 'remindDay',        'leadHighSea', 5,  3, 'dbc_bigint3',   '提前提醒天数',    0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('item', 'claimLimitDay',    'leadHighSea', 5,  3, 'dbc_bigint4',   '回收后禁领天数',  0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('item', 'releaseLimit',     'leadHighSea', 5,  3, 'dbc_bigint5',   '退回次数限制',    0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('item', 'claimMaxCount',    'leadHighSea', 5,  3, 'dbc_bigint6',   '每人最大持有数',  0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('item', 'enableFlg',        'leadHighSea', 31, 6, 'dbc_smallint4', '是否启用',       0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('item', 'description',      'leadHighSea', 4,  5, 'dbc_textarea1', '描述',          0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1);

-- 3. 注册默认业务类型
INSERT INTO p_common_metadata
    (metamodel_api_key, api_key, entity_api_key,
     dbc_varchar1, dbc_smallint1, delete_flg,
     created_at, created_by, updated_at, updated_by)
VALUES
    ('busiType', 'defaultBusiType', 'leadHighSea',
     '默认业务类型', 1, 0,
     EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1);

-- 4. 注册 pickOption（领取/回收/转移规则选项）
-- 复用 highSea 的 pickOption（apiKey 相同，entity_api_key 不同）
INSERT INTO p_common_metadata
    (metamodel_api_key, api_key, entity_api_key,
     dbc_varchar1, dbc_varchar2, dbc_int1, delete_flg,
     created_at, created_by, updated_at, updated_by)
VALUES
    ('pickOption', 'opt_self_claim',    'leadHighSea', '自行领取',   'assignRule',   0, 0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('pickOption', 'opt_manual_assign', 'leadHighSea', '手动分配',   'assignRule',   1, 0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('pickOption', 'opt_auto_recycle',  'leadHighSea', '自动回收',   'recycleRule',  0, 0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('pickOption', 'opt_manual_recycle','leadHighSea', '手动回收',   'recycleRule',  1, 0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('pickOption', 'opt_admin_only',    'leadHighSea', '仅管理员',   'transferRule', 0, 0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('pickOption', 'opt_member_can',    'leadHighSea', '成员可转移', 'transferRule', 1, 0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1);

-- ================================================================
-- 线索（lead）字段修正 — 新增公海关联字段
-- ================================================================

-- 新增 leadHighSeaId（关联线索公海）
INSERT INTO p_common_metadata
    (metamodel_api_key, api_key, entity_api_key,
     dbc_int1, dbc_int2, dbc_varchar3, dbc_varchar30, dbc_varchar1,
     delete_flg, created_at, created_by, updated_at, updated_by)
VALUES
    ('item', 'leadHighSeaId',     'lead', 10, 3, 'dbc_bigint5',  '所属线索公海', 'leadHighSea', 0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('item', 'leadHighSeaStatus', 'lead', 2,  1, 'dbc_varchar9', '公海状态',     NULL,          0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('item', 'claimTime',         'lead', 7,  3, 'dbc_bigint6',  '认领日期',     NULL,          0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('item', 'expireTime',        'lead', 7,  3, 'dbc_bigint7',  '到期时间',     NULL,          0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1);

-- 线索公海状态 pickOption
INSERT INTO p_common_metadata
    (metamodel_api_key, api_key, entity_api_key,
     dbc_varchar1, dbc_varchar2, delete_flg,
     created_at, created_by, updated_at, updated_by)
VALUES
    ('pickOption', 'active',    'lead', '活跃',   'leadHighSeaStatus', 0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('pickOption', 'inHighSea', 'lead', '公海中', 'leadHighSeaStatus', 0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('pickOption', 'claimed',   'lead', '已领取', 'leadHighSeaStatus', 0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('pickOption', 'converted', 'lead', '已转化', 'leadHighSeaStatus', 0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1),
    ('pickOption', 'invalid',   'lead', '无效',   'leadHighSeaStatus', 0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1);

-- ================================================================
-- entityLink 关联定义
-- ================================================================

INSERT INTO p_common_metadata
    (metamodel_api_key, api_key, entity_api_key,
     dbc_varchar1, dbc_varchar2, dbc_varchar3, dbc_int1,
     delete_flg, created_at, created_by, updated_at, updated_by)
VALUES
    -- dbc_varchar1=parentEntityApiKey, dbc_varchar2=childEntityApiKey,
    -- dbc_varchar3=referItemApiKey, dbc_int1=cascadeDelete
    ('entityLink', 'leadHighSea_to_lead', NULL,
     'leadHighSea', 'lead', 'leadHighSeaId', 0,
     0, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1, EXTRACT(EPOCH FROM NOW())::BIGINT*1000, 1);
