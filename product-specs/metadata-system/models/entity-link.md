# entityLink — 关联关系元模型

> 元模型 api_key：`entityLink`
> p_meta_model 注册：enable_common=1, enable_tenant=1, db_table=`p_tenant_entity_link`
> 父元模型：entity（通过 entityApiKey 关联）
> 子元模型：无
> Java Entity：`EntityLink.java` | API 模型：`XLink.java`

## 概述
定义两个 entity 之间的关联关系，支持 LOOKUP（查找）、主从、多对多三种关联类型。关联关系决定了字段的 LOOKUP 目标、级联删除策略和访问控制。

## 存储路由
| 层级 | 表名 | 说明 |
|:---|:---|:---|
| Common | `p_common_metadata` | 系统出厂关联（WHERE metamodel_api_key='entityLink'） |
| Tenant | `p_tenant_entity_link` | 租户自定义关联，结构与 p_common_metadata 一致 + tenant_id |

- 读取：先查 Common，再查 Tenant，按 api_key 合并
- 写入：`DynamicTableNameHolder.executeWith('p_tenant_entity_link')` 路由到 Tenant 表

## 字段定义（9 个）

### 基础信息（固定列映射）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| apiKey | api_key | 关联apiKey | String | 全局唯一 |
| label | label | 显示标签 | String | — |
| labelKey | label_key | 多语言Key | String | — |
| namespace | namespace | 命名空间 | String | — |
| description | description | 描述 | String | — |
| descriptionKey | description_key | 描述Key | String | — |
| entityApiKey | entity_api_key | 所属对象apiKey | String | 关联到父 entity |

### 扩展属性（dbc 列映射）

| api_key | db_column | label | 类型 | 取值约束 |
|:---|:---|:---|:---|:---|
| typeProperty | dbc_varchar_1 | 类型属性 | String | — |
| parentEntityApiKey | dbc_varchar_2 | 父对象apiKey | String | 关联源 entity |
| childEntityApiKey | dbc_varchar_3 | 子对象apiKey | String | 关联目标 entity |
| descriptionKey | dbc_varchar_4 | 描述Key | String | — |
| linkType | dbc_int_1 | 关联类型 | Integer | 0=LOOKUP, 1=主从, 2=多对多 |
| detailLinkFlg | dbc_smallint_1 | 明细关联 | Integer(0/1) | 0=否, 1=是 |
| cascadeDelete | dbc_smallint_2 | 级联删除 | Integer | 0=不级联, 1=级联删除, 2=阻止删除 |
| accessControl | dbc_smallint_3 | 访问控制 | Integer | 0=无控制, 1=读写控制 |
| enableFlg | dbc_smallint_4 | 启用标记 | Integer(0/1) | 0=否, 1=是 |

> 注意：entityLink 的 dbc 列历史上使用 `dbc_varchar_1`（带下划线）格式，这是老系统遗留。新增字段应使用 `dbc_xxxN` 格式。

## 业务规则
- entityLink.apiKey 全局唯一
- parentEntityApiKey 和 childEntityApiKey 必须指向已存在的 entity
- linkType=1（主从）时，子对象的 LOOKUP 字段自动设置 cascadeDelete
- 删除 entity 时级联删除其下所有 entityLink
