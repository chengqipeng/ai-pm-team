# busiType 元模型迁移方案

> 数据量：待统计 | Tenant 表：p_tenant_busi_type
> 同步脚本：`sql/sync_busi_type.py`

## 老系统数据来源

老系统 busiType 数据存储在两个地方：

| 数据类型 | 老表 | 字段差异 |
|:---|:---|:---|
| 标准业务类型 | `b_entity_belong_type` | belong_id（非 entity_id）、type_name（非 label）、del_flg（非 delete_flg） |
| 自定义业务类型 | `p_custom_busitype` | entity_id、label、delete_flg |
| 元数据仓库（合并后） | `p_meta_common_metadata` | metadata_json 存储所有字段 |

迁移从 `p_meta_common_metadata`（元数据仓库）读取，因为该表已经合并了标准和自定义数据，且字段名统一。

## 迁移内容

### 1. 元模型注册

```sql
-- 在 p_meta_model 中注册 busiType 元模型
-- 见 sql/seed_meta_item_busi_type.sql
```

### 2. 数据同步（Common 级）

通过 `sql/sync_busi_type.py` 从老库 PostgreSQL 同步到新库 MySQL。

核心转换：

| 转换项 | 老值 | 新值 | 说明 |
|:---|:---|:---|:---|
| metamodel_api_key | 老 metamodel_id | `'busiType'` | 固定值 |
| entity_api_key | objectId（Long） | entity.apiKey（String） | 通过 entity ID→apiKey 映射表转换 |
| parentApiKey（dbc_varchar1） | parentId（Long） | busiType.apiKey（String） | 通过 busiType ID→apiKey 映射表转换，0 或 null 不转换 |
| enableFlg（dbc_smallint1） | isActive（boolean） | Integer(0/1) | true→1, false→0 |
| namespace | xsy/system | product/system | 命名空间映射 |
| label_key | 老 labelKey | `XdMDBusiType.{apiKey}` | 统一格式 |

### 3. api_key 命名统一

busiType 的 p_meta_item 字段 api_key 在新系统中已按规范定义（seed SQL），无需额外迁移。

但需要检查老数据中 metadata_json 的 key 是否与新 p_meta_item.api_key 一致：

| 老 JSON key | 新 api_key | 变化 |
|:---|:---|:---|
| isActive | enableFlg | 重命名 |
| defaultFlg | defaultFlg | 不变 |
| specialFlg | specialFlg | 不变 |
| busiTypeOrder | busiTypeOrder | 不变 |
| depth | depth | 不变 |
| parentId | parentApiKey | 重命名 + ID→apiKey |
| helpText | helpText | 不变 |
| helpTextKey | helpTextKey | 不变 |
| isCustom | customFlg | 重命名（映射到固定列 custom_flg） |

### 4. Tenant 级数据迁移

Tenant 级数据从老库 `p_custom_busitype` 迁移到新库 `p_tenant_busi_type`：

```sql
-- Step 1: 创建 Tenant 快捷表
CREATE TABLE p_tenant_busi_type LIKE p_common_metadata;
ALTER TABLE p_tenant_busi_type ADD COLUMN tenant_id BIGINT NOT NULL AFTER id;
ALTER TABLE p_tenant_busi_type ADD INDEX idx_tenant_metamodel (tenant_id, metamodel_api_key);
ALTER TABLE p_tenant_busi_type ADD INDEX idx_tenant_entity (tenant_id, entity_api_key);

-- Step 2: Tenant 数据通过类似的 Python 脚本同步
-- 与 Common 级逻辑一致，额外需要：
--   - 设置 tenant_id
--   - namespace = 'custom'（租户自定义）
--   - 写入目标表为 p_tenant_busi_type
```

## 验证

```sql
-- 1. 数据量检查
SELECT COUNT(*) FROM p_common_metadata WHERE metamodel_api_key = 'busiType';

-- 2. entity_api_key 无纯数字 ID 残留
SELECT * FROM p_common_metadata
WHERE metamodel_api_key = 'busiType'
  AND entity_api_key REGEXP '^[0-9]+$';

-- 3. parentApiKey 无纯数字 ID 残留（dbc_varchar1）
SELECT * FROM p_common_metadata
WHERE metamodel_api_key = 'busiType'
  AND dbc_varchar1 IS NOT NULL
  AND dbc_varchar1 REGEXP '^[0-9]+$';

-- 4. enableFlg 只有 0/1
SELECT DISTINCT dbc_smallint1 FROM p_common_metadata
WHERE metamodel_api_key = 'busiType';

-- 5. namespace 合法
SELECT DISTINCT namespace FROM p_common_metadata
WHERE metamodel_api_key = 'busiType';

-- 6. 每个 entity 至少有一个 defaultFlg=1 的业务类型
SELECT entity_api_key, COUNT(*) AS cnt
FROM p_common_metadata
WHERE metamodel_api_key = 'busiType' AND dbc_smallint2 = 1
GROUP BY entity_api_key
HAVING cnt = 0;

-- 7. 抽样对比（取前 5 条与老库对比）
SELECT api_key, label, entity_api_key, namespace,
       dbc_smallint1 AS enableFlg, dbc_smallint2 AS defaultFlg,
       dbc_int1 AS specialFlg, dbc_int2 AS busiTypeOrder
FROM p_common_metadata
WHERE metamodel_api_key = 'busiType'
ORDER BY api_key
LIMIT 5;
```
