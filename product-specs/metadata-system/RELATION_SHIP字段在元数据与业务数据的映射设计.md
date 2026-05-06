# RELATION_SHIP 字段在元数据与业务数据的映射设计

## 一、核心概念

`RELATION_SHIP`（itemType=10）是"关联类型"字段。同一个 RELATION_SHIP 字段在系统中存在于两个不同维度，存储内容和映射方式完全不同：

- **元数据维度**：存储"这个字段的定义"（类型、列名、关联目标...）
- **业务数据维度**：存储"这个字段的值"（具体关联到哪条记录）

## 二、两个维度的完整对比

以 account 实体的 `dimDepart`（所属部门）字段为例：

```
                    ┌──────────────────────────────────────────────┐
                    │         元数据维度（字段定义）                  │
                    │         表：p_common_metadata                 │
                    │         metamodel_api_key = 'item'            │
                    │                                              │
                    │  这条记录回答的问题：                           │
                    │  "account 有一个叫 dimDepart 的字段，          │
                    │   它是什么类型？存在哪个列？关联到哪个对象？"     │
                    │                                              │
                    │  ┌─────────────────────────────────────────┐ │
                    │  │ api_key        = 'dimDepart'            │ │
                    │  │ entity_api_key = 'account'              │ │
                    │  │ label          = '所属部门'              │ │
                    │  │ dbc_int1       = 10  ← itemType 的值     │ │
                    │  │ dbc_int2       = 3   ← dataType 的值     │ │
                    │  │ dbc_varchar3   = 'dbc_bigint1' ← dbColumn│ │
                    │  │ dbc_varchar1   = 'department'  ← 关联目标 │ │
                    │  └─────────────────────────────────────────┘ │
                    └──────────────┬───────────────────────────────┘
                                   │
                                   │ dbColumn = 'dbc_bigint1'
                                   │ 告诉系统：dimDepart 的值
                                   │ 存在业务数据表的 dbc_bigint1 列
                                   ▼
                    ┌──────────────────────────────────────────────┐
                    │         业务数据维度（字段值）                  │
                    │         表：p_tenant_data_0                   │
                    │         entity_api_key = 'account'            │
                    │                                              │
                    │  这条记录回答的问题：                           │
                    │  "鸿阳科技这个客户属于哪个部门？"               │
                    │                                              │
                    │  ┌─────────────────────────────────────────┐ │
                    │  │ id             = 500001                 │ │
                    │  │ name           = '鸿阳科技'              │ │
                    │  │ dbc_bigint1    = 1001  ← dimDepart 的值  │ │
                    │  │                  ↑                       │ │
                    │  │                  这是部门的 ID            │ │
                    │  └─────────────────────────────────────────┘ │
                    └──────────────────────────────────────────────┘
```

### 对比表

| 维度 | 元数据（字段定义） | 业务数据（字段值） |
|:---|:---|:---|
| 表 | p_common_metadata / p_tenant_item | p_tenant_data_{N} |
| metamodel_api_key | `item` | 无（业务数据表没有此列） |
| entity_api_key | `account`（这个字段属于 account） | `account`（这条数据是 account） |
| RELATION_SHIP 体现 | `dbc_int1 = 10`（itemType 值） | `dbc_bigint1 = 1001`（关联目标 ID） |
| dbc_int1 的含义 | itemType = RELATION_SHIP | 无关（业务数据的 dbc_int1 是其他字段） |
| dbc_bigint1 的含义 | 无关（元数据的 dbc_bigint1 是其他属性） | dimDepart 的值 = 部门 ID |
| 关联目标信息 | `dbc_varchar1 = 'department'`（referEntityApiKey） | 不存储（需要查元数据才知道） |

**关键理解**：同一个 dbc 列名在两张表中含义完全不同，因为它们属于不同的元模型。元数据表的 dbc 列语义由 `metamodel_api_key='item'` 的 p_meta_item 定义，业务数据表的 dbc 列语义由具体 entity 的 item 定义。

## 三、传统模式 vs api_key 关联模式

### 3.1 传统模式：RELATION_SHIP + BIGINT（存 ID）

适用于：业务实体之间的关联（account → department、opportunity → account）

```
元数据定义（p_common_metadata, metamodel_api_key='item'）:
┌──────────────────────────────────────────────────────────┐
│ api_key='dimDepart', entity_api_key='account'            │
│ dbc_int1  = 10           ← itemType = RELATION_SHIP      │
│ dbc_int2  = 3            ← dataType = BIGINT（默认）      │
│ dbc_varchar3 = 'dbc_bigint1'  ← dbColumn                 │
│ dbc_varchar1 = 'department'   ← referEntityApiKey         │
└──────────────────────────────────────────────────────────┘

业务数据（p_tenant_data_0, entity_api_key='account'）:
┌──────────────────────────────────────────────────────────┐
│ id=500001, name='鸿阳科技'                                │
│ dbc_bigint1 = 1001       ← dimDepart 的值 = 部门 BIGINT ID│
└──────────────────────────────────────────────────────────┘

读取链路：
  1. 查元数据：dimDepart 的 dbColumn='dbc_bigint1', referEntityApiKey='department'
  2. 查业务数据：dbc_bigint1 = 1001
  3. 解析关联：去 department 表查 id=1001 的记录 → "销售部"
```

### 3.2 api_key 关联模式：RELATION_SHIP + VARCHAR（存 api_key）

适用于：角色/部门的树形自关联（role → role、department → department）

```
元数据定义（p_common_metadata, metamodel_api_key='item'）:
┌──────────────────────────────────────────────────────────┐
│ api_key='deptParentApiKey', entity_api_key='department'   │
│ dbc_int1  = 10           ← itemType = RELATION_SHIP      │
│ dbc_int2  = 1            ← dataType = VARCHAR（覆盖！）   │
│ dbc_varchar3 = 'dbc_varchar5'  ← dbColumn（varchar 列！） │
│ dbc_varchar1 = 'department'    ← referEntityApiKey（自关联）│
└──────────────────────────────────────────────────────────┘

业务数据（p_tenant_department, metamodel_api_key='department'）:
┌──────────────────────────────────────────────────────────┐
│ api_key='sales_dept', label='销售部'                      │
│ dbc_varchar5 = 'root'    ← deptParentApiKey = 上级的 api_key│
└──────────────────────────────────────────────────────────┘

读取链路：
  1. 查元数据：deptParentApiKey 的 dbColumn='dbc_varchar5', referEntityApiKey='department'
  2. 查业务数据：dbc_varchar5 = 'root'
  3. 解析关联：去 department 表查 api_key='root' 的记录 → "鸿阳科技"
```

### 3.3 两种模式的差异对比

| 维度 | 传统模式（存 ID） | api_key 模式（存 api_key） |
|:---|:---|:---|
| **元数据层** | | |
| itemType (dbc_int1) | `10` (RELATION_SHIP) | `10` (RELATION_SHIP) |
| dataType (dbc_int2) | `3` (BIGINT) — 默认值 | `1` (VARCHAR) — **覆盖** |
| dbColumn (dbc_varchar3) | `dbc_bigint{N}` | `dbc_varchar{N}` |
| referEntityApiKey (dbc_varchar1) | 目标实体 api_key | 目标实体 api_key |
| **业务数据层** | | |
| 存储列类型 | BIGINT | VARCHAR |
| 存储值 | `1001`（目标记录的 id） | `'sales_dept'`（目标记录的 api_key） |
| 解析方式 | `WHERE id = 1001` | `WHERE api_key = 'sales_dept'` |
| **前端渲染** | | |
| 组件类型 | 关联选择器（相同） | 关联选择器（相同） |
| 显示值 | 查关联记录的 name/label | 查关联记录的 name/label |
| 存储值 | 数字 ID | 字符串 api_key |
| **跨环境迁移** | | |
| 可迁移性 | ❌ ID 不同环境不一致 | ✅ api_key 全局一致 |

## 四、实现机制

### 4.1 写入时：dataType 决定存储列

```java
// CommonMetadataConverter Step 3 自动推导
if (ei.getDataType() == null && ei.getItemType() != null) {
    ItemTypeEnum ite = ItemTypeEnum.fromCode(ei.getItemType());
    // RELATION_SHIP(10) → defaultDataType = BIGINT(3)
    ei.setDataType(ite.getDefaultDataType().getCode());
}
```

传统模式下 `dataType` 为 null，自动推导为 `BIGINT(3)` → 分配 `dbc_bigint{N}` 列。

api_key 模式下 `dataType` 显式设为 `VARCHAR(1)` → 分配 `dbc_varchar{N}` 列。**覆盖了默认推导**。

### 4.2 读取时：dbColumn 决定从哪列取值

```
元数据读取链路（以 account.dimDepart 为例）：

1. 查 p_meta_item（metamodel_api_key='item', entity_api_key='account'）
   → 找到 api_key='dimDepart' 的记录
   → dbColumn = 'dbc_bigint1'
   → referEntityApiKey = 'department'

2. 查 p_tenant_data_0（entity_api_key='account', id=500001）
   → 读取 dbc_bigint1 列的值 = 1001

3. 前端展示：
   → 用 1001 去 department 表查 name → "销售部"
```

```
元数据读取链路（以 department.deptParentApiKey 为例）：

1. 查 p_meta_item（metamodel_api_key='item', entity_api_key='department'）
   → 找到 api_key='deptParentApiKey' 的记录
   → dbColumn = 'dbc_varchar5'
   → referEntityApiKey = 'department'

2. 查 p_tenant_department（api_key='sales_dept'）
   → 读取 dbc_varchar5 列的值 = 'root'

3. 前端展示：
   → 用 'root' 去 department 表查 label → "鸿阳科技"
```

### 4.3 前端渲染：itemType 决定组件类型

前端不关心 dataType 是 BIGINT 还是 VARCHAR，只看 `itemType=10` → 渲染为关联选择器。

区别在于：
- 传统模式：选择器的 value 是数字 ID，提交时发送 `{ dimDepart: 1001 }`
- api_key 模式：选择器的 value 是字符串 api_key，提交时发送 `{ deptParentApiKey: 'root' }`

## 五、完整举例：department 的 deptParentApiKey

### 5.1 p_meta_item 注册（元模型层）

```sql
INSERT INTO paas_metarepo_common.p_meta_item
  (metamodel_api_key, api_key, label, item_type, data_type, db_column)
VALUES
  ('department', 'deptParentApiKey', '上级部门', 10, 1, 'dbc_varchar5');
--                                               ↑   ↑   ↑
--                                    RELATION_SHIP  VARCHAR  存储列
```

### 5.2 p_common_metadata 中的 item 定义（元数据层）

```
表：p_common_metadata
metamodel_api_key = 'item'
entity_api_key    = 'department'
api_key           = 'deptParentApiKey'

dbc_int1    = 10              -- itemType = RELATION_SHIP
dbc_int2    = 1               -- dataType = VARCHAR（覆盖默认 BIGINT）
dbc_varchar3 = 'dbc_varchar5' -- dbColumn = 存在 varchar5 列
dbc_varchar1 = 'department'   -- referEntityApiKey = 自关联
```

### 5.3 p_tenant_department 中的实际数据（业务数据层）

```
表：p_tenant_department
metamodel_api_key = 'department'

记录 1：api_key='root',       label='鸿阳科技', dbc_varchar5=NULL        -- 根节点
记录 2：api_key='sales_dept', label='销售部',   dbc_varchar5='root'      -- 上级=鸿阳科技
记录 3：api_key='cs_dept',    label='客服部',   dbc_varchar5='root'      -- 上级=鸿阳科技
记录 4：api_key='rd_frontend',label='前端组',   dbc_varchar5='rd_dept'   -- 上级=研发部
```

### 5.4 对比：如果用传统 BIGINT 模式

```
-- 元数据定义
dbc_int1    = 10              -- itemType = RELATION_SHIP
dbc_int2    = 3               -- dataType = BIGINT（默认）
dbc_varchar3 = 'dbc_bigint1'  -- dbColumn = 存在 bigint1 列

-- 业务数据
记录 1：id=1000, label='鸿阳科技', dbc_bigint1=NULL
记录 2：id=1001, label='销售部',   dbc_bigint1=1000    -- 上级 ID=1000
记录 3：id=1002, label='客服部',   dbc_bigint1=1000
记录 4：id=1005, label='前端组',   dbc_bigint1=1003    -- 上级 ID=1003
```

**差异**：
- BIGINT 模式：`dbc_bigint1=1000` → 需要用 `WHERE id=1000` 查上级
- VARCHAR 模式：`dbc_varchar5='root'` → 需要用 `WHERE api_key='root'` 查上级
- 跨环境迁移时，ID 会变但 api_key 不变

## 六、设计规则总结

### 6.1 何时用传统模式（BIGINT）

- 业务实体之间的关联（account → department、opportunity → account）
- 关联目标是业务数据表（p_tenant_data）中的记录
- 不需要跨环境迁移关联关系

### 6.2 何时用 api_key 模式（VARCHAR）

- 元数据之间的关联（department → department 自关联、role → role 自关联）
- 关联目标是元数据快捷表（p_tenant_role、p_tenant_department）中的记录
- 需要跨环境迁移一致性
- 符合平台"禁止 ID 关联，统一用 api_key"的规范

### 6.3 实现要点

| 步骤 | 传统模式 | api_key 模式 |
|:---|:---|:---|
| 1. p_meta_item 注册 | `data_type=3(BIGINT)` 或留空（自动推导） | `data_type=1(VARCHAR)` **必须显式指定** |
| 2. db_column 分配 | `dbc_bigint{N}` | `dbc_varchar{N}` |
| 3. Java 服务层读取 | `Long parentId = (Long) r.get("dbc_bigint1")` | `String parentApiKey = (String) r.get("dbc_varchar5")` |
| 4. Java 服务层查关联 | `WHERE id = ?` | `WHERE api_key = ?` |
| 5. 前端存储值 | `number` | `string` |
| 6. 前端查关联显示名 | 用 ID 查 | 用 apiKey 查 |
