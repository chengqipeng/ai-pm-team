# busiType — 业务类型元模型

> 元模型 api_key：`busiType`
> 老系统常量：`MetaConstants.METAMODEL_ID_BUSI_TYPE`
> 老系统 DTO：`XBusiType` | 老系统 PO：`BusiType` / `EntityBelongType`
> 老系统存储：标准→`b_entity_belong_type`，自定义→`p_custom_busitype`
> 父元模型：entity（通过 entityApiKey 关联）
> 子元模型：busiTypePickOption（业务类型选项值）、busiTypeMapping（业务类型映射）
> 状态：❌ 未迁移到新系统

## 概述

业务类型（Business Type / Record Type）定义 entity 上的记录分类。同一个 entity（如 Account）可以有多种业务类型（如"标准客户"、"PRM 客户"、"退货单客户"），不同业务类型可以有不同的布局、字段可见性和选项值范围。

核心场景：
- 同一对象的不同记录类型展示不同的页面布局
- 不同业务类型下 PICKLIST 字段显示不同的选项子集
- 按业务类型控制职能权限（哪些角色可以看到哪些业务类型的数据）

## 老系统存储架构

老系统 busiType 采用双表存储（标准/自定义分离），与新系统的 Common/Tenant 分层不同：

| 数据类型 | 老表名 | 说明 |
|:---|:---|:---|
| 标准业务类型 | `b_entity_belong_type` | 系统预置，字段名与自定义表不完全一致 |
| 自定义业务类型 | `p_custom_busitype` | 租户创建 |
| 业务类型选项值 | `p_custom_busitype_pickoption` | 业务类型下的 PICKLIST 选项子集 |
| 业务类型部门关联 | `p_custom_busitype_depart` | 业务类型与部门的关联 |

> 注意：标准表 `b_entity_belong_type` 的字段命名与自定义表不一致（如 `belong_id` vs `entity_id`、`del_flg` vs `delete_flg`、`type_name` vs `label`），老系统通过 `MetaDtoKit.dealXItemMapSpecialAdd` 做特殊映射。

## 字段定义

### 从 XBusiType DTO 和 BusiType PO 提取的完整字段

> 来源：`BusiTypeAO.java`（ao2Dto/dto2Ao 方法）+ `CommonDataQuery.setBusiTypeField` + `BusiTypeServiceImpl`

| 老字段名 | Java 类型 | 老 db_column（自定义表） | 说明 | 新 api_key（建议） |
|:---|:---|:---|:---|:---|
| id | Long | id | 雪花主键 | — |
| tenantId | Long | tenant_id | 租户 ID | — |
| objectId | Long | entity_id | 所属对象 ID | entityApiKey |
| apiKey | String | api_key | 业务类型唯一标识 | apiKey |
| name | String | name | 内部名称 | — （丢弃，用 label） |
| label | String | label | 显示标签 | label |
| labelKey | String | label_key | 多语言 Key | labelKey |
| namespace | String | — | 命名空间（从元数据层获取） | namespace |
| description | String | description | 描述 | description |
| helpText | String | — | 帮助文本 | helpText |
| helpTextKey | String | — | 帮助文本 Key | helpTextKey |
| isCustom / customFlg | boolean/Integer | custom_flg | 是否自定义 | customFlg |
| isActive / enableFlg | boolean/Integer | enable_flg | 是否启用 | enableFlg |
| deleteFlg | Integer | delete_flg | 软删除 | deleteFlg |
| specialFlg / businessFlg | Short | special_flg | 特殊标志（1=单业务类型, 10=退货单, 20=PRM, 100=巡访） | specialFlg |
| busiTypeOrder | Short | busi_type_order | 排序序号 | busiTypeOrder |
| parentId | Long | parent_id | 父业务类型 ID（树形结构） | parentApiKey |
| depth | Integer | depth | 层级深度 | depth |
| dummy | Integer | dummy | 虚拟标记 | — （丢弃） |
| defaultFlg | Integer | default_flg | 是否默认业务类型 | defaultFlg |
| createdAt | Long | created_at | 创建时间 | createdAt |
| createdBy | Long | created_by | 创建人 | createdBy |
| updatedAt | Long | updated_at | 修改时间 | updatedAt |
| updatedBy | Long | updated_by | 修改人 | updatedBy |

### 新系统字段设计（按新规范）

> 遵循：camelCase 命名、xxxFlg 布尔后缀、api_key 关联（禁止 ID）、固定列优先

| api_key | db_column | label | 类型 | 说明 |
|:---|:---|:---|:---|:---|
| namespace | namespace | 命名空间 | String | 固定列 |
| entityApiKey | entity_api_key | 所属对象apiKey | String | 固定列，关联父 entity |
| apiKey | api_key | 业务类型apiKey | String | 固定列，同一 entity 内唯一 |
| label | label | 显示标签 | String | 固定列 |
| labelKey | label_key | 多语言Key | String | 固定列 |
| description | description | 描述 | String | 固定列 |
| customFlg | custom_flg | 自定义标记 | Integer(0/1) | 固定列（基类 BaseMetaCommonEntity 提供） |
| deleteFlg | delete_flg | 删除标记 | Integer(0/1) | 固定列 |
| enableFlg | dbc_smallint1 | 启用标记 | Integer(0/1) | 0=禁用, 1=启用 |
| defaultFlg | dbc_smallint2 | 默认业务类型 | Integer(0/1) | 每个 entity 最多一个 |
| specialFlg | dbc_int1 | 特殊标志 | Integer | 1=单业务类型, 10=退货单, 20=PRM, 100=巡访 |
| busiTypeOrder | dbc_int2 | 排序序号 | Integer | — |
| depth | dbc_int3 | 层级深度 | Integer | 树形结构层级 |
| parentApiKey | dbc_varchar1 | 父业务类型apiKey | String | 树形结构父节点（api_key 关联） |
| helpText | dbc_varchar2 | 帮助文本 | String | — |
| helpTextKey | dbc_varchar3 | 帮助文本Key | String | 国际化 |
| descriptionKey | dbc_varchar4 | 描述Key | String | 国际化 |

### dbc 列使用汇总

| 列类型 | 使用编号 | 总数 |
|:---|:---|:---|
| dbc_varchar | 1~4 | 4 |
| dbc_int | 1~3 | 3 |
| dbc_smallint | 1~2 | 2 |
| 合计 | | 9 |

## 新系统 p_meta_model 注册（建议）

```sql
INSERT INTO p_meta_model (api_key, label, label_key, namespace, metamodel_type, 
  enable_common, enable_tenant, entity_dependency, db_table, description)
VALUES ('busiType', '业务类型', 'meta.model.busiType', 'system', 1,
  1, 1, 1, 'p_tenant_busi_type', '业务类型元模型，定义对象的记录分类');
```

## 新系统存储路由（建议）

| 层级 | 表名 | 说明 |
|:---|:---|:---|
| Common | `p_common_metadata` | 系统出厂业务类型（WHERE metamodel_api_key='busiType'） |
| Tenant | `p_tenant_busi_type` | 租户自定义业务类型，结构与 p_common_metadata 一致 + tenant_id |

## 层级关系

```
entity（对象）
  └── busiType（业务类型）← entityApiKey 关联，级联删除
        ├── busiTypePickOption（业务类型选项值）← busiTypeApiKey 关联
        ├── busiTypeMapping（业务类型映射）← busiTypeApiKey 关联
        │     └── busiTypeMappingDetail（映射明细）
        └── busiType（子业务类型）← parentApiKey 自引用（树形）
```

## 迁移要点

### 关键改造

| 改造项 | 老系统 | 新系统 |
|:---|:---|:---|
| 存储 | 双表（b_entity_belong_type + p_custom_busitype） | 统一 Common/Tenant 大宽表 |
| 关联 | objectId（Long ID） | entityApiKey（String api_key） |
| 父子关系 | parentId（Long ID） | parentApiKey（String api_key） |
| 布尔字段 | isCustom/isActive（boolean） | customFlg/enableFlg（Integer 0/1） |
| 命名 | businessFlg/specialFlg 混用 | 统一 specialFlg |
| 删除标记 | 标准表 del_flg / 自定义表 delete_flg | 统一 delete_flg |

### 数据迁移 SQL 思路

```sql
-- 1. 标准业务类型迁移（b_entity_belong_type → p_common_metadata）
--    注意字段名映射：belong_id→entity_api_key, type_name→label, del_flg→delete_flg

-- 2. 自定义业务类型迁移（p_custom_busitype → p_tenant_busi_type）
--    注意：entity_id→entity_api_key（需查 entity 表转换）
--    注意：parent_id→parentApiKey（需查自身表转换）

-- 3. specialFlg 值保持不变（1/10/20/100），无需编码转换
```

## 业务规则

- busiType.apiKey 在同一 entity 内唯一
- 每个 entity 至少有一个 defaultFlg=1 的业务类型
- enableFlg=0 时业务类型在 UI 中不可选但已有数据保留
- 删除 entity 时级联删除其下所有 busiType
- specialFlg 用于标识特殊业务场景（退货单、PRM 等），普通业务类型 specialFlg=0 或 null
- 支持树形结构（parentApiKey + depth），但大多数场景只有一层
