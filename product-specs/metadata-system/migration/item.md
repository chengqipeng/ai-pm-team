# item 元模型迁移方案

> 数据量：23,819 条 | Tenant 表：p_tenant_item

## 迁移内容

### 1. item_type 编码转换（3,333 条）

```sql
UPDATE p_common_metadata SET dbc_int1 = CASE dbc_int1
    WHEN 23 THEN 12   -- EMAIL
    WHEN 24 THEN 14   -- URL
    WHEN 29 THEN 19   -- IMAGE
    WHEN 32 THEN 18   -- GEOLOCATION
    WHEN 34 THEN 17   -- MASTER_DETAIL
    WHEN 38 THEN 20   -- AUTONUMBER
    WHEN 39 THEN 22   -- AUDIO
    WHEN 40 THEN 27   -- COMPUTED
    WHEN 41 THEN 7    -- ROLLUP
    ELSE dbc_int1
END
WHERE metamodel_api_key = 'item'
  AND dbc_int1 IN (23, 24, 29, 32, 34, 38, 39, 40, 41);
```

### 2. db_column 重新分配（23,819 条）

```
规则：
1. 按 entity_api_key 分组
2. 每个 entity 内按 item_order 排序
3. 根据 itemType 查找 dbColumnPrefix
4. 同一 entity 内同前缀递增分配：dbc_varchar1, dbc_varchar2, ...
5. FORMULA/ROLLUP/JOIN/COMPUTED → NULL（不占物理列）
```

```sql
-- 清空不占物理列的类型
UPDATE p_common_metadata SET dbc_varchar3 = NULL
WHERE metamodel_api_key = 'item' AND dbc_int1 IN (6, 7, 21, 27);
-- 详见 sql/fix_item_db_column_values.sql
```

### 3. api_key 命名统一（24 个字段）

```sql
-- is* → *Flg / camelCase
UPDATE p_meta_item SET api_key = 'customFlg' WHERE metamodel_api_key = 'item' AND api_key = 'isCustom';
UPDATE p_meta_item SET api_key = 'deleteFlg' WHERE metamodel_api_key = 'item' AND api_key = 'isDeleted';
UPDATE p_meta_item SET api_key = 'detailFlg' WHERE metamodel_api_key = 'item' AND api_key = 'isDetail';
UPDATE p_meta_item SET api_key = 'copyWithParentFlg' WHERE metamodel_api_key = 'item' AND api_key = 'isCopyWithParent';
UPDATE p_meta_item SET api_key = 'externalFlg' WHERE metamodel_api_key = 'item' AND api_key = 'isExternal';
UPDATE p_meta_item SET api_key = 'currencyFlg' WHERE metamodel_api_key = 'item' AND api_key = 'isCurrency';
UPDATE p_meta_item SET api_key = 'multiCurrencyFlg' WHERE metamodel_api_key = 'item' AND api_key = 'isMultiCurrency';
UPDATE p_meta_item SET api_key = 'computeMultiCurrencyUnit' WHERE metamodel_api_key = 'item' AND api_key = 'isComputeMultiCurrencyUnit';
UPDATE p_meta_item SET api_key = 'computeMultiCurrencyFlg' WHERE metamodel_api_key = 'item' AND api_key = 'isComputeMultiCurrency';
UPDATE p_meta_item SET api_key = 'rebuildFlg' WHERE metamodel_api_key = 'item' AND api_key = 'isRebuild';
UPDATE p_meta_item SET api_key = 'maskFlg' WHERE metamodel_api_key = 'item' AND api_key = 'isMask';

-- enable* → *Flg
UPDATE p_meta_item SET api_key = 'historyLogFlg' WHERE metamodel_api_key = 'item' AND api_key IN ('enableHistoryLog', 'enable_history_log');
UPDATE p_meta_item SET api_key = 'deactivateFlg' WHERE metamodel_api_key = 'item' AND api_key IN ('enableDeactive', 'enableDeactivate');
UPDATE p_meta_item SET api_key = 'referItemFilterFlg' WHERE metamodel_api_key = 'item' AND api_key IN ('referItemFilterEnable', 'enableReferItemFilter');
UPDATE p_meta_item SET api_key = 'watermarkTimeFlg' WHERE metamodel_api_key = 'item' AND api_key = 'enableWatermarkTime';
UPDATE p_meta_item SET api_key = 'watermarkLoginUserFlg' WHERE metamodel_api_key = 'item' AND api_key = 'enableWatermarkLoginUser';
UPDATE p_meta_item SET api_key = 'watermarkLocationFlg' WHERE metamodel_api_key = 'item' AND api_key = 'enableWatermarkLocation';
UPDATE p_meta_item SET api_key = 'watermarkJoinFieldFlg' WHERE metamodel_api_key = 'item' AND api_key = 'enableWatermarkJoinField';
UPDATE p_meta_item SET api_key = 'configFlg', item_type = 31, data_type = 6 WHERE metamodel_api_key = 'item' AND api_key IN ('enableConfig', 'enable_config');
UPDATE p_meta_item SET api_key = 'packageFlg', item_type = 31, data_type = 6 WHERE metamodel_api_key = 'item' AND api_key IN ('enablePackage', 'enable_package');

-- 缺 Flg 后缀
UPDATE p_meta_item SET api_key = 'encryptFlg' WHERE metamodel_api_key = 'item' AND api_key = 'encrypt';
UPDATE p_meta_item SET api_key = 'markdownFlg' WHERE metamodel_api_key = 'item' AND api_key = 'markdown';
UPDATE p_meta_item SET api_key = 'compoundFlg' WHERE metamodel_api_key = 'item' AND api_key = 'compound';
UPDATE p_meta_item SET api_key = 'compoundSubFlg' WHERE metamodel_api_key = 'item' AND api_key = 'compoundSub';
```

### 4. globalPickItem 字段值迁移（ID → apiKey）

```sql
UPDATE p_common_metadata cm
INNER JOIN p_tenant_global_pickitem gp ON cm.dbc_varchar10 = CAST(gp.id AS CHAR)
SET cm.dbc_varchar10 = gp.api_key
WHERE cm.metamodel_api_key = 'item'
  AND cm.dbc_varchar10 IS NOT NULL
  AND cm.dbc_varchar10 REGEXP '^[0-9]+$';
```

### 5. 关联字段标准化

| 老字段名 | 新字段名 | 说明 |
|:---|:---|:---|
| referEntityIds | referEntityApiKeys | ID→apiKey |
| isExternalId | （删除） | 不再使用 |
