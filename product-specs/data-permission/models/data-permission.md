# dataPermission — 数据权限配置元模型

> 元模型 api_key：`dataPermission`
> p_meta_model 注册：enable_common=1, enable_tenant=1, db_table=`p_tenant_data_permission`
> 父元模型：entity（通过 entityApiKey 关联）
> 子元模型：无
> Java Entity：`DataPermission.java` | API 模型：`XDataPermission.java`
> 状态：📋 待开发

## 概述

数据权限配置（Data Permission）定义 entity 级别的数据权限总策略。每个 entity 有且仅有一条 dataPermission 配置，控制该对象的默认访问级别、层级访问策略、各权限来源的默认权限等。

核心作用：
- 控制组织内数据的默认可见性（私有/只读/读写）
- 控制上级是否可见下级数据（层级访问）
- 控制负责人、团队成员、区域的默认权限级别
- 控制是否允许手动共享和自动共享规则

与 entity 元数据的关系：
- entity.sharingFlg 控制"是否支持共享功能"
- dataPermission 控制"共享的具体策略和默认权限"

## 存储路由

| 层级 | 表名 | 说明 |
|:---|:---|:---|
| Common | `p_common_metadata` | 系统出厂权限配置（WHERE metamodel_api_key='dataPermission'），每个标准 entity 一条 |
| Tenant | `p_tenant_data_permission` | 租户自定义权限配置，结构与 p_common_metadata 一致 + tenant_id |

- 读取：先查 Common，再查 Tenant，按 entity_api_key + api_key 合并（Tenant 覆盖 Common）
- 写入：`DynamicTableNameHolder.executeWith('p_tenant_data_permission')` 路由到 Tenant 表
- 每个 entity 有且仅有一条 dataPermission 记录（api_key = `{entityApiKey}_data_permission`）

## 字段定义（18 个）

### 基础信息（固定列映射）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | system/product/custom |
| entityApiKey | entity_api_key | 所属对象apiKey | String | 关联到父 entity |
| apiKey | api_key | 配置apiKey | String | 格式：`{entityApiKey}_data_permission` |
| label | label | 配置名称 | String | 如"客户数据权限配置" |
| labelKey | label_key | 配置名称Key | String | 国际化 |
| description | description | 描述 | String | — |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 基类提供 |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 基类提供 |

### 扩展属性（dbc 列映射）

| api_key | db_column | label | 类型 | 取值约束（p_meta_option） | 说明 |
|:---|:---|:---|:---|:---|:---|
| defaultAccess | dbc_smallint1 | 默认访问级别 | Integer | 0=私有, 1=只读, 2=读写 | 组织内数据的默认可见性 |
| hierarchyAccess | dbc_smallint2 | 层级访问 | Integer | 0=无, 1=只读, 2=读写 | 上级是否可见下级数据 |
| ownerAccess | dbc_smallint3 | 负责人权限 | Integer | 1=只读, 2=读写 | 负责人对自己数据的默认权限 |
| teamAccess | dbc_smallint4 | 团队成员权限 | Integer | 0=无, 1=只读, 2=读写 | 团队成员的默认权限 |
| territoryAccess | dbc_smallint5 | 区域权限 | Integer | 0=无, 1=只读, 2=读写 | 区域成员的默认权限 |
| sharingFlg | dbc_smallint6 | 允许手动共享 | Integer(0/1) | 0=不允许, 1=允许 | 是否允许用户手动共享数据 |
| sharingRuleFlg | dbc_smallint7 | 允许共享规则 | Integer(0/1) | 0=不允许, 1=允许 | 是否启用自动共享规则 |
| externalAccess | dbc_smallint8 | 外部访问 | Integer | 0=无, 1=只读 | 外部用户（门户）的默认权限 |

### 审计字段（固定列映射）

| api_key | db_column | 类型 |
|:---|:---|:---|
| createdBy | created_by | Long |
| createdAt | created_at | Long(毫秒) |
| updatedBy | updated_by | Long |
| updatedAt | updated_at | Long(毫秒) |

### dbc 列使用汇总

| 列类型 | 使用编号 | 总数 |
|:---|:---|:---|
| dbc_smallint | 1~8 | 8 |
| 合计 | | 8 |

## p_meta_model 注册

```sql
INSERT INTO p_meta_model (
    id, api_key, label, label_key, namespace, metamodel_type,
    enable_common, enable_tenant, entity_dependency,
    db_table, visible, delete_flg, created_at, updated_at
) VALUES (
    {snowflake_id}, 'dataPermission', '数据权限配置',
    'XdMDMetaModel.DataPermission.Label', 'system', 1,
    1, 1, 1,
    'p_tenant_data_permission', 1, 0, {now}, {now}
);
```

## p_meta_item 注册（8 个扩展字段）

```sql
-- defaultAccess
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order, require_flg)
VALUES ({id}, 'dataPermission', 'defaultAccess', '默认访问级别',
    'XdMDMetaItem.DataPermission.DefaultAccess.Label', 'system',
    2, 5, 'dbc_smallint1', 1, 1);

-- hierarchyAccess
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order, require_flg)
VALUES ({id}, 'dataPermission', 'hierarchyAccess', '层级访问',
    'XdMDMetaItem.DataPermission.HierarchyAccess.Label', 'system',
    2, 5, 'dbc_smallint2', 2, 1);

-- ownerAccess
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order, require_flg)
VALUES ({id}, 'dataPermission', 'ownerAccess', '负责人权限',
    'XdMDMetaItem.DataPermission.OwnerAccess.Label', 'system',
    2, 5, 'dbc_smallint3', 3, 1);

-- teamAccess
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order, require_flg)
VALUES ({id}, 'dataPermission', 'teamAccess', '团队成员权限',
    'XdMDMetaItem.DataPermission.TeamAccess.Label', 'system',
    2, 5, 'dbc_smallint4', 4, 1);

-- territoryAccess
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order, require_flg)
VALUES ({id}, 'dataPermission', 'territoryAccess', '区域权限',
    'XdMDMetaItem.DataPermission.TerritoryAccess.Label', 'system',
    2, 5, 'dbc_smallint5', 5, 1);

-- sharingFlg
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order)
VALUES ({id}, 'dataPermission', 'sharingFlg', '允许手动共享',
    'XdMDMetaItem.DataPermission.SharingFlg.Label', 'system',
    31, 5, 'dbc_smallint6', 6);

-- sharingRuleFlg
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order)
VALUES ({id}, 'dataPermission', 'sharingRuleFlg', '允许共享规则',
    'XdMDMetaItem.DataPermission.SharingRuleFlg.Label', 'system',
    31, 5, 'dbc_smallint7', 7);

-- externalAccess
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order)
VALUES ({id}, 'dataPermission', 'externalAccess', '外部访问',
    'XdMDMetaItem.DataPermission.ExternalAccess.Label', 'system',
    2, 5, 'dbc_smallint8', 8);
```

## p_meta_option 注册

```sql
-- defaultAccess 选项
INSERT INTO p_meta_option (id, metamodel_api_key, item_api_key, option_code, option_key, option_label, option_order) VALUES
({id}, 'dataPermission', 'defaultAccess', 0, 'private', '私有', 1),
({id}, 'dataPermission', 'defaultAccess', 1, 'read', '只读', 2),
({id}, 'dataPermission', 'defaultAccess', 2, 'readWrite', '读写', 3);

-- hierarchyAccess 选项
INSERT INTO p_meta_option (id, metamodel_api_key, item_api_key, option_code, option_key, option_label, option_order) VALUES
({id}, 'dataPermission', 'hierarchyAccess', 0, 'none', '无', 1),
({id}, 'dataPermission', 'hierarchyAccess', 1, 'read', '只读', 2),
({id}, 'dataPermission', 'hierarchyAccess', 2, 'readWrite', '读写', 3);

-- ownerAccess 选项
INSERT INTO p_meta_option (id, metamodel_api_key, item_api_key, option_code, option_key, option_label, option_order) VALUES
({id}, 'dataPermission', 'ownerAccess', 1, 'read', '只读', 1),
({id}, 'dataPermission', 'ownerAccess', 2, 'readWrite', '读写', 2);

-- teamAccess 选项
INSERT INTO p_meta_option (id, metamodel_api_key, item_api_key, option_code, option_key, option_label, option_order) VALUES
({id}, 'dataPermission', 'teamAccess', 0, 'none', '无', 1),
({id}, 'dataPermission', 'teamAccess', 1, 'read', '只读', 2),
({id}, 'dataPermission', 'teamAccess', 2, 'readWrite', '读写', 3);

-- territoryAccess 选项
INSERT INTO p_meta_option (id, metamodel_api_key, item_api_key, option_code, option_key, option_label, option_order) VALUES
({id}, 'dataPermission', 'territoryAccess', 0, 'none', '无', 1),
({id}, 'dataPermission', 'territoryAccess', 1, 'read', '只读', 2),
({id}, 'dataPermission', 'territoryAccess', 2, 'readWrite', '读写', 3);

-- externalAccess 选项
INSERT INTO p_meta_option (id, metamodel_api_key, item_api_key, option_code, option_key, option_label, option_order) VALUES
({id}, 'dataPermission', 'externalAccess', 0, 'none', '无', 1),
({id}, 'dataPermission', 'externalAccess', 1, 'read', '只读', 2);
```

## p_meta_link 注册

```sql
INSERT INTO p_meta_link (id, api_key, namespace, label,
    parent_metamodel_api_key, child_metamodel_api_key,
    refer_item_api_key, cascade_delete)
VALUES
({id}, 'entity_to_dataPermission', 'system', '对象包含数据权限配置',
    'entity', 'dataPermission', 'entityApiKey', 1);
```

## Common 级出厂数据

系统出厂时，为每个标准 entity 预置默认的 dataPermission 配置：

```sql
-- account 对象的默认数据权限配置
INSERT INTO p_common_metadata (
    id, metamodel_api_key, entity_api_key, api_key, label, namespace,
    dbc_smallint1, dbc_smallint2, dbc_smallint3, dbc_smallint4,
    dbc_smallint5, dbc_smallint6, dbc_smallint7, dbc_smallint8,
    created_at, updated_at
) VALUES (
    {snowflake_id}, 'dataPermission', 'account', 'account_data_permission',
    '客户数据权限配置', 'system',
    0,  -- defaultAccess = 私有
    1,  -- hierarchyAccess = 只读
    2,  -- ownerAccess = 读写
    1,  -- teamAccess = 只读
    0,  -- territoryAccess = 无
    1,  -- sharingFlg = 允许
    1,  -- sharingRuleFlg = 允许
    0,  -- externalAccess = 无
    {now}, {now}
);

-- contact 对象
INSERT INTO p_common_metadata (
    id, metamodel_api_key, entity_api_key, api_key, label, namespace,
    dbc_smallint1, dbc_smallint2, dbc_smallint3, dbc_smallint4,
    dbc_smallint5, dbc_smallint6, dbc_smallint7, dbc_smallint8,
    created_at, updated_at
) VALUES (
    {snowflake_id}, 'dataPermission', 'contact', 'contact_data_permission',
    '联系人数据权限配置', 'system',
    0, 1, 2, 1, 0, 1, 1, 0,
    {now}, {now}
);

-- opportunity 对象
INSERT INTO p_common_metadata (
    id, metamodel_api_key, entity_api_key, api_key, label, namespace,
    dbc_smallint1, dbc_smallint2, dbc_smallint3, dbc_smallint4,
    dbc_smallint5, dbc_smallint6, dbc_smallint7, dbc_smallint8,
    created_at, updated_at
) VALUES (
    {snowflake_id}, 'dataPermission', 'opportunity', 'opportunity_data_permission',
    '商机数据权限配置', 'system',
    0, 1, 2, 1, 0, 1, 1, 0,
    {now}, {now}
);

-- lead 对象
INSERT INTO p_common_metadata (
    id, metamodel_api_key, entity_api_key, api_key, label, namespace,
    dbc_smallint1, dbc_smallint2, dbc_smallint3, dbc_smallint4,
    dbc_smallint5, dbc_smallint6, dbc_smallint7, dbc_smallint8,
    created_at, updated_at
) VALUES (
    {snowflake_id}, 'dataPermission', 'lead', 'lead_data_permission',
    '线索数据权限配置', 'system',
    0, 1, 2, 0, 0, 1, 1, 0,
    {now}, {now}
);
```

## 层级关系

```
entity（对象）
  └── dataPermission（数据权限配置）← entityApiKey 关联，级联删除
        每个 entity 有且仅有一条
```

## 业务规则

- 每个 entity 有且仅有一条 dataPermission 记录
- api_key 格式固定为 `{entityApiKey}_data_permission`
- 创建新 entity 时自动创建默认 dataPermission（defaultAccess=0, ownerAccess=2）
- 租户可覆盖 Common 级配置（如将 account 的 defaultAccess 从私有改为只读）
- defaultAccess=2（读写）时，所有用户可见所有数据，无需查 share 表（性能优化快速路径）
- ownerAccess 不允许设为 0（负责人必须能看到自己的数据）
- 删除 entity 时级联删除其 dataPermission
- dataPermission 变更时发送 MQ 事件，清除相关缓存
