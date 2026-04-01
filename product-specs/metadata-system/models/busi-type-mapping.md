# busiTypeMapping — 业务类型映射元模型

> 老系统常量：`METAMODEL_ID_BUSITYPE_MAPPING` / `METAMODEL_ID_BUSITYPE_MAPPING_DETAIL`
> 老系统 DTO：`XBusiTypeMapping` / `XBusiTypeMappingDetail`
> 父元模型：entity（通过 entityApiKey 关联主对象）

## 概述
业务类型映射定义主从对象之间业务类型的关联关系。当主对象选择某个业务类型时，从对象自动筛选对应的业务类型。

## busiTypeMapping 主元模型（16 字段）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| entityApiKey | entity_api_key | 主对象apiKey | String | 固定列 |
| apiKey | api_key | 映射apiKey | String | 固定列（格式：masterApiKey_childApiKey） |
| label | label | 标签 | String | 固定列 |
| labelKey | label_key | 多语言Key | String | 固定列 |
| description | description | 描述 | String | 固定列 |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 固定列 |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列 |
| masterEntityApiKey | dbc_varchar1 | 主对象apiKey | String | 关联 entity |
| childEntityApiKey | dbc_varchar2 | 从对象apiKey | String | 关联 entity |
| createdBy | created_by | 创建人 | Long | 固定列 |
| createdAt | created_at | 创建时间 | Long | 固定列 |
| updatedBy | updated_by | 修改人 | Long | 固定列 |
| updatedAt | updated_at | 修改时间 | Long | 固定列 |

## busiTypeMappingDetail 子元模型（16 字段）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| entityApiKey | entity_api_key | 主对象apiKey | String | 固定列 |
| apiKey | api_key | 明细apiKey | String | 固定列 |
| label | label | 标签 | String | 固定列 |
| labelKey | label_key | 多语言Key | String | 固定列 |
| description | description | 描述 | String | 固定列 |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 固定列 |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列 |
| mappingApiKey | dbc_varchar1 | 所属映射apiKey | String | 关联 busiTypeMapping |
| masterBusiTypeApiKey | dbc_varchar2 | 主业务类型apiKey | String | 关联 busiType |
| childBusiTypeApiKey | dbc_varchar3 | 从业务类型apiKey | String | 关联 busiType |
| mappingOrder | dbc_int1 | 排序序号 | Integer | — |
| createdBy | created_by | 创建人 | Long | 固定列 |
| createdAt | created_at | 创建时间 | Long | 固定列 |
| updatedBy | updated_by | 修改人 | Long | 固定列 |
| updatedAt | updated_at | 修改时间 | Long | 固定列 |
