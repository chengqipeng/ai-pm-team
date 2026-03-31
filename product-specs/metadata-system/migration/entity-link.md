# entityLink 元模型迁移方案

> 数据量：待统计 | Tenant 表：p_tenant_entity_link

## 迁移内容

### 1. api_key 命名统一（9 个字段，snake_case → camelCase）

```sql
UPDATE p_meta_item SET api_key = 'typeProperty' WHERE metamodel_api_key = 'entityLink' AND api_key = 'type_property';
UPDATE p_meta_item SET api_key = 'parentEntityApiKey' WHERE metamodel_api_key = 'entityLink' AND api_key = 'parent_entity_api_key';
UPDATE p_meta_item SET api_key = 'childEntityApiKey' WHERE metamodel_api_key = 'entityLink' AND api_key = 'child_entity_api_key';
UPDATE p_meta_item SET api_key = 'descriptionKey' WHERE metamodel_api_key = 'entityLink' AND api_key = 'description_key';
UPDATE p_meta_item SET api_key = 'linkType' WHERE metamodel_api_key = 'entityLink' AND api_key = 'link_type';
UPDATE p_meta_item SET api_key = 'detailLinkFlg' WHERE metamodel_api_key = 'entityLink' AND api_key IN ('detail_link', 'detailLink');
UPDATE p_meta_item SET api_key = 'cascadeDelete' WHERE metamodel_api_key = 'entityLink' AND api_key = 'cascade_delete';
UPDATE p_meta_item SET api_key = 'accessControl' WHERE metamodel_api_key = 'entityLink' AND api_key = 'access_control';
UPDATE p_meta_item SET api_key = 'enableFlg' WHERE metamodel_api_key = 'entityLink' AND api_key = 'enable_flg';
```

> 注意：entityLink 的 db_column 历史上使用 `dbc_varchar_1`（带下划线）格式，这是老系统遗留，暂不修改 db_column（会影响已有数据）。
