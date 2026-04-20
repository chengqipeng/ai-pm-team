# globalPickOption — 全局选项集元模型

> 元模型 api_key：`globalPickOption`
> p_meta_model 注册：enable_common=1, enable_tenant=1, db_table=`p_tenant_global_pick_option`
> 父元模型：无（第1层独立元模型）
> 子元模型：globalPickDependency（全局选项集依赖）
> Java Entity：`GlobalPickOption.java`

## 概述

全局选项集定义可被多个字段共享引用的选项集（如省份、城市、币种、行业等）。
通过 entityApiKey 区分选项集定义和选项值：
- entityApiKey 为空 → 选项集定义（如 province、city、currencyUnit）
- entityApiKey 非空 → 选项值（如"北京"、"上海"），entityApiKey 指向所属选项集的 apiKey

## 存储路由

| 层级 | 表名 | 说明 |
|:---|:---|:---|
| Common | `p_common_metadata` | 系统出厂选项集定义及选项值（WHERE metamodel_api_key='globalPickOption'） |
| Tenant | `p_tenant_global_pick_option` | 租户自定义选项集，结构与 p_common_metadata 一致 + tenant_id |

- 读取：先查 Common，再查 Tenant，按 apiKey 合并（Tenant 覆盖 Common，delete_flg=1 遮蔽）
- 写入：通过 DynamicTableNameHolder 路由到 p_tenant_global_pick_option

## 字段定义

### 基础信息（固定列映射，CommonMetadataConverter Step 1 自动处理）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | system/product/custom |
| entityApiKey | entity_api_key | 所属选项集apiKey | String | 选项集定义时为空，选项值时指向所属选项集 |
| apiKey | api_key | 选项集/选项apiKey | String | 全局唯一 |
| label | label | 显示名称 | String | — |
| labelKey | label_key | 多语言Key | String | 国际化 |
| description | description | 描述 | String | — |
| descriptionKey | description_key | 描述多语言Key | String | — |
| customFlg | custom_flg | 是否定制 | Integer(0/1) | 0=标准 1=自定义 |

### 扩展属性（dbc 列映射，需在 p_meta_item 中注册）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| optionOrder | dbc_int1 | 排序序号 | Integer | — |
| defaultFlg | dbc_smallint1 | 是否默认 | Integer(0/1) | — |
| enableFlg | dbc_smallint2 | 是否启用 | Integer(0/1) | — |

### 审计字段（固定列映射）

| api_key | db_column | 类型 |
|:---|:---|:---|
| createdBy | created_by | Long |
| createdAt | created_at | Long(毫秒) |
| updatedBy | updated_by | Long |
| updatedAt | updated_at | Long(毫秒) |

## 唯一性

- globalPickOption.apiKey 全局唯一
- 选项集定义：entityApiKey 为空，apiKey 如 "province"、"currencyUnit"
- 选项值：entityApiKey 指向选项集 apiKey，apiKey 在同一选项集内唯一

## 业务规则

- 系统出厂选项集（namespace=system）存储在 Common 级，所有租户自动继承
- 租户可覆盖 Common 级选项值（同 apiKey 的 Tenant 记录覆盖 Common 记录）
- 租户可通过 delete_flg=1 遮蔽不需要的 Common 级选项
- 租户可新增自定义选项集（namespace=custom）
- 字段引用全局选项集时，通过 item.referGlobalFlg=1 + item.globalPickItemApiKey 关联

## 老系统对照

| 老系统 | 新系统 | 说明 |
|:---|:---|:---|
| globalPickItem（x_global_pickitem 表） | globalPickOption（entityApiKey 为空的记录） | 选项集定义 |
| globalPickOption（p_custom_pickoption 表，globalFlg=1） | globalPickOption（entityApiKey 非空的记录） | 选项值 |
| tenant_id=-101 模拟 Common 级 | enable_common=1，存储在 p_common_metadata | 标准合并链路 |
| initGlobalPickItems() 复制到租户 | Common/Tenant 合并读取，无需复制 | 自动继承 |
