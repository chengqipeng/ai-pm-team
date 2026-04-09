# itemDependency — 字段依赖关系元模型

> 老系统常量：`METAMODEL_ID_ITEM_DEPENDENCY` / `METAMODEL_ID_ITEM_DEPENDENCY_DETAIL`
> 老系统 DTO：`XItemDependency` / `XItemDependencyDetail`
> 老系统 PO：`ItemDependency` / `ItemDependencyDetail`
> 父元模型：item（通过 entityApiKey 关联，控制字段和依赖字段都属于同一 entity）
> 子元模型：itemDependencyDetail（依赖明细）
> 状态：❌ 未迁移

## 概述

字段依赖关系定义两个 SELECT 字段之间的级联约束。当用户选择"控制字段"的某个选项后，"依赖字段"的可选选项范围会根据依赖明细自动过滤。

典型场景：
- 省→市→区 三级联动
- 行业→子行业 二级联动
- 全局选项集的字段依赖（entityApiKey 为全局选项集标识）

老系统中 `METAMODEL_ID_GLOBAL_PICK_DEPENDENCY` 和 `METAMODEL_ID_ITEM_DEPENDENCY` 结构完全相同，新系统统一为一个 itemDependency 元模型。

## 老系统字段

### XItemDependency

| 老字段名 | Java 类型 | 说明 | 新 api_key |
|:---|:---|:---|:---|
| id | Long | 主键 | — |
| objectId | Long | 所属对象 ID | entityApiKey |
| controlItemId | Long | 控制字段 ID | controlItemApiKey |
| dependentItemId | Long | 依赖字段 ID | dependentItemApiKey |
| globalDependencyId | Long | 全局依赖引用 ID | globalDependencyApiKey |
| apiKey | String | 唯一标识 | apiKey |
| label | String | 标签 | label |
| namespace | String | 命名空间 | namespace |
| deleteFlg | Integer | 软删除 | deleteFlg |

### XItemDependencyDetail

| 老字段名 | Java 类型 | 说明 | 新 api_key |
|:---|:---|:---|:---|
| id | Long | 主键 | — |
| objectId | Long | 所属对象 ID | entityApiKey |
| itemDependencyId | Long | 所属依赖关系 ID | dependencyApiKey |
| controlItemCode | Integer | 控制字段选项编码 | controlOptionCode |
| dependentItemCodeList | String | 依赖字段选项编码列表（逗号分隔） | dependentOptionCodes |

## 新系统字段设计

### itemDependency 主元模型

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| entityApiKey | entity_api_key | 所属对象 | String | 固定列 |
| apiKey | api_key | 依赖apiKey | String | 固定列 |
| label | label | 标签 | String | 固定列 |
| labelKey | label_key | 多语言Key | String | 固定列 |
| description | description | 描述 | String | 固定列 |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 固定列（基类） |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列（基类） |
| controlItemApiKey | dbc_varchar1 | 控制字段apiKey | String | 关联 item |
| dependentItemApiKey | dbc_varchar2 | 依赖字段apiKey | String | 关联 item |
| globalDependencyApiKey | dbc_varchar3 | 全局依赖apiKey | String | 引用全局选项集依赖 |
| createdBy | created_by | 创建人 | Long | 固定列 |
| createdAt | created_at | 创建时间 | Long | 固定列 |
| updatedBy | updated_by | 修改人 | Long | 固定列 |
| updatedAt | updated_at | 修改时间 | Long | 固定列 |

### itemDependencyDetail 子元模型

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| entityApiKey | entity_api_key | 所属对象 | String | 固定列 |
| apiKey | api_key | 明细apiKey | String | 固定列 |
| label | label | 标签 | String | 固定列 |
| labelKey | label_key | 多语言Key | String | 固定列 |
| description | description | 描述 | String | 固定列 |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 固定列（基类） |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列（基类） |
| dependencyApiKey | dbc_varchar1 | 所属依赖apiKey | String | 关联 itemDependency |
| controlOptionCode | dbc_int1 | 控制选项编码 | Integer | 控制字段的 pickOption code |
| dependentOptionCodes | dbc_varchar2 | 依赖选项编码列表 | String | 逗号分隔，如 "1,2,3" |
| createdBy | created_by | 创建人 | Long | 固定列 |
| createdAt | created_at | 创建时间 | Long | 固定列 |
| updatedBy | updated_by | 修改人 | Long | 固定列 |
| updatedAt | updated_at | 修改时间 | Long | 固定列 |

## p_meta_model 注册

| api_key | label | db_table | entity_dependency |
|:---|:---|:---|:---|
| itemDependency | 字段依赖 | p_tenant_item_dependency | 1 |
| itemDependencyDetail | 依赖明细 | p_tenant_item_dependency_detail | 1 |

## p_meta_link 关联关系

| api_key | 父元模型 | 子元模型 | 关联字段 | 级联删除 |
|:---|:---|:---|:---|:---|
| item_to_itemDependency | item | itemDependency | controlItemApiKey | 是 |
| itemDependency_to_detail | itemDependency | itemDependencyDetail | dependencyApiKey | 是 |

## 层级关系

```
item（字段）
  └── itemDependency（字段依赖）← controlItemApiKey 关联
        └── itemDependencyDetail（依赖明细）← dependencyApiKey 关联
```

## 业务规则

- 控制字段和依赖字段必须属于同一 entity（或同一全局选项集）
- 控制字段和依赖字段必须是 SELECT(4) 或 MULTI_SELECT(16) 类型
- 一个字段只能作为一个依赖关系的依赖字段（不能被多个控制字段控制）
- 禁止循环依赖（A→B→C→A）
- globalDependencyApiKey 用于引用全局选项集级别的依赖定义
- 删除 item 时级联删除其作为控制字段的所有 itemDependency
- 删除 itemDependency 时级联删除其下所有 itemDependencyDetail
