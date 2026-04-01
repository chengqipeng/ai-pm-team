# duplicateRule — 查重规则元模型

> 元模型 api_key：`duplicateRule`
> 老系统常量：`MetaConstants.METAMODEL_ID_DUPLICATE_RULE`
> 老系统 DTO：`XDuplicateRule` | 老系统 PO：`EntityDuplicateRule`
> 老系统存储：`p_custom_duplicate_rule`（通过元数据仓库 p_meta_common_metadata）
> 父元模型：entity（通过 entityApiKey 关联）
> 子元模型：duplicateRuleCriteria（查重条件）、duplicateMatchingRule（匹配规则）
> 状态：❌ 未迁移到新系统

## 概述

查重规则（Duplicate Rule）定义 entity 上的数据查重策略。当用户创建或更新记录时，系统根据查重规则检测是否存在重复数据，并给出提示或阻止操作。

核心场景：
- 创建客户时检测是否已存在同名/同电话的客户
- 创建商机时检测是否已存在同名商机
- 支持多条件组合查重（AND/OR 逻辑）
- 支持模糊匹配规则（matchingRule）

## 老系统数据结构

### XDuplicateRule DTO 字段

> 来源：`XDuplicateRuleAction.java`（save/update 方法）+ `EntityDuplicateRuleServiceImpl.java`

| 老字段名 | Java 类型 | 说明 | 新 api_key（建议） |
|:---|:---|:---|:---|
| id | Long | 雪花主键 | — |
| tenantId | Long | 租户 ID | — |
| objectId | Long | 所属对象 ID | entityApiKey |
| apiKey | String | 规则唯一标识 | apiKey |
| name | String | 内部名称 | — （丢弃，用 label） |
| ruleLabel | String | 规则显示标签 | label |
| labelKey | String | 多语言 Key | labelKey |
| namespace | String | 命名空间 | namespace |
| description | String | 描述 | description |
| isCustom | boolean | 是否自定义 | customFlg（基类） |
| isDelete | boolean | 删除标记 | deleteFlg（基类） |
| ruleType | Integer | 规则类型（1=查重规则） | ruleType |
| status | Integer | 状态（1=启用） | activeFlg |
| ruleOrder | Short | 规则排序序号 | ruleOrder |
| checkErrorMsg | String | 查重提示信息 | checkErrorMsg |
| checkErrorMsgKey | String | 提示信息多语言 Key | checkErrorMsgKey |
| criteriaLogic | String | 条件逻辑表达式（如 "1 AND 2 OR 3"） | criteriaLogic |
| filterFormula | String | 过滤公式 | filterFormula |
| matchingFlg | boolean | 是否启用模糊匹配 | matchingFlg |
| createdAt | Long | 创建时间 | createdAt |
| createdBy | Long | 创建人 | createdBy |
| updatedAt | Long | 修改时间 | updatedAt |
| updatedBy | Long | 修改人 | updatedBy |

### XDuplicateRuleCriteria DTO 字段（子元模型）

| 老字段名 | Java 类型 | 说明 | 新 api_key（建议） |
|:---|:---|:---|:---|
| id | Long | 雪花主键 | — |
| objectId | Long | 所属对象 ID | entityApiKey |
| ruleId | Long | 所属查重规则 ID | ruleApiKey |
| fieldId | Long | 匹配字段 ID | itemApiKey |
| matchType | Integer | 匹配方式（精确/模糊/包含） | matchType |
| matchBlank | Integer | 空值是否匹配 | matchBlankFlg |

### XDuplicateMatchingRule DTO 字段（子元模型）

| 老字段名 | Java 类型 | 说明 | 新 api_key（建议） |
|:---|:---|:---|:---|
| id | Long | 雪花主键 | — |
| objectId | Long | 所属对象 ID | entityApiKey |
| ruleId | Long | 所属查重规则 ID | ruleApiKey |
| fieldId | Long | 匹配字段 ID | itemApiKey |
| matchType | Integer | 匹配方式 | matchType |

## 新系统字段设计

### duplicateRule 主元模型（按新规范）

> 遵循：camelCase 命名、xxxFlg 布尔后缀、api_key 关联（禁止 ID）、固定列优先

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| entityApiKey | entity_api_key | 所属对象apiKey | String | 固定列，关联父 entity |
| apiKey | api_key | 规则apiKey | String | 固定列，同一 entity 内唯一 |
| label | label | 规则标签 | String | 固定列 |
| labelKey | label_key | 多语言Key | String | 固定列 |
| description | description | 描述 | String | 固定列 |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 固定列（基类提供） |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列（基类提供） |
| activeFlg | dbc_smallint1 | 启用状态 | Integer(0/1) | 0=禁用, 1=启用 |
| matchingFlg | dbc_smallint2 | 启用模糊匹配 | Integer(0/1) | — |
| ruleType | dbc_int1 | 规则类型 | Integer | 1=查重规则 |
| ruleOrder | dbc_int2 | 排序序号 | Integer | — |
| checkErrorMsg | dbc_varchar1 | 查重提示信息 | String | — |
| checkErrorMsgKey | dbc_varchar2 | 提示信息Key | String | 国际化 |
| descriptionKey | dbc_varchar3 | 描述Key | String | 国际化 |
| criteriaLogic | dbc_textarea1 | 条件逻辑表达式 | String | 如 "1 AND 2 OR 3" |
| filterFormula | dbc_textarea2 | 过滤公式 | String | — |

### duplicateRuleCriteria 子元模型

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| entityApiKey | entity_api_key | 所属对象apiKey | String | 固定列 |
| apiKey | api_key | 条件apiKey | String | 固定列 |
| label | label | 条件标签 | String | 固定列 |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列 |
| ruleApiKey | dbc_varchar1 | 所属规则apiKey | String | 关联父 duplicateRule |
| itemApiKey | dbc_varchar2 | 匹配字段apiKey | String | 关联 item |
| matchType | dbc_int1 | 匹配方式 | Integer | 1=精确, 2=模糊, 3=包含 |
| matchBlankFlg | dbc_smallint1 | 空值匹配 | Integer(0/1) | — |

### duplicateMatchingRule 子元模型

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| entityApiKey | entity_api_key | 所属对象apiKey | String | 固定列 |
| apiKey | api_key | 匹配规则apiKey | String | 固定列 |
| label | label | 匹配规则标签 | String | 固定列 |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列 |
| ruleApiKey | dbc_varchar1 | 所属规则apiKey | String | 关联父 duplicateRule |
| itemApiKey | dbc_varchar2 | 匹配字段apiKey | String | 关联 item |
| matchType | dbc_int1 | 匹配方式 | Integer | — |

### dbc 列使用汇总

| 元模型 | dbc_varchar | dbc_int | dbc_smallint | dbc_textarea | 合计 |
|:---|:---|:---|:---|:---|:---|
| duplicateRule | 1~3 | 1~2 | 1~2 | 1~2 | 9 |
| duplicateRuleCriteria | 1~2 | 1 | 1 | — | 4 |
| duplicateMatchingRule | 1~2 | 1 | — | — | 3 |

## 新系统 p_meta_model 注册（建议）

```sql
INSERT INTO p_meta_model (api_key, label, namespace, metamodel_type,
  enable_common, enable_tenant, entity_dependency, db_table)
VALUES
  ('duplicateRule',         'duplicateRule',         'system', 1, 1, 1, 1, 'p_tenant_duplicate_rule'),
  ('duplicateRuleCriteria', 'duplicateRuleCriteria', 'system', 1, 1, 1, 1, 'p_tenant_duplicate_rule_criteria'),
  ('duplicateMatchingRule', 'duplicateMatchingRule', 'system', 1, 1, 1, 1, 'p_tenant_duplicate_matching_rule');
```

## 新系统存储路由

| 元模型 | Common 表 | Tenant 表 |
|:---|:---|:---|
| duplicateRule | p_common_metadata | p_tenant_duplicate_rule |
| duplicateRuleCriteria | p_common_metadata | p_tenant_duplicate_rule_criteria |
| duplicateMatchingRule | p_common_metadata | p_tenant_duplicate_matching_rule |

## 层级关系

```
entity（对象）
  └── duplicateRule（查重规则）← entityApiKey 关联，级联删除
        ├── duplicateRuleCriteria（查重条件）← ruleApiKey 关联，级联删除
        └── duplicateMatchingRule（匹配规则）← ruleApiKey 关联，级联删除
```

## p_meta_link 关联关系

| api_key | 父元模型 | 子元模型 | 关联字段 | 级联删除 |
|:---|:---|:---|:---|:---|
| entity_to_duplicateRule | entity | duplicateRule | entityApiKey | 是 |
| duplicateRule_to_criteria | duplicateRule | duplicateRuleCriteria | ruleApiKey | 是 |
| duplicateRule_to_matchingRule | duplicateRule | duplicateMatchingRule | ruleApiKey | 是 |

## 迁移要点

| 改造项 | 老系统 | 新系统 |
|:---|:---|:---|
| 关联 | objectId / ruleId / fieldId（Long ID） | entityApiKey / ruleApiKey / itemApiKey（String api_key） |
| 布尔字段 | isCustom/isDelete（boolean）、status（Integer） | customFlg/deleteFlg（基类）、activeFlg（Integer 0/1） |
| 命名 | ruleLabel | label（固定列） |
| 条件逻辑 | criteriaLogic（String） | criteriaLogic（dbc_textarea1，不变） |
| 匹配规则 | 独立子元模型 | 独立子元模型（保持） |

## 业务规则

- duplicateRule.apiKey 在同一 entity 内唯一
- 每个 entity 可有多条查重规则，按 ruleOrder 排序执行
- activeFlg=0 时规则不执行
- criteriaLogic 定义条件间的 AND/OR 逻辑组合
- 删除 entity 时级联删除其下所有 duplicateRule（及其 criteria 和 matchingRule）
- 删除 duplicateRule 时级联删除其下所有 duplicateRuleCriteria 和 duplicateMatchingRule
- matchingFlg=1 时启用模糊匹配，需配合 duplicateMatchingRule 子元模型
- ruleType=1 表示查重规则（当前仅此一种类型）
