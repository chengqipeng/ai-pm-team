# 元模型与元数据 ItemType 设计差异分析

## 一、问题背景

系统中存在两个不同层级的 `itemType`，编码体系不同，容易混淆。本文梳理两者的定义、用途、编码差异和关联关系。

## 二、两层 itemType 的定义

### 2.1 元模型层：p_meta_item.item_type

| 维度 | 说明 |
|:---|:---|
| 存储位置 | `paas_metarepo_common.p_meta_item` 表的 `item_type` 列 |
| 含义 | 描述"元模型的某个属性字段"在管理界面上的 UI 展示类型 |
| 作用对象 | 元模型的属性定义（如 entity 元模型的 `entityType` 属性、item 元模型的 `itemType` 属性） |
| 编码体系 | **老系统前端编码**（p_meta_option 约束） |
| 使用场景 | 元模型管理后台（front-admin 的元模型浏览页面）渲染字段编辑器 |

示例：`p_meta_item` 中 `metamodel_api_key='item'`, `api_key='itemType'` 这条记录的 `item_type=3`（老编码 3=SELECT），表示"item 元模型的 itemType 属性在管理界面上渲染为**单选下拉框**"。

### 2.2 元数据层：业务字段的 itemType 值

| 维度 | 说明 |
|:---|:---|
| 存储位置 | `p_common_metadata` / `p_tenant_item` 大宽表的 `dbc_int1` 列 |
| 含义 | 描述"某个业务实体的某个字段"的数据类型和 UI 交互方式 |
| 作用对象 | 业务字段定义（如 account 的 phone 字段、opportunity 的 money 字段） |
| 编码体系 | **ItemTypeEnum 编码**（Java 枚举，系统内部权威编码） |
| 使用场景 | 前端业务页面渲染字段组件、后端数据校验、公式计算类型推导 |

示例：account 的 phone 字段，其 `dbc_int1=22`（ItemTypeEnum.PHONE），表示"这个字段是电话类型，前端渲染为电话输入框"。

## 三、编码体系对照

两套编码**不一致**，老编码用于 `p_meta_item.item_type` 和 `p_meta_option` 约束，新编码用于 `ItemTypeEnum` 和元数据实例。

| 老编码（p_meta_item） | 老名称 | 新编码（ItemTypeEnum） | 新名称 | 说明 |
|:---:|:---|:---:|:---|:---|
| 1 | 文本 | 1 | TEXT | 编码一致 |
| 2 | 数字 | 5 | NUMBER | **不一致** |
| 3 | 日期 | 7 | DATE | **不一致** |
| 4 | 单选 | 2 | SELECT | **不一致** |
| 5 | 查找关联 | 10 | RELATION_SHIP | **不一致** |
| 6 | 公式 | 27 | FORMULA | **不一致** |
| 7 | 汇总 | 27 | FORMULA(rollup) | **不一致** |
| 8 | 长文本 | 4 | TEXTAREA | **不一致** |
| 9 | 布尔 | 31 | BOOLEAN | **不一致** |
| 10 | 货币 | 6 | CURRENCY | **不一致** |
| 11 | 百分比 | 33 | PERCENT | **不一致** |
| 12 | 邮箱 | 23 | EMAIL | **不一致** |
| 13 | 电话 | 22 | PHONE | **不一致** |
| 14 | URL | 24 | URL | **不一致** |
| 15 | 日期时间 | 38 | DATETIME | **不一致** |
| 16 | 多选 | 3 | MULTI_SELECT | **不一致** |
| 17 | 主从 | 41 | MASTER_DETAIL | **不一致** |
| 18 | 地理位置 | 32 | GEO | **不一致** |
| 19 | 图片 | 29 | IMAGE | **不一致** |
| 20 | 自动编号 | 9 | AUTONUMBER | **不一致** |
| 21 | 引用 | 26 | JOIN | **不一致** |
| 22 | 语音 | 39 | FILE | **不一致** |
| 27 | 计算字段 | 27 | FORMULA | 编码一致 |

> 只有 `1(文本)` 和 `27(计算字段)` 两个编码恰好一致，其余全部不同。

## 四、数据流向

```
┌─────────────────────────────────────────────────────────────────┐
│ 第一层：元模型定义（p_meta_item）                                  │
│                                                                 │
│  p_meta_item.item_type = 老编码                                  │
│  含义：这个元模型属性在管理界面上怎么渲染                             │
│  例：item 元模型的 itemType 属性 → item_type=3(老编码:单选)         │
│       → 管理界面渲染为下拉框，选项由 p_meta_option 提供              │
│                                                                 │
│  p_meta_option 约束值 = 老编码                                    │
│  例：itemType 字段的选项 → 1=文本, 5=查找关联, 10=货币...           │
│       → 管理员在下拉框中选择"查找关联"时，存入值 = 5(老编码)          │
├─────────────────────────────────────────────────────────────────┤
│ 第二层：元数据实例（p_common_metadata / p_tenant_item）             │
│                                                                 │
│  dbc_int1（itemType 值）= 新编码（ItemTypeEnum）                   │
│  含义：这个业务字段的实际数据类型                                     │
│  例：account.phone → dbc_int1=22(新编码:PHONE)                    │
│       → 前端业务页面渲染为电话输入框                                 │
│                                                                 │
│  ⚠️ 管理员通过管理界面创建字段时：                                   │
│     选择"查找关联"(老编码 5) → 系统转换为 ItemTypeEnum.RELATION_SHIP │
│     → 存入 dbc_int1 = 10(新编码)                                  │
├─────────────────────────────────────────────────────────────────┤
│ 第三层：业务数据（p_tenant_data）                                   │
│                                                                 │
│  根据 itemType(新编码) 的 defaultDataType 决定存储列：              │
│  RELATION_SHIP(10) → DataType.BIGINT → dbc_bigint 列（存 ID）    │
│  TEXT(1) → DataType.VARCHAR → dbc_varchar 列（存文本）             │
│                                                                 │
│  ⚠️ 特殊情况：RELATION_SHIP + dataType 覆盖为 VARCHAR              │
│     → 存储在 dbc_varchar 列（存 api_key 字符串）                    │
│     → 适用于角色/部门的 parentApiKey 等禁止 ID 关联的场景            │
└─────────────────────────────────────────────────────────────────┘
```

## 五、RELATION_SHIP 在两层中的表现

### 5.1 元模型层

`p_meta_item` 中 `item_type` 的含义是"这个属性在管理界面上怎么渲染"。

对于 role/department 元模型的 `parentApiKey` 字段：
- `item_type` 应该设为**老编码中对应"关联"语义的值**
- 老编码 `5 = 查找关联`（对应新编码 `10 = RELATION_SHIP`）
- 但 `p_meta_item.item_type` 使用的是老编码体系，所以应填 `5`

### 5.2 元数据层

如果 role/department 的字段定义本身也作为元数据存储在大宽表中（`p_common_metadata` 中 `metamodel_api_key='item'` 的记录），那么：
- `dbc_int1`（itemType）= `10`（新编码 RELATION_SHIP）
- `dbc_int2`（dataType）= `1`（VARCHAR，覆盖默认的 BIGINT）
- `dbc_varchar3`（dbColumn）= `dbc_varchar5`（存储在 varchar 列）

### 5.3 对比总结

| 维度 | 元模型层（p_meta_item.item_type） | 元数据层（dbc_int1 itemType 值） |
|:---|:---|:---|
| 编码体系 | 老编码（p_meta_option 约束） | 新编码（ItemTypeEnum） |
| "关联"的编码 | 5（查找关联） | 10（RELATION_SHIP） |
| 含义 | 管理界面渲染方式 | 业务字段数据类型 |
| 存储位置 | p_meta_item 表的 item_type 列 | 大宽表的 dbc_int1 列 |
| 谁写入 | 平台初始化脚本 | 管理员操作 / 数据迁移 |
| 谁读取 | 元模型管理后台（front-admin） | 前端业务页面 + 后端服务 |

## 六、对 role/department parentApiKey 的影响

`roleParentApiKey` / `deptParentApiKey` 是 `RELATION_SHIP` 类型字段，但存储 api_key（VARCHAR）而非 id（BIGINT）。

在 `p_meta_item` 中的注册：

| 字段 | 值 | 说明 |
|:---|:---|:---|
| metamodel_api_key | role / department | 所属元模型 |
| api_key | roleParentApiKey / deptParentApiKey | 字段名 |
| item_type | 5 | **老编码**：查找关联 |
| data_type | 1 | VARCHAR（覆盖 RELATION_SHIP 默认的 BIGINT） |
| db_column | dbc_varchar5 | 存储在 varchar 列（因为存的是 api_key 字符串） |

在元数据实例（`p_common_metadata` 中 `metamodel_api_key='item'`）中：

| dbc 列 | 值 | 说明 |
|:---|:---|:---|
| dbc_int1（itemType） | 10 | **新编码**：RELATION_SHIP |
| dbc_int2（dataType） | 1 | VARCHAR（覆盖默认 BIGINT） |
| dbc_varchar3（dbColumn） | dbc_varchar5 | 物理存储列 |

## 七、设计建议

1. **不要混用两套编码**：`p_meta_item.item_type` 始终用老编码，元数据实例的 `dbc_int1` 始终用新编码（ItemTypeEnum）
2. **RELATION_SHIP 的 dataType 可以覆盖**：当关联字段存储 api_key 而非 id 时，将 `dataType` 从默认的 `3(BIGINT)` 覆盖为 `1(VARCHAR)`，`db_column` 使用 `dbc_varchar` 前缀
3. **前端需要编码转换**：管理后台创建字段时，用户选择的是老编码（p_meta_option 约束），保存到元数据实例时需要转换为新编码（ItemTypeEnum）
4. **后续统一方向**：长期目标是统一为 ItemTypeEnum 编码，但当前 p_meta_option 中的约束值仍为老编码，需要在前端管理界面做映射
