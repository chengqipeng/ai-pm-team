# referenceFilter — 关联过滤元模型

> 元模型 api_key：`referenceFilter`
> p_meta_model 注册：enable_common=1, enable_tenant=1, db_table=`p_tenant_refer_filter`
> 父元模型：item（通过 itemApiKey 关联）
> 子元模型：无
> Java Entity：`ReferFilter.java` | API 模型：无独立 X 模型

## 概述
定义 RELATION_SHIP 类型字段的下拉过滤条件。当用户在 UI 上选择关联记录时，系统根据 filterFormula 过滤候选列表。

## 存储路由
| 层级 | 表名 | 说明 |
|:---|:---|:---|
| Common | `p_common_metadata` | 系统出厂过滤条件（WHERE metamodel_api_key='referenceFilter'） |
| Tenant | `p_tenant_refer_filter` | 租户自定义过滤条件，结构与 p_common_metadata 一致 + tenant_id |

- 读取：先查 Common，再查 Tenant，按 entity_api_key + item_api_key + api_key 合并
- 写入：`DynamicTableNameHolder.executeWith('p_tenant_refer_filter')` 路由到 Tenant 表

## 字段定义（12 个）

### 基础信息（固定列映射）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | — |
| entityApiKey | entity_api_key | 所属对象apiKey | String | 三级定位 |
| itemApiKey | item_api_key | 所属字段apiKey | String | 关联到父 item |

### 扩展属性（固定列映射）

| api_key | db_column | label | 类型 | 取值约束 |
|:---|:---|:---|:---|:---|
| filterMode | filter_mode | 过滤模式 | Integer | 0=无过滤, 1=简单过滤, 2=公式过滤 |
| filterFormula | filter_formula | 过滤表达式 | String | — |
| activeFlg | active_flg | 是否启用 | Integer(0/1) | — |
| andOr | andor | 操作符 | Integer | AND/OR 逻辑 |
| deleteFlg | delete_flg | 删除标识 | Integer(0/1) | 软删除 |

### 审计字段

| api_key | db_column | 类型 |
|:---|:---|:---|
| createdBy | created_by | Long |
| createdAt | created_at | Long(毫秒) |
| updatedBy | updated_by | Long |
| updatedAt | updated_at | Long(毫秒) |

## 业务规则
- 仅 itemType=5（RELATION_SHIP）或 itemType=17（MASTER_DETAIL）的字段可创建 referenceFilter
- filterMode=0 时无过滤，filterMode=1 时简单条件，filterMode=2 时使用公式
- 删除 item 时级联删除其下所有 referenceFilter
- activeFlg=0 时过滤规则不生效
