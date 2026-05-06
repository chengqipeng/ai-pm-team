-- ================================================================
-- 字段类型修正脚本
-- 日期：2026-04-28
-- 目标库：paas_metarepo_common（元数据）+ paas_entity_data（业务数据）
-- 执行方式：在 psql 中执行，或复制到数据库客户端
-- ================================================================

BEGIN;

-- ============================================================
-- 阶段 1：修正前快照（用于验证）
-- ============================================================

-- 保存修正前的状态到临时表
CREATE TEMP TABLE _fix_before AS
SELECT entity_api_key, api_key, dbc_int1 AS old_item_type, dbc_int2 AS old_data_type, dbc_varchar3 AS old_db_column
FROM p_common_metadata
WHERE metamodel_api_key = 'item'
  AND delete_flg = 0
  AND entity_api_key IN ('account', 'opportunity', 'lead')
  AND api_key IN (
    -- 动作一（20）
    'score','visitUnvisitDay','annualRevenue','longitude','latitude',
    'highSeaAccountSource','level','industryId','fState','fCity','fDistrict','highSeaStatus',
    'money','projectBudget','actualCost','discount','reason','status','standardPeriod','actualPeriod',
    -- 动作二（7）
    'claimTime','expireTime','closeDate','stageUpdatedAt','invoiceDate','paymentDate','customItem167__c',
    -- 动作三（5）
    'employeeNumber','doNotDisturb','recentActivityRecordTime','winRate','repeatFlg',
    -- 动作四（8）
    'opportunityType','winReason','commitmentFlg','forecastCategory','oppHealthAssessmentLevel',
    'leadChannel','leadQuality','bdType',
    -- 动作五（12）
    'customItem150__c','newOppFlg','customItem147__c','customItem153__c',
    'activeDays','gradeLabel','nameInitial','nameLenCategory',
    'wonRatioText','compositeGrade','processedName','srcFlg'
  );

-- ============================================================
-- 阶段 2：动作一 — 修正 itemType / dataType（20 个，无数据迁移）
-- ============================================================

-- account（12 个）
UPDATE p_common_metadata SET dbc_int1 = 5,  dbc_int2 = 3 WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'     AND api_key = 'score'                AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int1 = 27, dbc_int2 = 3 WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'     AND api_key = 'visitUnvisitDay'      AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int1 = 6,  dbc_int2 = 4 WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'     AND api_key = 'annualRevenue'        AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int1 = 6,  dbc_int2 = 3 WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'     AND api_key = 'longitude'            AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int1 = 6,  dbc_int2 = 3 WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'     AND api_key = 'latitude'             AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int1 = 2,  dbc_int2 = 1 WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'     AND api_key = 'highSeaAccountSource'  AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int1 = 2,  dbc_int2 = 1 WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'     AND api_key = 'level'                AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int1 = 2,  dbc_int2 = 1 WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'     AND api_key = 'industryId'           AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int1 = 2,  dbc_int2 = 1 WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'     AND api_key = 'fState'               AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int1 = 2,  dbc_int2 = 1 WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'     AND api_key = 'fCity'                AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int1 = 2,  dbc_int2 = 1 WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'     AND api_key = 'fDistrict'            AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int1 = 2,  dbc_int2 = 1 WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'     AND api_key = 'highSeaStatus'        AND delete_flg = 0;

-- opportunity（8 个）
UPDATE p_common_metadata SET dbc_int1 = 6,  dbc_int2 = 4 WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity' AND api_key = 'money'                AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int1 = 6,  dbc_int2 = 4 WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity' AND api_key = 'projectBudget'        AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int1 = 6,  dbc_int2 = 4 WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity' AND api_key = 'actualCost'           AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int1 = 33, dbc_int2 = 4 WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity' AND api_key = 'discount'             AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int1 = 2,  dbc_int2 = 1 WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity' AND api_key = 'reason'               AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int1 = 2,  dbc_int2 = 1 WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity' AND api_key = 'status'               AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int1 = 5,  dbc_int2 = 3 WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity' AND api_key = 'standardPeriod'       AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int1 = 5,  dbc_int2 = 3 WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity' AND api_key = 'actualPeriod'         AND delete_flg = 0;

-- ============================================================
-- 阶段 3：动作二 — 修正 dataType 声明（7 个，无数据迁移）
-- ============================================================

UPDATE p_common_metadata SET dbc_int2 = 3 WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'     AND api_key = 'claimTime'        AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int2 = 3 WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'     AND api_key = 'expireTime'       AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int2 = 3 WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity' AND api_key = 'closeDate'        AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int2 = 3 WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity' AND api_key = 'stageUpdatedAt'   AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int2 = 3 WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity' AND api_key = 'invoiceDate'      AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int2 = 3 WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity' AND api_key = 'paymentDate'      AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_int2 = 3 WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity' AND api_key = 'customItem167__c' AND delete_flg = 0;

-- ============================================================
-- 阶段 4：动作三 — 改 dbColumn + 数据迁移（5 个）
-- ⚠️ 注意：以 p_tenant_data_0 为例，多分片需逐表执行
-- ============================================================

-- 28. account.employeeNumber: dbc_bigint4 → dbc_varchar31
UPDATE paas_entity_data.p_tenant_data_0
SET dbc_varchar31 = dbc_bigint4::VARCHAR
WHERE entity_api_key = 'account' AND dbc_bigint4 IS NOT NULL AND delete_flg = 0;

UPDATE p_common_metadata
SET dbc_varchar3 = 'dbc_varchar31', dbc_int1 = 2, dbc_int2 = 1
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'employeeNumber' AND delete_flg = 0;

-- 29. account.doNotDisturb: dbc_varchar22 → dbc_smallint2
UPDATE paas_entity_data.p_tenant_data_0
SET dbc_smallint2 = CASE WHEN dbc_varchar22 IN ('true','1','yes') THEN 1 ELSE 0 END
WHERE entity_api_key = 'account' AND dbc_varchar22 IS NOT NULL AND delete_flg = 0;

UPDATE p_common_metadata
SET dbc_varchar3 = 'dbc_smallint2', dbc_int1 = 31, dbc_int2 = 6
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'doNotDisturb' AND delete_flg = 0;

-- 30. account.recentActivityRecordTime: dbc_varchar11 → dbc_bigint14
UPDATE paas_entity_data.p_tenant_data_0
SET dbc_bigint14 = dbc_varchar11::BIGINT
WHERE entity_api_key = 'account' AND dbc_varchar11 IS NOT NULL
  AND dbc_varchar11 ~ '^\d+$' AND delete_flg = 0;

UPDATE p_common_metadata
SET dbc_varchar3 = 'dbc_bigint14', dbc_int1 = 38, dbc_int2 = 3
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'recentActivityRecordTime' AND delete_flg = 0;

-- 31. opportunity.winRate: dbc_bigint7 → dbc_varchar6
UPDATE paas_entity_data.p_tenant_data_0
SET dbc_varchar6 = dbc_bigint7::VARCHAR
WHERE entity_api_key = 'opportunity' AND dbc_bigint7 IS NOT NULL AND delete_flg = 0;

UPDATE p_common_metadata
SET dbc_varchar3 = 'dbc_varchar6', dbc_int1 = 2, dbc_int2 = 1
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'winRate' AND delete_flg = 0;

-- 32. opportunity.repeatFlg: dbc_bigint20 → dbc_smallint1
UPDATE paas_entity_data.p_tenant_data_0
SET dbc_smallint1 = dbc_bigint20::SMALLINT
WHERE entity_api_key = 'opportunity' AND dbc_bigint20 IS NOT NULL AND delete_flg = 0;

UPDATE p_common_metadata
SET dbc_varchar3 = 'dbc_smallint1', dbc_int1 = 31, dbc_int2 = 6
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'repeatFlg' AND delete_flg = 0;

-- ============================================================
-- 阶段 5：动作四 — dbc_int 列迁移到合法列（8 个）
-- ============================================================

-- opportunity（5 个）
UPDATE p_common_metadata SET dbc_varchar3 = 'dbc_varchar9',  dbc_int1 = 2,  dbc_int2 = 1 WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity' AND api_key = 'opportunityType'          AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_varchar3 = 'dbc_varchar10', dbc_int1 = 2,  dbc_int2 = 1 WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity' AND api_key = 'winReason'                 AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_varchar3 = 'dbc_smallint2', dbc_int1 = 31, dbc_int2 = 6 WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity' AND api_key = 'commitmentFlg'             AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_varchar3 = 'dbc_varchar11', dbc_int1 = 2,  dbc_int2 = 1 WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity' AND api_key = 'forecastCategory'           AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_varchar3 = 'dbc_varchar12', dbc_int1 = 2,  dbc_int2 = 1 WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity' AND api_key = 'oppHealthAssessmentLevel'   AND delete_flg = 0;

-- lead（3 个）
UPDATE p_common_metadata SET dbc_varchar3 = 'dbc_varchar1',  dbc_int1 = 2,  dbc_int2 = 1 WHERE metamodel_api_key = 'item' AND entity_api_key = 'lead' AND api_key = 'leadChannel'  AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_varchar3 = 'dbc_varchar3',  dbc_int1 = 2,  dbc_int2 = 1 WHERE metamodel_api_key = 'item' AND entity_api_key = 'lead' AND api_key = 'leadQuality'  AND delete_flg = 0;
UPDATE p_common_metadata SET dbc_varchar3 = 'dbc_varchar4',  dbc_int1 = 2,  dbc_int2 = 1 WHERE metamodel_api_key = 'item' AND entity_api_key = 'lead' AND api_key = 'bdType'       AND delete_flg = 0;

-- ============================================================
-- 阶段 6：动作五 — 软删除废弃字段（12 个）
-- ============================================================

UPDATE p_common_metadata
SET delete_flg = 1, updated_at = EXTRACT(EPOCH FROM NOW()) * 1000
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key IN (
    'customItem150__c','newOppFlg','customItem147__c','customItem153__c',
    'activeDays','gradeLabel','nameInitial','nameLenCategory',
    'wonRatioText','compositeGrade','processedName','srcFlg'
  )
  AND delete_flg = 0;

-- ============================================================
-- 阶段 7：验证
-- ============================================================

-- 验证 1：对比修正前后，确认每个字段都被正确修改
SELECT
  b.entity_api_key,
  b.api_key,
  b.old_item_type,
  m.dbc_int1 AS new_item_type,
  b.old_data_type,
  m.dbc_int2 AS new_data_type,
  b.old_db_column,
  m.dbc_varchar3 AS new_db_column,
  m.delete_flg,
  CASE
    WHEN m.delete_flg = 1 THEN 'DELETED'
    WHEN b.old_item_type = m.dbc_int1 AND b.old_data_type = m.dbc_int2 AND b.old_db_column = m.dbc_varchar3 THEN 'UNCHANGED'
    ELSE 'MODIFIED'
  END AS change_status
FROM _fix_before b
JOIN p_common_metadata m
  ON m.metamodel_api_key = 'item'
  AND m.entity_api_key = b.entity_api_key
  AND m.api_key = b.api_key
ORDER BY b.entity_api_key, b.api_key;

-- 验证 2：检查是否还有 itemType 与 dbColumn 前缀不匹配的字段
WITH type_rules(item_type, expected_prefix) AS (VALUES
  (1,'dbc_varchar'),(2,'dbc_varchar'),(3,'dbc_array'),(4,'dbc_textarea'),
  (5,'dbc_bigint'),(6,'dbc_decimal'),(7,'dbc_bigint'),(9,'dbc_varchar'),
  (10,'dbc_bigint'),(11,'dbc_bigint'),(13,'dbc_varchar'),(15,'dbc_bigint'),
  (16,'dbc_varchar'),(22,'dbc_varchar'),(23,'dbc_varchar'),(24,'dbc_varchar'),
  (29,'dbc_varchar'),(31,'dbc_smallint'),(32,'dbc_varchar'),(33,'dbc_decimal'),
  (34,'dbc_bigint'),(38,'dbc_bigint'),(39,'dbc_varchar'),(40,'dbc_textarea'),
  (41,'dbc_bigint')
)
SELECT
  m.entity_api_key,
  m.api_key,
  m.dbc_int1 AS item_type,
  m.dbc_int2 AS data_type,
  m.dbc_varchar3 AS db_column,
  r.expected_prefix
FROM p_common_metadata m
JOIN type_rules r ON r.item_type = m.dbc_int1
WHERE m.metamodel_api_key = 'item'
  AND m.delete_flg = 0
  AND m.entity_api_key IN ('account','opportunity','lead')
  AND m.dbc_varchar3 IS NOT NULL
  AND m.dbc_int1 IS NOT NULL
  AND m.dbc_int1 NOT IN (8, 26, 27, 99)
  AND NOT (m.dbc_int1 = 10 AND m.dbc_int2 = 1)  -- 排除 RELATION_SHIP+VARCHAR 合法覆盖
  AND m.dbc_varchar3 NOT LIKE r.expected_prefix || '%'
ORDER BY m.entity_api_key, m.api_key;
-- 期望：0 行

-- 验证 3：检查是否还有引用 dbc_int 的字段
SELECT entity_api_key, api_key, dbc_varchar3 AS db_column
FROM p_common_metadata
WHERE metamodel_api_key = 'item' AND delete_flg = 0
  AND dbc_varchar3 LIKE 'dbc\_int%'
ORDER BY entity_api_key, api_key;
-- 期望：0 行

-- 验证 4：动作三数据迁移抽样检查
-- account.employeeNumber: 旧列 dbc_bigint4 vs 新列 dbc_varchar31
SELECT id, dbc_bigint4 AS old_val, dbc_varchar31 AS new_val
FROM paas_entity_data.p_tenant_data_0
WHERE entity_api_key = 'account' AND dbc_bigint4 IS NOT NULL
LIMIT 5;

-- account.doNotDisturb: 旧列 dbc_varchar22 vs 新列 dbc_smallint2
SELECT id, dbc_varchar22 AS old_val, dbc_smallint2 AS new_val
FROM paas_entity_data.p_tenant_data_0
WHERE entity_api_key = 'account' AND dbc_varchar22 IS NOT NULL
LIMIT 5;

-- account.recentActivityRecordTime: 旧列 dbc_varchar11 vs 新列 dbc_bigint14
SELECT id, dbc_varchar11 AS old_val, dbc_bigint14 AS new_val
FROM paas_entity_data.p_tenant_data_0
WHERE entity_api_key = 'account' AND dbc_varchar11 IS NOT NULL AND dbc_varchar11 ~ '^\d+$'
LIMIT 5;

-- opportunity.winRate: 旧列 dbc_bigint7 vs 新列 dbc_varchar6
SELECT id, dbc_bigint7 AS old_val, dbc_varchar6 AS new_val
FROM paas_entity_data.p_tenant_data_0
WHERE entity_api_key = 'opportunity' AND dbc_bigint7 IS NOT NULL
LIMIT 5;

-- opportunity.repeatFlg: 旧列 dbc_bigint20 vs 新列 dbc_smallint1
SELECT id, dbc_bigint20 AS old_val, dbc_smallint1 AS new_val
FROM paas_entity_data.p_tenant_data_0
WHERE entity_api_key = 'opportunity' AND dbc_bigint20 IS NOT NULL
LIMIT 5;

-- 验证 5：动作五软删除确认
SELECT entity_api_key, api_key, delete_flg
FROM p_common_metadata
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key IN (
    'customItem150__c','newOppFlg','customItem147__c','customItem153__c',
    'activeDays','gradeLabel','nameInitial','nameLenCategory',
    'wonRatioText','compositeGrade','processedName','srcFlg'
  );
-- 期望：12 行，全部 delete_flg = 1

-- 验证 6：统计修正结果
SELECT
  CASE
    WHEN m.delete_flg = 1 THEN 'DELETED'
    WHEN b.old_item_type != m.dbc_int1 OR b.old_data_type != m.dbc_int2 THEN 'TYPE_FIXED'
    WHEN b.old_db_column != m.dbc_varchar3 THEN 'COLUMN_MIGRATED'
    ELSE 'UNCHANGED'
  END AS fix_type,
  COUNT(*) AS cnt
FROM _fix_before b
JOIN p_common_metadata m
  ON m.metamodel_api_key = 'item'
  AND m.entity_api_key = b.entity_api_key
  AND m.api_key = b.api_key
GROUP BY 1
ORDER BY 1;
-- 期望：DELETED=12, TYPE_FIXED=27, COLUMN_MIGRATED=13, UNCHANGED=0

-- ============================================================
-- 确认无误后提交，否则 ROLLBACK
-- ============================================================

-- COMMIT;
-- 或
-- ROLLBACK;

DROP TABLE IF EXISTS _fix_before;
