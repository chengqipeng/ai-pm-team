# checkRule 元模型迁移方案

> 数据量：待统计 | Tenant 表：p_tenant_check_rule

## 迁移内容

### 1. 关联字段标准化（ID → apiKey）

| 老字段名 | 新字段名 | 说明 |
|:---|:---|:---|
| object_id | entity_api_key | db_column 统一使用 apiKey |
| ruleLabel | label | 统一使用基类字段名 |
| ruleLabelKey | labelKey | 统一使用基类字段名 |
| name | （删除） | 冗余字段，label 已替代 |

### 2. item_type/data_type 修正（布尔字段统一为 31,6）

```sql
UPDATE p_meta_item SET item_type = 31, data_type = 6
WHERE metamodel_api_key = 'checkRule'
  AND api_key IN ('activeFlg', 'checkAllItemsFlg');
```

> checkRule 的 api_key 已经是 camelCase，无需改名。
