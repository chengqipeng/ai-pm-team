# globalPickDependency — 全局选项集依赖元模型

> 老系统常量：`METAMODEL_ID_GLOBAL_PICK_DEPENDENCY` / `METAMODEL_ID_GLOBAL_PICK_DEPENDENCY_DETAIL`
> 老系统 DTO：`XItemDependency` / `XItemDependencyDetail`（与 itemDependency 共用）
> 父元模型：globalPickOption（通过 entityApiKey 关联全局选项集标识）
> 子元模型：globalPickDependencyDetail（依赖明细）

## 概述

全局选项集依赖定义全局选项集中两个选项字段之间的级联约束，结构与 itemDependency 完全一致。区别在于 entityApiKey 指向全局选项集标识（如 `-101`）而非普通 entity。

老系统中 globalPickDependency 和 itemDependency 共用 `XItemDependency` DTO，通过 `globalDependencyApiKey` 字段关联。新系统保持独立元模型注册以兼容数据迁移。

## 新系统字段设计

### globalPickDependency（15 字段，与 itemDependency 一致）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| entityApiKey | entity_api_key | 全局选项集标识 | String | 固定列 |
| apiKey | api_key | 依赖apiKey | String | 固定列 |
| label | label | 标签 | String | 固定列 |
| labelKey | label_key | 多语言Key | String | 固定列 |
| description | description | 描述 | String | 固定列 |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 固定列 |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列 |
| controlItemApiKey | dbc_varchar1 | 控制字段apiKey | String | — |
| dependentItemApiKey | dbc_varchar2 | 依赖字段apiKey | String | — |
| createdBy | created_by | 创建人 | Long | 固定列 |
| createdAt | created_at | 创建时间 | Long | 固定列 |
| updatedBy | updated_by | 修改人 | Long | 固定列 |
| updatedAt | updated_at | 修改时间 | Long | 固定列 |

### globalPickDependencyDetail（15 字段，与 itemDependencyDetail 一致）

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| entityApiKey | entity_api_key | 全局选项集标识 | String | 固定列 |
| apiKey | api_key | 明细apiKey | String | 固定列 |
| label | label | 标签 | String | 固定列 |
| labelKey | label_key | 多语言Key | String | 固定列 |
| description | description | 描述 | String | 固定列 |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 固定列 |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列 |
| dependencyApiKey | dbc_varchar1 | 所属依赖apiKey | String | 关联 globalPickDependency |
| controlOptionCode | dbc_int1 | 控制选项编码 | Integer | — |
| dependentOptionCodes | dbc_varchar2 | 依赖选项编码列表 | String | 逗号分隔 |
| createdBy | created_by | 创建人 | Long | 固定列 |
| createdAt | created_at | 创建时间 | Long | 固定列 |
| updatedBy | updated_by | 修改人 | Long | 固定列 |
| updatedAt | updated_at | 修改时间 | Long | 固定列 |

## p_meta_link

| api_key | 父元模型 | 子元模型 | 关联字段 | 级联删除 |
|:---|:---|:---|:---|:---|
| globalPick_to_dependency | globalPickOption | globalPickDependency | entityApiKey | 是 |
| globalPickDependency_to_detail | globalPickDependency | globalPickDependencyDetail | dependencyApiKey | 是 |
