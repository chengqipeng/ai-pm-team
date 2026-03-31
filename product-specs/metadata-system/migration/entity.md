# entity 元模型迁移方案

> 数据量：873 条 | Tenant 表：p_tenant_entity

## 迁移内容

### 1. api_key 命名统一（16 个字段）

```sql
-- snake_case → camelCase
UPDATE p_meta_item SET api_key = 'svgApiKey' WHERE metamodel_api_key = 'entity' AND api_key = 'svg_api_key';
UPDATE p_meta_item SET api_key = 'dbTable' WHERE metamodel_api_key = 'entity' AND api_key = 'db_table';
UPDATE p_meta_item SET api_key = 'entityType' WHERE metamodel_api_key = 'entity' AND api_key = 'entity_type';
UPDATE p_meta_item SET api_key = 'customEntitySeq' WHERE metamodel_api_key = 'entity' AND api_key = 'custom_entity_seq';
UPDATE p_meta_item SET api_key = 'businessCategory' WHERE metamodel_api_key = 'entity' AND api_key = 'business_category';
UPDATE p_meta_item SET api_key = 'enableFlg' WHERE metamodel_api_key = 'entity' AND api_key = 'enable_flg';
UPDATE p_meta_item SET api_key = 'customFlg' WHERE metamodel_api_key = 'entity' AND api_key = 'custom_flg';

-- enable* → *Flg
UPDATE p_meta_item SET api_key = 'historyLogFlg' WHERE metamodel_api_key = 'entity' AND api_key IN ('enable_history_log', 'enableHistoryLog');
UPDATE p_meta_item SET api_key = 'configFlg', item_type = 31, data_type = 6 WHERE metamodel_api_key = 'entity' AND api_key IN ('enable_config', 'enableConfig');
UPDATE p_meta_item SET api_key = 'busiTypeFlg' WHERE metamodel_api_key = 'entity' AND api_key IN ('enable_busitype', 'enableBusinessType', 'businessTypeFlg');
UPDATE p_meta_item SET api_key = 'checkRuleFlg' WHERE metamodel_api_key = 'entity' AND api_key IN ('enable_checkrule', 'enableCheckRule');
UPDATE p_meta_item SET api_key = 'flowFlg', item_type = 31, data_type = 6 WHERE metamodel_api_key = 'entity' AND api_key IN ('enable_flow', 'enableFlow');
UPDATE p_meta_item SET api_key = 'packageFlg', item_type = 31, data_type = 6 WHERE metamodel_api_key = 'entity' AND api_key IN ('enable_package', 'enablePackage');
UPDATE p_meta_item SET api_key = 'searchableFlg' WHERE metamodel_api_key = 'entity' AND api_key = 'searchable';
UPDATE p_meta_item SET api_key = 'scriptExecutorFlg' WHERE metamodel_api_key = 'entity' AND api_key IN ('enable_script_executor', 'enableScriptExecutor');
UPDATE p_meta_item SET api_key = 'groupMemberFlg' WHERE metamodel_api_key = 'entity' AND api_key IN ('enable_group_member', 'enableGroupMember');
UPDATE p_meta_item SET api_key = 'dynamicFeedFlg' WHERE metamodel_api_key = 'entity' AND api_key IN ('enable_dynamic_feed', 'enableDynamicFeed');
UPDATE p_meta_item SET api_key = 'duplicateRuleFlg' WHERE metamodel_api_key = 'entity' AND api_key IN ('enable_duplicaterule', 'enableDuplicateRule');

-- is* → *Flg
UPDATE p_meta_item SET api_key = 'archivedFlg' WHERE metamodel_api_key = 'entity' AND api_key = 'is_archived';
```

### 2. item_type/data_type 修正（布尔字段统一为 31,6）

```sql
UPDATE p_meta_item SET item_type = 31, data_type = 6
WHERE metamodel_api_key = 'entity'
  AND api_key IN ('duplicateRuleFlg', 'scriptExecutorFlg', 'archivedFlg', 'groupMemberFlg', 'dynamicFeedFlg');
```

### 3. 验证

```sql
-- 无 snake_case 残留
SELECT * FROM p_meta_item WHERE metamodel_api_key = 'entity' AND api_key LIKE '%\_%';
-- 无 enable*/is* 前缀残留
SELECT * FROM p_meta_item WHERE metamodel_api_key = 'entity' AND (api_key LIKE 'enable%' OR api_key LIKE 'is%') AND api_key NOT IN ('enableFlg', 'enableConfig');
-- 所有 *Flg 字段 item_type=31
SELECT * FROM p_meta_item WHERE metamodel_api_key = 'entity' AND api_key LIKE '%Flg' AND item_type != 31;
```
