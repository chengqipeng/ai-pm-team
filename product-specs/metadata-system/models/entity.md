# entity — 自定义对象元模型

> 元模型 api_key：`entity`
> p_meta_model 注册：enable_common=1, enable_tenant=1, db_table=`p_tenant_entity`
> 父元模型：无（顶层）
> 子元模型：item（字段）、entityLink（关联关系）、checkRule（校验规则）
> Java Entity：`Entity.java` | API 模型：`XEntity.java`

## 概述
定义平台中的业务对象（如 Account、Contact、Opportunity），是元数据体系的顶层实体。所有字段（item）、关联关系（entityLink）、校验规则（checkRule）都挂在 entity 下。

## 存储路由
| 层级 | 表名 | 说明 |
|:---|:---|:---|
| Common | `p_common_metadata` | 系统出厂对象（WHERE metamodel_api_key='entity'），所有租户共享 |
| Tenant | `p_tenant_entity` | 租户自定义对象，结构与 p_common_metadata 一致 + tenant_id |

- 读取：先查 Common，再查 Tenant，按 api_key 合并（Tenant 覆盖 Common，delete_flg=1 隐藏）
- 写入：`DynamicTableNameHolder.executeWith('p_tenant_entity')` 路由到 Tenant 表
- 删除 Common 对象：插入 delete_flg=1 的 Tenant 记录（遮蔽删除）

## 字段定义（32 个）

### 基础信息（固定列映射）
> 以下字段由基类 BaseMetaCommonEntity / BaseMetaTenantEntity 提供，所有元模型共享

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| apiKey | api_key | 对象apiKey | String | 全局唯一标识 |
| label | label | 显示标签 | String | 中文名称 |
| labelKey | label_key | 多语言Key | String | 国际化 |
| namespace | namespace | 命名空间 | String | system/product/custom |
| description | description | 描述 | String | — |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 0=标准 1=自定义 |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 软删除 |

### 扩展属性（dbc 列映射，32 个 p_meta_item 记录）

| api_key | db_column | label | 类型 | 取值约束 |
|:---|:---|:---|:---|:---|
| svgApiKey | dbc_varchar1 | SVG图标 | String | — |
| dbTable | dbc_varchar2 | 数据库表名 | String | — |
| svgColor | dbc_varchar3 | SVG颜色 | String | — |
| descriptionKey | dbc_varchar4 | 描述Key | String | 国际化 |
| entityType | dbc_int1 | 对象类型 | Integer | 0=标准, 1=自定义, 2=系统, 3=虚拟 |
| customEntitySeq | dbc_int2 | 对象排序号 | Integer | — |
| businessCategory | dbc_int3 | 业务分类 | Integer | — |
| duplicateRuleFlg | dbc_int4 | 启用查重规则 | Integer(0/1) | — |
| scriptExecutorFlg | dbc_int5 | 启用脚本执行器 | Integer(0/1) | — |
| archivedFlg | dbc_int6 | 已归档 | Integer(0/1) | — |
| groupMemberFlg | dbc_int7 | 启用组成员 | Integer(0/1) | — |
| dynamicFeedFlg | dbc_int8 | 启用动态 | Integer(0/1) | — |
| busiTypeFlg | dbc_smallint1 | 启用业务类型 | Integer(0/1) | — |
| checkRuleFlg | dbc_smallint2 | 启用校验规则 | Integer(0/1) | — |
| enableFlg | dbc_smallint3 | 启用标记 | Integer(0/1) | 0=否, 1=是 |
| customFlg | dbc_smallint4 | 自定义标记 | Integer(0/1) | 0=标准, 1=自定义 |
| historyLogFlg | dbc_smallint5 | 启用历史日志 | Integer(0/1) | — |
| detailFlg | dbc_smallint6 | 明细对象 | Integer(0/1) | — |
| teamFlg | dbc_smallint7 | 启用团队 | Integer(0/1) | — |
| socialFlg | dbc_smallint8 | 启用社交 | Integer(0/1) | — |
| hiddenFlg | dbc_smallint9 | 隐藏标记 | Integer(0/1) | — |
| searchableFlg | dbc_smallint10 | 可搜索 | Integer(0/1) | — |
| sharingFlg | dbc_smallint11 | 启用共享 | Integer(0/1) | — |
| scriptTriggerFlg | dbc_smallint12 | 脚本触发器 | Integer(0/1) | — |
| activityFlg | dbc_smallint13 | 启用活动 | Integer(0/1) | — |
| reportFlg | dbc_smallint14 | 启用报表 | Integer(0/1) | — |
| referFlg | dbc_smallint15 | 启用引用 | Integer(0/1) | — |
| apiFlg | dbc_smallint16 | 启用API | Integer(0/1) | — |
| configFlg | dbc_bigint1 | 配置开关 | Integer(0/1) | — |
| flowFlg | dbc_bigint2 | 启用流程 | Integer(0/1) | — |
| packageFlg | dbc_bigint3 | 启用打包 | Integer(0/1) | — |
| typeProperty | dbc_textarea1 | 类型扩展属性JSON | String | — |
| extendProperty | dbc_textarea2 | 扩展属性 | String | — |

### dbc 列使用汇总

| 列类型 | 使用编号 | 总数 |
|:---|:---|:---|
| dbc_varchar | 1~4 | 4 |
| dbc_int | 1~8 | 8 |
| dbc_smallint | 1~16 | 16 |
| dbc_bigint | 1~3 | 3 |
| dbc_textarea | 1~2 | 2 |
| 合计 | | 33（含 customFlg 固定列+dbc 双映射） |

## 层级关系

```
entity（对象）
  ├── item（字段）          ← entityApiKey 关联，级联删除
  │     ├── pickOption      ← itemApiKey 关联，级联删除
  │     └── referenceFilter ← itemApiKey 关联，级联删除
  ├── entityLink（关联关系） ← entityApiKey 关联，级联删除
  └── checkRule（校验规则）  ← entityApiKey 关联，级联删除
```

## 业务规则
- entity.apiKey 全局唯一
- entityType=1（自定义对象）时 customFlg=1
- 删除 entity 时级联删除所有子元数据（item/entityLink/checkRule）
- namespace=system 的 entity 不可被租户删除（遮蔽删除）
