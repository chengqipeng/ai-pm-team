# entity — 自定义对象元模型

> 元模型 api_key：`entity`
> p_meta_model 注册：enable_common=1, enable_tenant=1, db_table=`p_tenant_entity`
> 父元模型：无（顶层）
> 子元模型：item（字段）、entityLink（关联关系）、checkRule（校验规则）
> Java Entity：`Entity.java` | API 模型：`XEntity.java`

## 概述
定义平台中的业务对象（如 Account、Contact、Opportunity），是元数据体系的顶层实体。所有字段（item）、关联关系（entityLink）、校验规则（checkRule）都挂在 entity 下。

## 字段定义（17 个）

### 基础信息（固定列映射）
> 以下字段由基类 BaseMetaCommonEntity / BaseMetaTenantEntity 提供，所有元模型共享

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| apiKey | api_key | 对象apiKey | String | 全局唯一标识 |
| label | label | 显示标签 | String | 中文名称 |
| labelKey | label_key | 多语言Key | String | 国际化 |
| namespace | namespace | 命名空间 | String | system/product/custom |
| description | description | 描述 | String | — |
| descriptionKey | description_key | 描述Key | String | 国际化 |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 0=标准 1=自定义 |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 软删除 |

### 扩展属性（dbc 列映射）

| api_key | db_column | label | 类型 | 取值约束 |
|:---|:---|:---|:---|:---|
| svgApiKey | dbc_varchar1 | SVG图标 | String | — |
| dbTable | dbc_varchar2 | 数据库表名 | String | — |
| svgColor | dbc_varchar3 | SVG颜色 | String | — |
| entityType | dbc_int1 | 对象类型 | Integer | 0=标准, 1=自定义, 2=系统, 3=虚拟 |
| customEntitySeq | dbc_int2 | 对象排序号 | Integer | — |
| businessCategory | dbc_int3 | 业务分类 | Integer | — |
| enableFlg | dbc_smallint3 | 启用标记 | Integer(0/1) | 0=否, 1=是 |
| enableHistoryLog | dbc_smallint5 | 启用历史日志 | Integer(0/1) | — |
| enableConfig | dbc_bigint1 | 启用配置位 | Long(位掩码) | — |
| enableBusinessType | dbc_smallint1 | 启用业务类型 | Integer(0/1) | — |
| enableCheckRule | dbc_smallint2 | 启用校验规则 | Integer(0/1) | — |
| enableDuplicateRule | dbc_int4 | 启用查重规则 | Integer | — |
| enableScriptExecutor | dbc_int5 | 启用脚本执行器 | Integer | — |
| archivedFlg | dbc_int6 | 已归档 | Integer | — |
| enableGroupMember | dbc_int7 | 启用组成员 | Integer | — |
| enableDynamicFeed | dbc_int8 | 启用动态 | Integer | — |

### Java Entity 额外字段（非 p_meta_item 定义，由 Java 类直接持有）

| Java 字段 | 类型 | 说明 |
|:---|:---|:---|
| detailFlg | Integer(0/1) | 明细对象标记 |
| enableTeam | Integer(0/1) | 启用团队 |
| enableSocial | Integer(0/1) | 启用社交 |
| hiddenFlg | Integer(0/1) | 隐藏标记 |
| searchable | Integer(0/1) | 可搜索 |
| enableSharing | Integer(0/1) | 启用共享 |
| enableScriptTrigger | Integer(0/1) | 启用脚本触发器 |
| enableActivity | Integer(0/1) | 启用活动 |
| enableReport | Integer(0/1) | 启用报表 |
| enableRefer | Integer(0/1) | 启用引用 |
| enableApi | Integer(0/1) | 启用API |
| enableFlow | Long | 启用流程 |
| enablePackage | Long | 启用打包 |
| typeProperty | String | 类型扩展属性JSON |
| extendProperty | String | 扩展属性 |

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
