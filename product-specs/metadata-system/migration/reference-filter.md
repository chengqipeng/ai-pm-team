# referenceFilter 元模型迁移方案

> 数据量：待统计 | Tenant 表：p_tenant_refer_filter

## 迁移内容

### 1. 关联字段标准化（ID → apiKey）

| 老字段名 | 新字段名 | 说明 |
|:---|:---|:---|
| object_id | entity_api_key | db_column 统一使用 apiKey |
| item_id | item_api_key | db_column 统一使用 apiKey |

### 2. api_key 命名统一（3 个修正）

```sql
UPDATE p_meta_item SET api_key = 'activeFlg' WHERE metamodel_api_key = 'referenceFilter' AND api_key = 'isActive';
UPDATE p_meta_item SET api_key = 'deleteFlg' WHERE metamodel_api_key = 'referenceFilter' AND api_key = 'isDeleted';
UPDATE p_meta_item SET api_key = 'andOr' WHERE metamodel_api_key = 'referenceFilter' AND api_key = 'andor';
```
