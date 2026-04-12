# sharingRuleCondition — 共享规则条件元模型

> 元模型 api_key：`sharingRuleCondition`
> p_meta_model 注册：enable_common=1, enable_tenant=1, db_table=`p_tenant_sharing_rule_condition`
> 父元模型：sharingRule（通过 ruleApiKey 关联）
> 子元模型：无
> Java Entity：`SharingRuleCondition.java` | API 模型：`XSharingRuleCondition.java`
> 状态：📋 待开发

## 概述

共享规则条件（Sharing Rule Condition）定义"基于条件"类型共享规则的具体过滤条件行。每个 sharingRule（shareType=1）可包含多条 condition，通过 criteriaLogic 表达式组合（如 "1 AND 2 OR 3"）。

条件引用 entity 下的 item（字段），通过 operatorCode 和 conditionValue 定义匹配逻辑。运行时，条件被转换为 SQL WHERE 子句，查询 p_tenant_data 中匹配的业务数据。

## 存储路由

| 层级 | 表名 | 说明 |
|:---|:---|:---|
| Common | `p_common_metadata` | 系统出厂规则条件（WHERE metamodel_api_key='sharingRuleCondition'） |
| Tenant | `p_tenant_sharing_rule_condition` | 租户自定义规则条件，结构与 p_common_metadata 一致 + tenant_id |

- 读取：先查 Common，再查 Tenant，按 entity_api_key + api_key 合并
- 写入：`DynamicTableNameHolder.executeWith('p_tenant_sharing_rule_condition')` 路由到 Tenant 表

## 字段定义（17 个）

### 基础信息（固定列映射）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | system/product/custom |
| entityApiKey | entity_api_key | 所属对象apiKey | String | 三级定位：entity → sharingRule → condition |
| apiKey | api_key | 条件apiKey | String | 同一 entity 内唯一 |
| label | label | 条件标签 | String | — |
| labelKey | label_key | 条件标签Key | String | 国际化 |
| description | description | 描述 | String | — |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 基类提供 |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 基类提供 |

### 扩展属性（dbc 列映射）

| api_key | db_column | label | 类型 | 取值约束（p_meta_option） | 说明 |
|:---|:---|:---|:---|:---|:---|
| ruleApiKey | dbc_varchar1 | 所属规则apiKey | String | — | 关联父 sharingRule |
| itemApiKey | dbc_varchar2 | 条件字段apiKey | String | — | 关联同 entity 下的 item |
| operatorCode | dbc_varchar3 | 操作符编码 | String | equal/notEqual/greaterThan/greaterEqual/lessThan/lessEqual/contain/notContain/empty/notEmpty | 条件操作符 |
| conditionValue | dbc_varchar4 | 条件值 | String | — | 匹配值，类型由 item.itemType 决定 |
| conditionValueLabel | dbc_varchar5 | 条件值显示名 | String | — | 冗余显示用（如选项值的 label） |
| rowNo | dbc_int1 | 条件行号 | Integer | — | 用于 criteriaLogic 表达式中的序号引用 |
| conditionType | dbc_int2 | 条件类型 | Integer | 1=字段条件 | 预留扩展 |

### 审计字段（固定列映射）

| api_key | db_column | 类型 |
|:---|:---|:---|
| createdBy | created_by | Long |
| createdAt | created_at | Long(毫秒) |

### dbc 列使用汇总

| 列类型 | 使用编号 | 总数 |
|:---|:---|:---|
| dbc_varchar | 1~5 | 5 |
| dbc_int | 1~2 | 2 |
| 合计 | | 7 |

## p_meta_model 注册

```sql
INSERT INTO p_meta_model (
    id, api_key, label, label_key, namespace, metamodel_type,
    enable_common, enable_tenant, entity_dependency,
    db_table, visible, delete_flg, created_at, updated_at
) VALUES (
    {snowflake_id}, 'sharingRuleCondition', '共享规则条件',
    'XdMDMetaModel.SharingRuleCondition.Label', 'system', 1,
    1, 1, 1,
    'p_tenant_sharing_rule_condition', 0, 0, {now}, {now}
);
```

## p_meta_item 注册（7 个扩展字段）

```sql
-- ruleApiKey
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order, require_flg)
VALUES ({id}, 'sharingRuleCondition', 'ruleApiKey', '所属规则apiKey',
    'XdMDMetaItem.SharingRuleCondition.RuleApiKey.Label', 'system',
    1, 1, 'dbc_varchar1', 1, 1);

-- itemApiKey
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order, require_flg)
VALUES ({id}, 'sharingRuleCondition', 'itemApiKey', '条件字段apiKey',
    'XdMDMetaItem.SharingRuleCondition.ItemApiKey.Label', 'system',
    1, 1, 'dbc_varchar2', 2, 1);

-- operatorCode
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order, require_flg)
VALUES ({id}, 'sharingRuleCondition', 'operatorCode', '操作符编码',
    'XdMDMetaItem.SharingRuleCondition.OperatorCode.Label', 'system',
    1, 1, 'dbc_varchar3', 3, 1);

-- conditionValue
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order)
VALUES ({id}, 'sharingRuleCondition', 'conditionValue', '条件值',
    'XdMDMetaItem.SharingRuleCondition.ConditionValue.Label', 'system',
    1, 1, 'dbc_varchar4', 4);

-- conditionValueLabel
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order)
VALUES ({id}, 'sharingRuleCondition', 'conditionValueLabel', '条件值显示名',
    'XdMDMetaItem.SharingRuleCondition.ConditionValueLabel.Label', 'system',
    1, 1, 'dbc_varchar5', 5);

-- rowNo
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order, require_flg)
VALUES ({id}, 'sharingRuleCondition', 'rowNo', '条件行号',
    'XdMDMetaItem.SharingRuleCondition.RowNo.Label', 'system',
    2, 4, 'dbc_int1', 6, 1);

-- conditionType
INSERT INTO p_meta_item (id, metamodel_api_key, api_key, label, label_key, namespace,
    item_type, data_type, db_column, item_order)
VALUES ({id}, 'sharingRuleCondition', 'conditionType', '条件类型',
    'XdMDMetaItem.SharingRuleCondition.ConditionType.Label', 'system',
    2, 4, 'dbc_int2', 7);
```

## p_meta_option 注册

```sql
-- operatorCode 选项（存储为 String，通过 p_meta_option 约束合法值）
INSERT INTO p_meta_option (id, metamodel_api_key, item_api_key, option_code, option_key, option_label, option_order) VALUES
({id}, 'sharingRuleCondition', 'operatorCode', 1, 'equal', '等于', 1),
({id}, 'sharingRuleCondition', 'operatorCode', 2, 'notEqual', '不等于', 2),
({id}, 'sharingRuleCondition', 'operatorCode', 6, 'greaterThan', '大于', 3),
({id}, 'sharingRuleCondition', 'operatorCode', 7, 'greaterEqual', '大于等于', 4),
({id}, 'sharingRuleCondition', 'operatorCode', 8, 'lessThan', '小于', 5),
({id}, 'sharingRuleCondition', 'operatorCode', 9, 'lessEqual', '小于等于', 6),
({id}, 'sharingRuleCondition', 'operatorCode', 10, 'contain', '包含', 7),
({id}, 'sharingRuleCondition', 'operatorCode', 16, 'notContain', '不包含', 8),
({id}, 'sharingRuleCondition', 'operatorCode', 13, 'empty', '为空', 9),
({id}, 'sharingRuleCondition', 'operatorCode', 14, 'notEmpty', '不为空', 10);

-- conditionType 选项
INSERT INTO p_meta_option (id, metamodel_api_key, item_api_key, option_code, option_key, option_label, option_order) VALUES
({id}, 'sharingRuleCondition', 'conditionType', 1, 'field', '字段条件', 1);
```

## 业务规则

- sharingRuleCondition 仅在父 sharingRule.shareType=1（基于条件）时有意义
- ruleApiKey 必须指向同 entity 下已存在的 sharingRule
- itemApiKey 必须指向同 entity 下已存在且 enableFlg=1 的 item
- operatorCode 必须在 p_meta_option 定义的合法范围内
- conditionValue 的格式由 item.itemType 决定（如 DATE 类型存毫秒时间戳，PICKLIST 存 optionApiKey）
- rowNo 对应 sharingRule.criteriaLogic 表达式中的序号（如 criteriaLogic="1 AND 2" 中的 1 和 2）
- 删除 sharingRule 时级联删除其下所有 sharingRuleCondition
