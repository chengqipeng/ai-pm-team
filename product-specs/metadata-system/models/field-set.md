# fieldSet — 字段集元模型

> 老系统常量：`METAMODEL_ID_FIELD_SET` / `METAMODEL_ID_FIELD_SET_ITEM`
> 老系统 DTO：`XFieldSet` / `XFieldSetItem`
> 父元模型：entity（通过 entityApiKey 关联）
> 子元模型：fieldSetItem（字段集字段）

## 概述

字段集（Field Set）定义 entity 上的一组字段集合，用于在不同场景下控制哪些字段可见。典型用途包括：布局中的字段分组、API 返回字段范围控制、移动端精简字段展示等。

## 老系统字段

### XFieldSet
| 老字段名 | 说明 | 新 api_key |
|:---|:---|:---|
| objectId | 所属对象 ID | entityApiKey |
| apiKey | 唯一标识 | apiKey |
| label | 标签 | label |
| labelKey | 多语言 Key | labelKey |
| description | 描述 | description |
| fieldSetOrder | 排序序号 | fieldSetOrder |
| customFlag | 是否自定义 | customFlg（基类） |

### XFieldSetItem
| 老字段名 | 说明 | 新 api_key |
|:---|:---|:---|
| objectId | 所属对象 ID | entityApiKey |
| fieldSetId | 所属字段集 ID | fieldSetApiKey |
| itemId | 关联字段 ID | itemApiKey |

## 新系统字段设计

### fieldSet 主元模型（15 字段）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| entityApiKey | entity_api_key | 所属对象 | String | 固定列 |
| apiKey | api_key | 字段集apiKey | String | 固定列 |
| label | label | 标签 | String | 固定列 |
| labelKey | label_key | 多语言Key | String | 固定列 |
| description | description | 描述 | String | 固定列 |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 固定列（基类） |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列（基类） |
| fieldSetOrder | dbc_int1 | 排序序号 | Integer | — |
| createdBy | created_by | 创建人 | Long | 固定列 |
| createdAt | created_at | 创建时间 | Long | 固定列 |
| updatedBy | updated_by | 修改人 | Long | 固定列 |
| updatedAt | updated_at | 修改时间 | Long | 固定列 |

### fieldSetItem 子元模型（15 字段）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| entityApiKey | entity_api_key | 所属对象 | String | 固定列 |
| apiKey | api_key | apiKey | String | 固定列 |
| label | label | 标签 | String | 固定列 |
| labelKey | label_key | 多语言Key | String | 固定列 |
| description | description | 描述 | String | 固定列 |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 固定列（基类） |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列（基类） |
| fieldSetApiKey | dbc_varchar1 | 所属字段集 | String | 关联 fieldSet |
| itemApiKey | dbc_varchar2 | 关联字段 | String | 关联 item |
| itemOrder | dbc_int1 | 排序序号 | Integer | — |
| createdBy | created_by | 创建人 | Long | 固定列 |
| createdAt | created_at | 创建时间 | Long | 固定列 |
| updatedBy | updated_by | 修改人 | Long | 固定列 |
| updatedAt | updated_at | 修改时间 | Long | 固定列 |

## p_meta_link

| api_key | 父元模型 | 子元模型 | 关联字段 | 级联删除 |
|:---|:---|:---|:---|:---|
| entity_to_fieldSet | entity | fieldSet | entityApiKey | 是 |
| fieldSet_to_item | fieldSet | fieldSetItem | fieldSetApiKey | 是 |

## 业务规则

- fieldSet.apiKey 在同一 entity 内唯一
- 删除 entity 时级联删除其下所有 fieldSet
- 删除 fieldSet 时级联删除其下所有 fieldSetItem
- fieldSetItem.itemApiKey 必须指向同一 entity 下的有效 item
