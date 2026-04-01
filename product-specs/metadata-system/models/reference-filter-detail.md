# referenceFilterDetail — 关联过滤条件明细

> 老系统常量：`METAMODEL_ID_REFERENCE_FILTER_DETAIL`
> 老系统 DTO：`XReferFilterCriteria`
> 父元模型：referenceFilter（通过 filterApiKey 关联）

## 概述
定义 referenceFilter 的具体过滤条件行。每个 referenceFilter 可包含多条 criteria，通过 AND/OR 逻辑组合。

## 新系统字段设计（15 字段）

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
| filterApiKey | dbc_varchar1 | 所属过滤apiKey | String | 关联 referenceFilter |
| filterItemApiKey | dbc_varchar2 | 过滤字段apiKey | String | 条件中的字段 |
| filterOperator | dbc_int1 | 过滤操作符 | Integer | 等于/不等于/包含等 |
| filterValue | dbc_varchar3 | 过滤值 | String | — |
| filterRowNum | dbc_int2 | 条件行号 | Integer | 用于 AND/OR 逻辑排序 |
| criteriaType | dbc_int3 | 条件类型 | Integer | 1=字段条件 |
| createdBy | created_by | 创建人 | Long | 固定列 |
| createdAt | created_at | 创建时间 | Long | 固定列 |
| updatedBy | updated_by | 修改人 | Long | 固定列 |
| updatedAt | updated_at | 修改时间 | Long | 固定列 |
