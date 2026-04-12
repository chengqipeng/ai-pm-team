# sharingRule — 共享规则元模型

> 元模型 api_key：`sharingRule`
> p_meta_model 注册：enable_common=1, enable_tenant=1, db_table=`p_tenant_sharing_rule`
> 父元模型：entity（通过 entityApiKey 关联）
> 子元模型：sharingRuleCondition（共享规则条件）
> Java Entity：`SharingRule.java` | API 模型：`XSharingRule.java`
> 状态：📋 待开发

## 概述

共享规则（Sharing Rule）定义 entity 上的数据自动共享策略。当数据满足规则条件时，系统自动将数据共享给指定的目标主体（用户/部门/公共组/区域），使目标主体获得对该数据的只读或读写权限。

核心场景：
- 将华东区负责人的客户数据共享给华东销售公共组（基于负责人）
- 将 VIP 等级的客户数据共享给 VIP 服务部门（基于条件）
- 将金额 > 100 万的商机共享给管理层公共组（基于条件）

两种共享类型：
- **基于负责人（owner）**：当数据负责人属于来源主体时，将数据共享给目标主体
- **基于条件（condition）**：当数据字段值满足指定条件时，将数据共享给目标主体

## 存储路由

| 层级 | 表名 | 说明 |
|:---|:---|:---|
| Common | `p_common_metadata` | 系统出厂共享规则（WHERE metamodel_api_key='sharingRule'），所有租户共享 |
| Tenant | `p_tenant_sharing_rule` | 租户自定义共享规则，结构与 p_common_metadata 一致 + tenant_id |

- 读取：先查 Common，再查 Tenant，按 entity_api_key + api_key 合并（Tenant 覆盖 Common，delete_flg=1 隐藏）
- 写入：`DynamicTableNameHolder.executeWith('p_tenant_sharing_rule')` 路由到 Tenant 表
- 删除 Common 规则：插入 delete_flg=1 的 Tenant 记录（遮蔽删除）

## 字段定义（23 个）

### 基础信息（固定列映射）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | system/product/custom |
| entityApiKey | entity_api_key | 所属对象apiKey | String | 关联到父 entity |
| apiKey | api_key | 规则apiKey | String | 同一 entity 内唯一 |
| label | label | 规则名称 | String | 如"华东区客户共享给华东销售组" |
| labelKey | label_key | 规则名称Key | String | 国际化 |
| description | description | 规则描述 | String | — |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 0=标准 1=自定义（基类提供） |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 软删除（基类提供） |

### 扩展属性（dbc 列映射）

| api_key | db_column | label | 类型 | 取值约束（p_meta_option） | 说明 |
|:---|:---|:---|:---|:---|:---|
| shareType | dbc_smallint1 | 共享类型 | Integer | 0=基于负责人, 1=基于条件 | 决定规则执行逻辑 |
| fromSubjectType | dbc_smallint2 | 来源主体类型 | Integer | 0=用户, 1=公共组, 2=部门, 3=部门及下级, 4=部门及内部下级, 5=区域 | 数据负责人/数据所属的组织范围 |
| toSubjectType | dbc_smallint3 | 目标主体类型 | Integer | 0=用户, 1=公共组, 2=部门, 3=部门及下级, 4=部门及内部下级, 5=区域 | 被共享的目标组织范围 |
| accessLevel | dbc_smallint4 | 访问级别 | Integer | 1=只读, 2=读写 | 目标主体获得的权限 |
| scopeType | dbc_smallint5 | 作用域 | Integer | 0=全部数据, 1=仅自己的数据 | — |
| activeFlg | dbc_smallint6 | 激活状态 | Integer(0/1) | 0=未激活, 1=已激活 | 未激活的规则不执行 |
| enableFlg | dbc_smallint7 | 启用标记 | Integer(0/1) | 0=禁用, 1=启用 | — |
| fromSubjectApiKey | dbc_varchar1 | 来源主体apiKey | String | — | 用户/部门/公共组/区域的 apiKey（禁止 ID 关联） |
| toSubjectApiKey | dbc_varchar2 | 目标主体apiKey | String | — | 用户/部门/公共组/区域的 apiKey（禁止 ID 关联） |
| criteriaLogic | dbc_varchar3 | 条件逻辑表达式 | String | — | 如 "1 AND 2 OR 3"，仅 shareType=1 时使用 |
| descriptionKey | dbc_varchar4 | 描述Key | String | — | 国际化 |
| fromSubjectLabel | dbc_varchar5 | 来源主体名称 | String | — | 冗余显示用 |
| toSubjectLabel | dbc_varchar6 | 目标主体名称 | String | — | 冗余显示用 |
| ruleOrder | dbc_int1 | 规则排序号 | Integer | — | 多条规则时的执行顺序 |

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
| dbc_smallint | 1~7 | 7 |
| dbc_varchar | 1~6 | 6 |
| dbc_int | 1 | 1 |
| 合计 | | 14 |

## p_meta_model 注册

```sql
INSERT INTO p_meta_model (
    id, api_key, label, label_key, namespace, metamodel_type,
    enable_common, enable_tenant, entity_dependency,
    db_table, visible, delete_flg, created_at, updated_at
) VALUES (
    {snowflake_id}, 'sharingRule', '共享规则',
    'XdMDMetaModel.SharingRule.Label', 'system', 1,
    1, 1, 1,
    'p_tenant_sharing_rule', 1, 0, {now}, {now}
);
```

## p_meta_item 注册（14 个扩展字段）

```sql
-- shareType
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order, require_flg)
VALUES ({id}, 'sharingRule', 'shareType', '共享类型',
    'XdMDMetaItem.SharingRule.ShareType.Label', 'system',
    2, 5, 'dbc_smallint1', 1, 1);

-- fromSubjectType
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order, require_flg)
VALUES ({id}, 'sharingRule', 'fromSubjectType', '来源主体类型',
    'XdMDMetaItem.SharingRule.FromSubjectType.Label', 'system',
    2, 5, 'dbc_smallint2', 2, 1);

-- toSubjectType
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order, require_flg)
VALUES ({id}, 'sharingRule', 'toSubjectType', '目标主体类型',
    'XdMDMetaItem.SharingRule.ToSubjectType.Label', 'system',
    2, 5, 'dbc_smallint3', 3, 1);

-- accessLevel
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order, require_flg)
VALUES ({id}, 'sharingRule', 'accessLevel', '访问级别',
    'XdMDMetaItem.SharingRule.AccessLevel.Label', 'system',
    2, 5, 'dbc_smallint4', 4, 1);

-- scopeType
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order)
VALUES ({id}, 'sharingRule', 'scopeType', '作用域',
    'XdMDMetaItem.SharingRule.ScopeType.Label', 'system',
    2, 5, 'dbc_smallint5', 5);

-- activeFlg
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order)
VALUES ({id}, 'sharingRule', 'activeFlg', '激活状态',
    'XdMDMetaItem.SharingRule.ActiveFlg.Label', 'system',
    31, 5, 'dbc_smallint6', 6);

-- enableFlg
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order)
VALUES ({id}, 'sharingRule', 'enableFlg', '启用标记',
    'XdMDMetaItem.SharingRule.EnableFlg.Label', 'system',
    31, 5, 'dbc_smallint7', 7);

-- fromSubjectApiKey
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order)
VALUES ({id}, 'sharingRule', 'fromSubjectApiKey', '来源主体apiKey',
    'XdMDMetaItem.SharingRule.FromSubjectApiKey.Label', 'system',
    1, 1, 'dbc_varchar1', 8);

-- toSubjectApiKey
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order)
VALUES ({id}, 'sharingRule', 'toSubjectApiKey', '目标主体apiKey',
    'XdMDMetaItem.SharingRule.ToSubjectApiKey.Label', 'system',
    1, 1, 'dbc_varchar2', 9);

-- criteriaLogic
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order)
VALUES ({id}, 'sharingRule', 'criteriaLogic', '条件逻辑表达式',
    'XdMDMetaItem.SharingRule.CriteriaLogic.Label', 'system',
    1, 1, 'dbc_varchar3', 10);

-- descriptionKey
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order)
VALUES ({id}, 'sharingRule', 'descriptionKey', '描述Key',
    'XdMDMetaItem.SharingRule.DescriptionKey.Label', 'system',
    1, 1, 'dbc_varchar4', 11);

-- fromSubjectLabel
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order)
VALUES ({id}, 'sharingRule', 'fromSubjectLabel', '来源主体名称',
    'XdMDMetaItem.SharingRule.FromSubjectLabel.Label', 'system',
    1, 1, 'dbc_varchar5', 12);

-- toSubjectLabel
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order)
VALUES ({id}, 'sharingRule', 'toSubjectLabel', '目标主体名称',
    'XdMDMetaItem.SharingRule.ToSubjectLabel.Label', 'system',
    1, 1, 'dbc_varchar6', 13);

-- ruleOrder
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order)
VALUES ({id}, 'sharingRule', 'ruleOrder', '规则排序号',
    'XdMDMetaItem.SharingRule.RuleOrder.Label', 'system',
    2, 4, 'dbc_int1', 14);
```

## p_meta_option 注册

```sql
-- shareType 选项
INSERT INTO p_meta_option (id, metamodel_api_key, item_api_key, option_code, option_key, option_label, option_order) VALUES
({id}, 'sharingRule', 'shareType', 0, 'owner', '基于负责人', 1),
({id}, 'sharingRule', 'shareType', 1, 'condition', '基于条件', 2);

-- fromSubjectType / toSubjectType 选项（共用）
INSERT INTO p_meta_option (id, metamodel_api_key, item_api_key, option_code, option_key, option_label, option_order) VALUES
({id}, 'sharingRule', 'fromSubjectType', 0, 'user', '用户', 1),
({id}, 'sharingRule', 'fromSubjectType', 1, 'publicGroup', '公共组', 2),
({id}, 'sharingRule', 'fromSubjectType', 2, 'depart', '部门', 3),
({id}, 'sharingRule', 'fromSubjectType', 3, 'departAndSub', '部门及下级', 4),
({id}, 'sharingRule', 'fromSubjectType', 4, 'departInternal', '部门及内部下级', 5),
({id}, 'sharingRule', 'fromSubjectType', 5, 'territory', '区域', 6);

INSERT INTO p_meta_option (id, metamodel_api_key, item_api_key, option_code, option_key, option_label, option_order) VALUES
({id}, 'sharingRule', 'toSubjectType', 0, 'user', '用户', 1),
({id}, 'sharingRule', 'toSubjectType', 1, 'publicGroup', '公共组', 2),
({id}, 'sharingRule', 'toSubjectType', 2, 'depart', '部门', 3),
({id}, 'sharingRule', 'toSubjectType', 3, 'departAndSub', '部门及下级', 4),
({id}, 'sharingRule', 'toSubjectType', 4, 'departInternal', '部门及内部下级', 5),
({id}, 'sharingRule', 'toSubjectType', 5, 'territory', '区域', 6);

-- accessLevel 选项
INSERT INTO p_meta_option (id, metamodel_api_key, item_api_key, option_code, option_key, option_label, option_order) VALUES
({id}, 'sharingRule', 'accessLevel', 1, 'read', '只读', 1),
({id}, 'sharingRule', 'accessLevel', 2, 'write', '读写', 2);

-- scopeType 选项
INSERT INTO p_meta_option (id, metamodel_api_key, item_api_key, option_code, option_key, option_label, option_order) VALUES
({id}, 'sharingRule', 'scopeType', 0, 'all', '全部数据', 1),
({id}, 'sharingRule', 'scopeType', 1, 'own', '仅自己的数据', 2);
```

## p_meta_link 注册

```sql
INSERT INTO p_meta_link (id, api_key, namespace, label,
    parent_metamodel_api_key, child_metamodel_api_key,
    refer_item_api_key, cascade_delete)
VALUES
({id}, 'entity_to_sharingRule', 'system', '对象包含共享规则',
    'entity', 'sharingRule', 'entityApiKey', 1),
({id}, 'sharingRule_to_condition', 'system', '共享规则包含条件',
    'sharingRule', 'sharingRuleCondition', 'ruleApiKey', 1);
```

## 层级关系

```
entity（对象）
  └── sharingRule（共享规则）← entityApiKey 关联，级联删除
        └── sharingRuleCondition（规则条件）← ruleApiKey 关联，级联删除
```

## 业务规则

- sharingRule.apiKey 在同一 entity 内唯一
- activeFlg=0 时规则不执行
- shareType=0（基于负责人）时，fromSubjectType/fromSubjectApiKey 指定来源组织范围，不需要 sharingRuleCondition
- shareType=1（基于条件）时，必须至少有一条 sharingRuleCondition，criteriaLogic 定义条件间的 AND/OR 逻辑
- 删除 entity 时级联删除其下所有 sharingRule（及其 sharingRuleCondition）
- 删除 sharingRule 时级联删除其下所有 sharingRuleCondition
- 规则变更（创建/修改/删除/激活/停用）时，发送 MQ 事件触发权限重算
- 多条规则按 ruleOrder 排序执行
- fromSubjectApiKey/toSubjectApiKey 使用 apiKey 关联（禁止 ID 关联），运行时通过 apiKey 查询对应主体的详细信息
