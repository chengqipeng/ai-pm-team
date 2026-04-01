# formulaCompute / aggregationCompute — 计算字段子元模型

> 老系统常量：`METAMODEL_ID_FORMULA_COMPUTE` / `METAMODEL_ID_AGGREGATION_COMPUTE` 等
> 老系统 DTO：`XComputeFormula` / `XComputeAggregate` / `XComputeFormulaItem` / `XComputeAggregateCriteria`
> 老系统 PO：`ComputeExpression` / `AggregateRule` / `ComputeExpressionItem` / `AggregateCriteria`
> 父元模型：item（通过 entityApiKey + itemApiKey 关联，仅 itemType=FORMULA/ROLLUP 的字段）
> 状态：P2 待恢复

## 概述

计算字段子元模型定义 FORMULA（公式）和 ROLLUP（汇总）类型字段的计算逻辑。当 item.itemType=6（FORMULA）或 item.itemType=7（ROLLUP）时，需要关联的子元模型来描述具体的计算规则。

包含 5 个元模型：

| 元模型 | api_key | 说明 | 父元模型 |
|:---|:---|:---|:---|
| 计算公式定义 | formulaCompute | 公式表达式、空值处理、结果类型 | item |
| 公式引用字段 | formulaComputeItem | 公式中引用的字段列表 | formulaCompute |
| 汇总累计定义 | aggregationCompute | 汇总对象、汇总字段、汇总方式 | item |
| 汇总条件明细 | aggregationComputeDetail | 汇总的过滤条件 | aggregationCompute |
| 计算因子 | computeFactor | 公式/汇总共享的变量定义 | formulaCompute / aggregationCompute |

## 层级关系

```
item (itemType=FORMULA/ROLLUP)
  ├── formulaCompute（计算公式定义）← entityApiKey + itemApiKey 关联
  │     ├── formulaComputeItem（公式引用字段）← computeApiKey 关联
  │     └── computeFactor（计算因子）← computeApiKey 关联
  └── aggregationCompute（汇总累计定义）← entityApiKey + itemApiKey 关联
        ├── aggregationComputeDetail（汇总条件）← aggregateApiKey 关联
        └── computeFactor（计算因子，共享）← computeApiKey 关联
```

---

## 1. formulaCompute — 计算公式定义

> 老系统：`XComputeFormula` / `ComputeExpression`
> 关联：item.entityApiKey + item.apiKey（仅 itemType=6 FORMULA）

### 老系统字段

| 老字段名 | Java 类型 | 说明 | 新 api_key |
|:---|:---|:---|:---|
| id | Long | 主键 | — |
| objectId / entityId | Long | 所属对象 | entityApiKey |
| itemId | Long | 所属字段 | itemApiKey |
| apiKey | String | 唯一标识 | apiKey |
| label | String | 标签 | label |
| namespace | String | 命名空间 | namespace |
| computeExpression | String | 公式表达式 | computeExpression |
| nullTreatment | Integer | 空值处理方式 | nullTreatment |
| resultType | Integer | 结果数据类型 | resultType |
| deleteFlg | Integer | 软删除 | deleteFlg |

### 新系统字段设计

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| entityApiKey | entity_api_key | 所属对象 | String | 固定列 |
| apiKey | api_key | 公式apiKey | String | 固定列 |
| label | label | 标签 | String | 固定列 |
| labelKey | label_key | 多语言Key | String | 固定列 |
| description | description | 描述 | String | 固定列 |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 固定列 |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列 |
| itemApiKey | dbc_varchar1 | 所属字段apiKey | String | 关联 item |
| computeExpression | dbc_textarea1 | 公式表达式 | String | — |
| nullTreatment | dbc_int1 | 空值处理 | Integer | 0=视为0, 1=视为空 |
| resultType | dbc_int2 | 结果类型 | Integer | ItemTypeEnum 编码 |
| createdBy | created_by | 创建人 | Long | 固定列 |
| createdAt | created_at | 创建时间 | Long | 固定列 |
| updatedBy | updated_by | 修改人 | Long | 固定列 |
| updatedAt | updated_at | 修改时间 | Long | 固定列 |

---

## 2. formulaComputeItem — 公式引用字段

> 老系统：`XComputeFormulaItem` / `ComputeExpressionItem`
> 关联：formulaCompute.apiKey

### 新系统字段设计

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| entityApiKey | entity_api_key | 所属对象 | String | 固定列 |
| apiKey | api_key | 明细apiKey | String | 固定列 |
| label | label | 标签 | String | 固定列 |
| labelKey | label_key | 多语言Key | String | 固定列 |
| description | description | 描述 | String | 固定列 |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 固定列 |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列 |
| computeApiKey | dbc_varchar1 | 所属公式apiKey | String | 关联 formulaCompute |
| referItemApiKey | dbc_varchar2 | 引用字段apiKey | String | 公式中引用的字段 |
| referEntityApiKey | dbc_varchar3 | 引用对象apiKey | String | 跨对象引用时的目标对象 |
| itemOrder | dbc_int1 | 排序序号 | Integer | — |
| createdBy | created_by | 创建人 | Long | 固定列 |
| createdAt | created_at | 创建时间 | Long | 固定列 |
| updatedBy | updated_by | 修改人 | Long | 固定列 |
| updatedAt | updated_at | 修改时间 | Long | 固定列 |

---

## 3. aggregationCompute — 汇总累计定义

> 老系统：`XComputeAggregate` / `AggregateRule`
> 关联：item.entityApiKey + item.apiKey（仅 itemType=7 ROLLUP）

### 老系统字段

| 老字段名 | Java 类型 | 说明 | 新 api_key |
|:---|:---|:---|:---|
| id | Long | 主键 | — |
| objectId / entityId | Long | 所属对象 | entityApiKey |
| itemId | Long | 所属字段 | itemApiKey |
| aggregateObjectId / argEntityId | Long | 汇总目标对象 | aggregateEntityApiKey |
| aggregateItemId / argItemId | Long | 汇总目标字段 | aggregateItemApiKey |
| aggregateLinkItemId / argLinkItemId | Long | 汇总关联字段 | aggregateLinkItemApiKey |
| aggregateType | Integer | 汇总方式（SUM/COUNT/MIN/MAX/AVG） | aggregateType |
| filterFormula | String | 过滤公式 | filterFormula |
| deleteFlg | Integer | 软删除 | deleteFlg |

### 新系统字段设计

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| entityApiKey | entity_api_key | 所属对象 | String | 固定列 |
| apiKey | api_key | 汇总apiKey | String | 固定列 |
| label | label | 标签 | String | 固定列 |
| labelKey | label_key | 多语言Key | String | 固定列 |
| description | description | 描述 | String | 固定列 |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 固定列 |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列 |
| itemApiKey | dbc_varchar1 | 所属字段apiKey | String | 关联 item |
| aggregateEntityApiKey | dbc_varchar2 | 汇总目标对象 | String | 被汇总的子对象 |
| aggregateItemApiKey | dbc_varchar3 | 汇总目标字段 | String | 被汇总的字段 |
| aggregateLinkItemApiKey | dbc_varchar4 | 汇总关联字段 | String | 关联关系字段 |
| aggregateType | dbc_int1 | 汇总方式 | Integer | 1=SUM, 2=COUNT, 3=MIN, 4=MAX, 5=AVG |
| filterFormula | dbc_textarea1 | 过滤公式 | String | — |
| createdBy | created_by | 创建人 | Long | 固定列 |
| createdAt | created_at | 创建时间 | Long | 固定列 |
| updatedBy | updated_by | 修改人 | Long | 固定列 |
| updatedAt | updated_at | 修改时间 | Long | 固定列 |

---

## 4. aggregationComputeDetail — 汇总条件明细

> 老系统：`XComputeAggregateCriteria` / `AggregateCriteria`
> 关联：aggregationCompute.apiKey

### 新系统字段设计

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| entityApiKey | entity_api_key | 所属对象 | String | 固定列 |
| apiKey | api_key | 条件apiKey | String | 固定列 |
| label | label | 标签 | String | 固定列 |
| labelKey | label_key | 多语言Key | String | 固定列 |
| description | description | 描述 | String | 固定列 |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 固定列 |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列 |
| aggregateApiKey | dbc_varchar1 | 所属汇总apiKey | String | 关联 aggregationCompute |
| filterItemApiKey | dbc_varchar2 | 过滤字段apiKey | String | 条件中的字段 |
| filterOperator | dbc_int1 | 过滤操作符 | Integer | 等于/不等于/大于/小于等 |
| filterValue | dbc_varchar3 | 过滤值 | String | — |
| itemOrder | dbc_int2 | 排序序号 | Integer | — |
| createdBy | created_by | 创建人 | Long | 固定列 |
| createdAt | created_at | 创建时间 | Long | 固定列 |
| updatedBy | updated_by | 修改人 | Long | 固定列 |
| updatedAt | updated_at | 修改时间 | Long | 固定列 |

---

## 5. computeFactor — 计算因子

> 老系统：共享于 formulaCompute 和 aggregationCompute
> 关联：computeApiKey（指向 formulaCompute 或 aggregationCompute 的 apiKey）

### 新系统字段设计

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| entityApiKey | entity_api_key | 所属对象 | String | 固定列 |
| apiKey | api_key | 因子apiKey | String | 固定列 |
| label | label | 标签 | String | 固定列 |
| labelKey | label_key | 多语言Key | String | 固定列 |
| description | description | 描述 | String | 固定列 |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 固定列 |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列 |
| computeApiKey | dbc_varchar1 | 所属计算apiKey | String | 关联 formulaCompute 或 aggregationCompute |
| factorType | dbc_int1 | 因子类型 | Integer | 1=字段引用, 2=常量, 3=函数 |
| factorValue | dbc_varchar2 | 因子值 | String | 字段apiKey / 常量值 / 函数名 |
| factorOrder | dbc_int2 | 排序序号 | Integer | — |
| createdBy | created_by | 创建人 | Long | 固定列 |
| createdAt | created_at | 创建时间 | Long | 固定列 |
| updatedBy | updated_by | 修改人 | Long | 固定列 |
| updatedAt | updated_at | 修改时间 | Long | 固定列 |

---

## p_meta_model 注册

| api_key | label | db_table | entity_dependency |
|:---|:---|:---|:---|
| formulaCompute | 计算公式 | p_tenant_formula_compute | 1 |
| formulaComputeItem | 公式引用字段 | p_tenant_formula_compute_item | 1 |
| aggregationCompute | 汇总累计 | p_tenant_aggregation_compute | 1 |
| aggregationComputeDetail | 汇总条件 | p_tenant_aggregation_compute_detail | 1 |
| computeFactor | 计算因子 | p_tenant_compute_factor | 1 |

## p_meta_link 关联关系

| api_key | 父元模型 | 子元模型 | 关联字段 | 级联删除 |
|:---|:---|:---|:---|:---|
| item_to_formulaCompute | item | formulaCompute | itemApiKey | 是 |
| item_to_aggregationCompute | item | aggregationCompute | itemApiKey | 是 |
| formulaCompute_to_item | formulaCompute | formulaComputeItem | computeApiKey | 是 |
| formulaCompute_to_factor | formulaCompute | computeFactor | computeApiKey | 是 |
| aggregationCompute_to_detail | aggregationCompute | aggregationComputeDetail | aggregateApiKey | 是 |
| aggregationCompute_to_factor | aggregationCompute | computeFactor | computeApiKey | 是 |

## dbc 列使用汇总

| 元模型 | dbc_varchar | dbc_int | dbc_textarea | 固定列 | 合计 |
|:---|:---|:---|:---|:---|:---|
| formulaCompute | 1 | 2 | 1 | 12 | 16 |
| formulaComputeItem | 3 | 1 | — | 12 | 16 |
| aggregationCompute | 4 | 1 | 1 | 12 | 18 |
| aggregationComputeDetail | 3 | 2 | — | 12 | 17 |
| computeFactor | 2 | 2 | — | 12 | 16 |

## 业务规则

- formulaCompute / aggregationCompute 仅关联 itemType=6（FORMULA）或 itemType=7（ROLLUP）的字段
- 删除 item 时级联删除其下所有 formulaCompute / aggregationCompute
- 删除 formulaCompute 时级联删除其下所有 formulaComputeItem 和 computeFactor
- 删除 aggregationCompute 时级联删除其下所有 aggregationComputeDetail 和 computeFactor
- computeFactor 是共享元模型，通过 computeApiKey 关联到 formulaCompute 或 aggregationCompute
- aggregateType 取值：1=SUM, 2=COUNT, 3=MIN, 4=MAX, 5=AVG
