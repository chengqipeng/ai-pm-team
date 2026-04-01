# pickOption — 选项值元模型

> 元模型 api_key：`pickOption`
> p_meta_model 注册：enable_common=1, enable_tenant=1, db_table=`p_tenant_pick_option`
> 父元模型：item（通过 itemApiKey 关联）
> 子元模型：无
> Java Entity：`PickOption.java` | API 模型：`XPickOption.java`

## 概述
定义 PICKLIST（单选）和 MULTIPICKLIST（多选）类型字段的选项值列表。每个选项有唯一的 apiKey、显示标签和排序序号。

## 存储路由
| 层级 | 表名 | 说明 |
|:---|:---|:---|
| Common | `p_common_metadata` | 系统出厂选项值（WHERE metamodel_api_key='pickOption'） |
| Tenant | `p_tenant_pick_option` | 租户自定义选项值，结构与 p_common_metadata 一致 + tenant_id |

- 读取：先查 Common，再查 Tenant，按 entity_api_key + item_api_key + api_key 合并
- 写入：`DynamicTableNameHolder.executeWith('p_tenant_pick_option')` 路由到 Tenant 表

## 字段定义（19 个）

### 基础信息（固定列映射）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | — |
| entityApiKey | entity_api_key | 所属对象apiKey | String | 三级定位 |
| itemApiKey | item_api_key | 所属字段apiKey | String | 关联到父 item |
| apiKey | api_key | 选项apiKey | String | 同一字段内唯一 |
| label | label | 选项标签 | String | — |
| labelKey | label_key | 选项标签Key | String | 国际化 |
| description | description | 描述 | String | — |

### 扩展属性（固定列映射）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| optionOrder | option_order | 排序序号 | Integer | — |
| defaultFlg | default_flg | 是否默认 | Integer(0/1) | — |
| globalFlg | global_flg | 是否全局 | Integer(0/1) | — |
| customFlg | custom_flg | 是否定制 | Integer(0/1) | 0=标准 1=自定义 |
| deleteFlg | delete_flg | 是否删除 | Integer(0/1) | 软删除 |
| enableFlg | enable_flg | 是否启用 | Integer(0/1) | — |
| specialFlg | special_flg | 特殊标志 | Integer | — |
| optionType | NULL | 选项类型 | Integer | 无物理列 |

### 审计字段

| api_key | db_column | 类型 |
|:---|:---|:---|
| createdBy | created_by | Long |
| createdAt | created_at | Long(毫秒) |
| updatedBy | updated_by | Long |
| updatedAt | updated_at | Long(毫秒) |

## 唯一性
- pickOption.apiKey 在同一字段（entity_api_key + item_api_key）内唯一
- 定位方式：entity_api_key + item_api_key + api_key

## 业务规则
- 仅 itemType=4（PICKLIST）或 itemType=16（MULTIPICKLIST）的字段可创建 pickOption
- 删除 item 时级联删除其下所有 pickOption
- globalFlg=1 表示引用全局选项集
- enableFlg=0 时选项在 UI 下拉中不显示但数据保留
