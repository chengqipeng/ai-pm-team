# 字段类型修正 — 执行 SQL

> 日期：2026-04-28
> 执行顺序：动作一 → 动作二 → 动作三 → 动作四 → 动作五
> 执行前提：在事务中执行，验证无误后 COMMIT

---

## 动作一：只改 itemType（20 个）

只更新 `dbc_int1`（itemType）和 `dbc_int2`（dataType），不迁移数据。

```sql
-- ============================================================
-- 动作一：修正 itemType / dataType（无数据迁移）
-- ============================================================

-- === account（12 个） ===

-- 1. score: 单选(2) → 整数(5)，分值是数字
UPDATE p_common_metadata
SET dbc_int1 = 5, dbc_int2 = 3
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'score' AND delete_flg = 0;

-- 2. visitUnvisitDay: 单选(2) → 计算(27)，天数由公式计算
UPDATE p_common_metadata
SET dbc_int1 = 27, dbc_int2 = 3
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'visitUnvisitDay' AND delete_flg = 0;

-- 3. annualRevenue: 关联(10) → 实数(6)，金额不是关联
UPDATE p_common_metadata
SET dbc_int1 = 6, dbc_int2 = 4
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'annualRevenue' AND delete_flg = 0;

-- 4. longitude: 关联(10) → 实数(6)，GPS 坐标
--    ⚠️ 注意：V2 目标是 dbc_decimal2，但当前列是 dbc_bigint7
--    这里先只改 itemType，dbColumn 迁移见动作三补充
UPDATE p_common_metadata
SET dbc_int1 = 6, dbc_int2 = 3
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'longitude' AND delete_flg = 0;

-- 5. latitude: 关联(10) → 实数(6)，GPS 坐标
--    ⚠️ 同上，V2 目标是 dbc_decimal3，当前列是 dbc_bigint9
UPDATE p_common_metadata
SET dbc_int1 = 6, dbc_int2 = 3
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'latitude' AND delete_flg = 0;

-- 6. highSeaAccountSource: 日期(3) → 单选(2)，来源渠道是单选
UPDATE p_common_metadata
SET dbc_int1 = 2, dbc_int2 = 1
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'highSeaAccountSource' AND delete_flg = 0;

-- 7. level: 文本域(4) → 单选(2)，等级 A/B/C/D
UPDATE p_common_metadata
SET dbc_int1 = 2, dbc_int2 = 1
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'level' AND delete_flg = 0;

-- 8. industryId: 文本域(4) → 单选(2)，行业
UPDATE p_common_metadata
SET dbc_int1 = 2, dbc_int2 = 1
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'industryId' AND delete_flg = 0;

-- 9. fState: 文本域(4) → 单选(2)，省份级联
UPDATE p_common_metadata
SET dbc_int1 = 2, dbc_int2 = 1
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'fState' AND delete_flg = 0;

-- 10. fCity: 文本域(4) → 单选(2)，市级联
UPDATE p_common_metadata
SET dbc_int1 = 2, dbc_int2 = 1
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'fCity' AND delete_flg = 0;

-- 11. fDistrict: 文本域(4) → 单选(2)，区级联
UPDATE p_common_metadata
SET dbc_int1 = 2, dbc_int2 = 1
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'fDistrict' AND delete_flg = 0;

-- 12. highSeaStatus: 文本域(4) → 单选(2)，公海状态
UPDATE p_common_metadata
SET dbc_int1 = 2, dbc_int2 = 1
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'highSeaStatus' AND delete_flg = 0;

-- === opportunity（8 个） ===

-- 13. money: 关联(10) → 实数(6)，销售金额
UPDATE p_common_metadata
SET dbc_int1 = 6, dbc_int2 = 4
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'money' AND delete_flg = 0;

-- 14. projectBudget: 关联(10) → 实数(6)，项目预算
UPDATE p_common_metadata
SET dbc_int1 = 6, dbc_int2 = 4
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'projectBudget' AND delete_flg = 0;

-- 15. actualCost: 关联(10) → 实数(6)，实际花费
UPDATE p_common_metadata
SET dbc_int1 = 6, dbc_int2 = 4
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'actualCost' AND delete_flg = 0;

-- 16. discount: 关联(10) → 百分比(33)，折扣率
UPDATE p_common_metadata
SET dbc_int1 = 33, dbc_int2 = 4
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'discount' AND delete_flg = 0;

-- 17. reason: 文本域(4) → 单选(2)，输单原因
UPDATE p_common_metadata
SET dbc_int1 = 2, dbc_int2 = 1
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'reason' AND delete_flg = 0;

-- 18. status: 文本域(4) → 单选(2)，商机状态
UPDATE p_common_metadata
SET dbc_int1 = 2, dbc_int2 = 1
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'status' AND delete_flg = 0;

-- 19. standardPeriod: 单选(2) → 整数(5)，周期天数
UPDATE p_common_metadata
SET dbc_int1 = 5, dbc_int2 = 3
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'standardPeriod' AND delete_flg = 0;

-- 20. actualPeriod: 单选(2) → 整数(5)，周期天数
UPDATE p_common_metadata
SET dbc_int1 = 5, dbc_int2 = 3
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'actualPeriod' AND delete_flg = 0;
```


---

## 动作二：只改 dataType 声明（7 个）

itemType 和 dbColumn 都正确，只是 dataType 声明为 VARCHAR(1) 而实际列是 BIGINT。

```sql
-- ============================================================
-- 动作二：修正 dataType 声明（无数据迁移）
-- ============================================================

-- === account（2 个） ===

-- 21. claimTime: dataType VARCHAR → BIGINT
UPDATE p_common_metadata
SET dbc_int2 = 3
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'claimTime' AND delete_flg = 0;

-- 22. expireTime: dataType VARCHAR → BIGINT
UPDATE p_common_metadata
SET dbc_int2 = 3
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'expireTime' AND delete_flg = 0;

-- === opportunity（5 个） ===

-- 23. closeDate: dataType VARCHAR → BIGINT
UPDATE p_common_metadata
SET dbc_int2 = 3
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'closeDate' AND delete_flg = 0;

-- 24. stageUpdatedAt: dataType VARCHAR → BIGINT
UPDATE p_common_metadata
SET dbc_int2 = 3
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'stageUpdatedAt' AND delete_flg = 0;

-- 25. invoiceDate: dataType VARCHAR → BIGINT
UPDATE p_common_metadata
SET dbc_int2 = 3
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'invoiceDate' AND delete_flg = 0;

-- 26. paymentDate: dataType VARCHAR → BIGINT
UPDATE p_common_metadata
SET dbc_int2 = 3
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'paymentDate' AND delete_flg = 0;

-- 27. customItem167__c: dataType VARCHAR → BIGINT
UPDATE p_common_metadata
SET dbc_int2 = 3
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'customItem167__c' AND delete_flg = 0;
```

---

## 动作三：改 dbColumn + 数据迁移（5 个）

需要分配新列号，迁移存量数据，更新元数据。

```sql
-- ============================================================
-- 动作三：改 dbColumn + 数据迁移
-- ============================================================

-- -------------------------------------------------------
-- 28. account.employeeNumber: dbc_bigint4 → dbc_varchar31
--     单选(2) 存 apiKey 字符串，不能写 bigint 列
--     account 已用 dbc_varchar: 1~22, 23~30 → 分配 31
-- -------------------------------------------------------

-- Step 1: 迁移数据（所有分片表都要执行，这里以分片 0 为例）
UPDATE paas_entity_data.p_tenant_data_0
SET dbc_varchar31 = dbc_bigint4::VARCHAR
WHERE entity_api_key = 'account'
  AND dbc_bigint4 IS NOT NULL
  AND delete_flg = 0;

-- Step 2: 更新元数据 dbColumn + itemType + dataType
UPDATE p_common_metadata
SET dbc_varchar3 = 'dbc_varchar31',  -- dbColumn
    dbc_int1 = 2,                     -- itemType = SELECT
    dbc_int2 = 1                      -- dataType = VARCHAR
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'employeeNumber' AND delete_flg = 0;

-- Step 3: 验证
-- SELECT id, dbc_bigint4, dbc_varchar31
-- FROM paas_entity_data.p_tenant_data_0
-- WHERE entity_api_key = 'account' AND dbc_bigint4 IS NOT NULL LIMIT 10;

-- -------------------------------------------------------
-- 29. account.doNotDisturb: dbc_varchar22 → dbc_smallint2
--     老布尔(9) 存字符串 → 新布尔(31) 存 SMALLINT
--     account 已用 dbc_smallint: 1, 3 → 分配 2
-- -------------------------------------------------------

UPDATE paas_entity_data.p_tenant_data_0
SET dbc_smallint2 = CASE
    WHEN dbc_varchar22 IN ('true', '1', 'yes') THEN 1
    ELSE 0
  END
WHERE entity_api_key = 'account'
  AND dbc_varchar22 IS NOT NULL
  AND delete_flg = 0;

UPDATE p_common_metadata
SET dbc_varchar3 = 'dbc_smallint2',
    dbc_int1 = 31,                    -- itemType = BOOLEAN
    dbc_int2 = 6                      -- dataType = SMALLINT
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'doNotDisturb' AND delete_flg = 0;

-- -------------------------------------------------------
-- 30. account.recentActivityRecordTime: dbc_varchar11 → dbc_bigint14
--     日期时间戳从 varchar 迁移到 bigint
--     account 已用 dbc_bigint: 1~13, 18~27, 30, 35 → 分配 14
-- -------------------------------------------------------

UPDATE paas_entity_data.p_tenant_data_0
SET dbc_bigint14 = dbc_varchar11::BIGINT
WHERE entity_api_key = 'account'
  AND dbc_varchar11 IS NOT NULL
  AND dbc_varchar11 ~ '^\d+$'        -- 只迁移纯数字的值
  AND delete_flg = 0;

UPDATE p_common_metadata
SET dbc_varchar3 = 'dbc_bigint14',
    dbc_int1 = 38,                    -- itemType = DATETIME
    dbc_int2 = 3                      -- dataType = BIGINT
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key = 'recentActivityRecordTime' AND delete_flg = 0;

-- -------------------------------------------------------
-- 31. opportunity.winRate: dbc_bigint7 → dbc_varchar6
--     单选(2) 存 apiKey 字符串，不能写 bigint 列
--     opportunity 已用 dbc_varchar: 1~5, 7~8 → 分配 6
-- -------------------------------------------------------

UPDATE paas_entity_data.p_tenant_data_0
SET dbc_varchar6 = dbc_bigint7::VARCHAR
WHERE entity_api_key = 'opportunity'
  AND dbc_bigint7 IS NOT NULL
  AND delete_flg = 0;

UPDATE p_common_metadata
SET dbc_varchar3 = 'dbc_varchar6',
    dbc_int1 = 2,                     -- itemType = SELECT
    dbc_int2 = 1                      -- dataType = VARCHAR
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'winRate' AND delete_flg = 0;

-- -------------------------------------------------------
-- 32. opportunity.repeatFlg: dbc_bigint20 → dbc_smallint1
--     布尔 0/1，从 bigint 迁移到 smallint
--     opportunity 已用 dbc_smallint: 无 → 分配 1
-- -------------------------------------------------------

UPDATE paas_entity_data.p_tenant_data_0
SET dbc_smallint1 = dbc_bigint20::SMALLINT
WHERE entity_api_key = 'opportunity'
  AND dbc_bigint20 IS NOT NULL
  AND delete_flg = 0;

UPDATE p_common_metadata
SET dbc_varchar3 = 'dbc_smallint1',
    dbc_int1 = 31,                    -- itemType = BOOLEAN
    dbc_int2 = 6                      -- dataType = SMALLINT
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'repeatFlg' AND delete_flg = 0;
```


---

## 动作四：从 dbc_int（不存在的列）迁移到合法列（8 个）

先检查老表是否有 dbc_int 列。如果有则迁移数据，如果没有则只更新元数据。

```sql
-- ============================================================
-- 动作四：预检查 — 确认 dbc_int 列是否存在
-- ============================================================

-- 在业务数据库执行，确认大宽表是否有 dbc_int 列
SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'paas_entity_data'
  AND table_name = 'p_tenant_data_0'
  AND column_name LIKE 'dbc\_int%'
ORDER BY column_name;

-- 如果返回空：说明列不存在，这些字段从未写入过数据，直接更新元数据即可
-- 如果返回有列：需要先迁移数据再更新元数据

-- ============================================================
-- 动作四-A：如果 dbc_int 列不存在（直接更新元数据）
-- ============================================================

-- === opportunity（5 个） ===

-- 33. opportunityType: dbc_int1 → dbc_varchar9
--     opportunity 已用 dbc_varchar: 1~8 → 分配 9
UPDATE p_common_metadata
SET dbc_varchar3 = 'dbc_varchar9',
    dbc_int1 = 2,                     -- itemType = SELECT
    dbc_int2 = 1                      -- dataType = VARCHAR
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'opportunityType' AND delete_flg = 0;

-- 34. winReason: dbc_int8 → dbc_varchar10
UPDATE p_common_metadata
SET dbc_varchar3 = 'dbc_varchar10',
    dbc_int1 = 2,                     -- itemType = SELECT
    dbc_int2 = 1                      -- dataType = VARCHAR
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'winReason' AND delete_flg = 0;

-- 35. commitmentFlg: dbc_int3 → dbc_smallint2
--     opportunity 已用 dbc_smallint: 1(repeatFlg) → 分配 2
UPDATE p_common_metadata
SET dbc_varchar3 = 'dbc_smallint2',
    dbc_int1 = 31,                    -- itemType = BOOLEAN
    dbc_int2 = 6                      -- dataType = SMALLINT
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'commitmentFlg' AND delete_flg = 0;

-- 36. forecastCategory: dbc_int7 → dbc_varchar11
UPDATE p_common_metadata
SET dbc_varchar3 = 'dbc_varchar11',
    dbc_int1 = 2,                     -- itemType = SELECT
    dbc_int2 = 1                      -- dataType = VARCHAR
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'forecastCategory' AND delete_flg = 0;

-- 37. oppHealthAssessmentLevel: dbc_int9 → dbc_varchar12
UPDATE p_common_metadata
SET dbc_varchar3 = 'dbc_varchar12',
    dbc_int1 = 2,                     -- itemType = SELECT
    dbc_int2 = 1                      -- dataType = VARCHAR
WHERE metamodel_api_key = 'item' AND entity_api_key = 'opportunity'
  AND api_key = 'oppHealthAssessmentLevel' AND delete_flg = 0;

-- === lead（3 个） ===

-- 38. leadChannel: dbc_int7 → dbc_varchar1
--     lead 已用 dbc_varchar: 2, 13, 15, 17~21, 23 → 分配 1
UPDATE p_common_metadata
SET dbc_varchar3 = 'dbc_varchar1',
    dbc_int1 = 2,                     -- itemType = SELECT
    dbc_int2 = 1                      -- dataType = VARCHAR
WHERE metamodel_api_key = 'item' AND entity_api_key = 'lead'
  AND api_key = 'leadChannel' AND delete_flg = 0;

-- 39. leadQuality: dbc_int10 → dbc_varchar3
--     lead 空闲 dbc_varchar: 3
--     注意：p_common_metadata 的 dbc_varchar3 列存的是 dbColumn 值
UPDATE p_common_metadata
SET dbc_varchar3 = 'dbc_varchar3',    -- dbColumn = dbc_varchar3（业务数据表的列名）
    dbc_int1 = 2,                     -- itemType = SELECT
    dbc_int2 = 1                      -- dataType = VARCHAR
WHERE metamodel_api_key = 'item' AND entity_api_key = 'lead'
  AND api_key = 'leadQuality' AND delete_flg = 0;

-- 40. bdType: dbc_int11 → dbc_varchar4
UPDATE p_common_metadata
SET dbc_varchar3 = 'dbc_varchar4',
    dbc_int1 = 2,                     -- itemType = SELECT
    dbc_int2 = 1                      -- dataType = VARCHAR
WHERE metamodel_api_key = 'item' AND entity_api_key = 'lead'
  AND api_key = 'bdType' AND delete_flg = 0;

-- ============================================================
-- 动作四-B：如果 dbc_int 列存在（先迁移数据再更新元数据）
-- ============================================================

-- 以 opportunity.opportunityType 为例：
-- UPDATE paas_entity_data.p_tenant_data_0
-- SET dbc_varchar9 = dbc_int1::VARCHAR
-- WHERE entity_api_key = 'opportunity'
--   AND dbc_int1 IS NOT NULL AND delete_flg = 0;
-- 然后执行上面动作四-A 的元数据更新 SQL
```

---

## 动作五：软删除废弃字段（12 个）

V2 已删除的字段，确认无业务依赖后软删除。

```sql
-- ============================================================
-- 动作五：软删除废弃字段
-- ============================================================

-- 41~50+: account 废弃字段
UPDATE p_common_metadata SET delete_flg = 1, updated_at = EXTRACT(EPOCH FROM NOW()) * 1000
WHERE metamodel_api_key = 'item' AND entity_api_key = 'account'
  AND api_key IN (
    'customItem150__c',     -- 自定义时间字段，A-必炸
    'newOppFlg',            -- 是否存在销售机会，可由汇总字段判断
    'customItem147__c',     -- 自定义百分比，无业务含义
    'customItem153__c',     -- 自定义布尔，无业务含义
    'activeDays',           -- 活跃天数，可由前端计算
    'gradeLabel',           -- AI 等级标签，可由前端计算
    'nameInitial',          -- 名称首字母，可由搜索引擎处理
    'nameLenCategory',      -- 名称长度分类，无业务价值
    'wonRatioText',         -- 赢单占比文本，可由前端格式化
    'compositeGrade',       -- 综合评级，可由前端计算
    'processedName',        -- 处理后名称，内部运维用
    'srcFlg'                -- 工商注册，非核心业务
  )
  AND delete_flg = 0;
```


---

## 执行后验证 SQL

```sql
-- ============================================================
-- 验证：检查是否还有 itemType 与 dbColumn 不匹配的字段
-- ============================================================

-- 规则：dbColumn 前缀必须与 itemType 的 defaultDataType 对应的 dbc 前缀一致
-- 以下查询找出所有不匹配的字段

WITH type_rules AS (
  -- itemType → 期望的 dbColumn 前缀
  SELECT 1 AS item_type, 'dbc_varchar' AS expected_prefix UNION ALL   -- TEXT
  SELECT 2, 'dbc_varchar' UNION ALL                                    -- SELECT
  SELECT 3, 'dbc_array' UNION ALL                                      -- MULTI_SELECT
  SELECT 4, 'dbc_textarea' UNION ALL                                   -- TEXTAREA
  SELECT 5, 'dbc_bigint' UNION ALL                                     -- NUMBER
  SELECT 6, 'dbc_decimal' UNION ALL                                    -- CURRENCY
  SELECT 7, 'dbc_bigint' UNION ALL                                     -- DATE
  SELECT 9, 'dbc_varchar' UNION ALL                                    -- AUTONUMBER
  SELECT 10, 'dbc_bigint' UNION ALL                                    -- RELATION_SHIP（默认，api_key 模式除外）
  SELECT 11, 'dbc_bigint' UNION ALL                                    -- NUMBER_OLD
  SELECT 13, 'dbc_varchar' UNION ALL                                   -- PHONE_OLD
  SELECT 15, 'dbc_bigint' UNION ALL                                    -- DATETIME_OLD
  SELECT 16, 'dbc_varchar' UNION ALL                                   -- MULTI_TAG
  SELECT 22, 'dbc_varchar' UNION ALL                                   -- PHONE
  SELECT 23, 'dbc_varchar' UNION ALL                                   -- EMAIL
  SELECT 24, 'dbc_varchar' UNION ALL                                   -- URL
  SELECT 29, 'dbc_varchar' UNION ALL                                   -- IMAGE
  SELECT 31, 'dbc_smallint' UNION ALL                                  -- BOOLEAN
  SELECT 32, 'dbc_varchar' UNION ALL                                   -- GEO
  SELECT 33, 'dbc_decimal' UNION ALL                                   -- PERCENT
  SELECT 34, 'dbc_bigint' UNION ALL                                    -- MULTI_RELATION
  SELECT 38, 'dbc_bigint' UNION ALL                                    -- DATETIME
  SELECT 39, 'dbc_varchar' UNION ALL                                   -- FILE
  SELECT 40, 'dbc_textarea' UNION ALL                                  -- RICHTEXT
  SELECT 41, 'dbc_bigint'                                              -- MASTER_DETAIL
)
SELECT
  m.entity_api_key,
  m.api_key,
  m.dbc_int1 AS item_type,
  m.dbc_int2 AS data_type,
  m.dbc_varchar3 AS db_column,
  r.expected_prefix,
  CASE
    WHEN m.dbc_varchar3 IS NULL THEN 'NO_COLUMN'
    WHEN m.dbc_varchar3 NOT LIKE r.expected_prefix || '%' THEN 'MISMATCH'
    ELSE 'OK'
  END AS status
FROM p_common_metadata m
JOIN type_rules r ON r.item_type = m.dbc_int1
WHERE m.metamodel_api_key = 'item'
  AND m.delete_flg = 0
  AND m.entity_api_key IN ('account', 'opportunity', 'lead')
  AND m.dbc_varchar3 IS NOT NULL
  AND m.dbc_int1 IS NOT NULL
  -- 排除虚拟字段（无物理列）
  AND m.dbc_int1 NOT IN (8, 26, 27, 99)
  -- 排除 RELATION_SHIP + VARCHAR 覆盖模式（合法的 api_key 关联）
  AND NOT (m.dbc_int1 = 10 AND m.dbc_int2 = 1)
HAVING CASE
    WHEN m.dbc_varchar3 NOT LIKE r.expected_prefix || '%' THEN 'MISMATCH'
    ELSE 'OK'
  END = 'MISMATCH'
ORDER BY m.entity_api_key, m.api_key;

-- 期望结果：0 行（所有字段都匹配）
```

```sql
-- ============================================================
-- 验证：检查是否还有引用 dbc_int 的字段
-- ============================================================

SELECT entity_api_key, api_key, dbc_varchar3 AS db_column, dbc_int1 AS item_type
FROM p_common_metadata
WHERE metamodel_api_key = 'item'
  AND delete_flg = 0
  AND dbc_varchar3 LIKE 'dbc\_int%'
ORDER BY entity_api_key, api_key;

-- 期望结果：0 行
```

---

## 执行检查清单

| 步骤 | 动作 | SQL 条数 | 影响行数 | 验证方式 |
|------|------|---------|---------|---------|
| 1 | 动作一：改 itemType | 20 条 UPDATE | 20 行 | 查询确认 dbc_int1/dbc_int2 值 |
| 2 | 动作二：改 dataType | 7 条 UPDATE | 7 行 | 查询确认 dbc_int2 值 |
| 3 | 动作三：数据迁移 | 5×2 条（迁移+元数据） | 视数据量 | 对比新旧列值一致 |
| 4 | 动作四预检查 | 1 条 SELECT | — | 确认 dbc_int 列是否存在 |
| 5 | 动作四：迁移/更新 | 8 条 UPDATE | 8 行 | 查询确认 dbc_varchar3 值 |
| 6 | 动作五：软删除 | 1 条 UPDATE | 12 行 | 查询确认 delete_flg=1 |
| 7 | 全量验证 | 2 条 SELECT | 期望 0 行 | 无不匹配字段 |

---

## 注意事项

1. **分片表**：动作三的数据迁移 SQL 以 `p_tenant_data_0` 为例，实际需要对所有分片表执行（`p_tenant_data_0` ~ `p_tenant_data_N`）
2. **Tenant 级元数据**：以上 SQL 只更新 `p_common_metadata`（Common 级）。如果 `p_tenant_item`（Tenant 级）中也有这些字段的覆盖记录，需要同步更新
3. **缓存清理**：元数据更新后需要清理 Redis 缓存（`EntityColumnResolver` 的列缓存 + 元数据合并读取缓存）
4. **前端发版**：动作一/二修正 itemType/dataType 后，前端组件渲染和值格式会变化，需要同步发版
5. **回退方案**：动作三的数据迁移不清空旧列，如需回退只需将元数据 dbColumn 改回旧值
