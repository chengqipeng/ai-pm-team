# pickOption 元模型迁移方案

> 数据量：待统计 | Tenant 表：p_tenant_pick_option

## 迁移内容

### 1. 关联字段标准化（ID → apiKey）

| 老字段名 | 新字段名 | 说明 |
|:---|:---|:---|
| item_id | item_api_key | db_column 统一使用 apiKey |

### 2. api_key 命名统一（5 个 is 前缀修正）

```sql
UPDATE p_meta_item SET api_key = 'defaultFlg' WHERE metamodel_api_key = 'pickOption' AND api_key = 'isDefault';
UPDATE p_meta_item SET api_key = 'globalFlg' WHERE metamodel_api_key = 'pickOption' AND api_key = 'isGlobal';
UPDATE p_meta_item SET api_key = 'customFlg' WHERE metamodel_api_key = 'pickOption' AND api_key = 'isCustom';
UPDATE p_meta_item SET api_key = 'deleteFlg' WHERE metamodel_api_key = 'pickOption' AND api_key = 'isDeleted';
UPDATE p_meta_item SET api_key = 'enableFlg' WHERE metamodel_api_key = 'pickOption' AND api_key = 'isActive';
```
