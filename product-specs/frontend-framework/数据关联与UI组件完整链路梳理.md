# 数据关联与 UI 组件完整链路梳理

> 日期：2026-04-23
> 目标：不改代码，先把从数据库到 UI 组件的每一步都搞清楚，定位所有断点

---

## 一、数据存储层

### 1.1 p_common_metadata 大宽表结构

所有 Common 级元数据统一存储在一张大宽表中：

```
p_common_metadata
├── 固定列（所有元模型共享）
│   ├── id                        BIGINT
│   ├── metamodel_api_key         VARCHAR    ← 标识属于哪个元模型（如 globalPickOption）
│   ├── api_key                   VARCHAR    ← 记录唯一标识
│   ├── label                     VARCHAR    ← 显示名
│   ├── label_key                 VARCHAR    ← 多语言 Key
│   ├── entity_api_key            VARCHAR    ← 所属对象（如 province/city/district）
│   ├── parent_metadata_api_key   VARCHAR    ← 父级记录（如城市的父级是省份）
│   ├── namespace                 VARCHAR    ← system/product/custom
│   ├── custom_flg                SMALLINT
│   ├── metadata_order            INTEGER
│   ├── description               VARCHAR
│   ├── delete_flg                SMALLINT
│   ├── created_at/by, updated_at/by
│   └── tenant_id                 BIGINT     ← Tenant 表才有
│
├── 扩展列（dbc_xxx_N，由 p_meta_item 定义语义）
│   ├── dbc_varchar1~30           VARCHAR(300)
│   ├── dbc_textarea1~10          TEXT
│   ├── dbc_bigint1~20            BIGINT
│   ├── dbc_int1~15               INTEGER
│   ├── dbc_smallint1~50          SMALLINT
│   └── dbc_decimal1~5            DECIMAL(20,4)
```

### 1.2 省市区数据在大宽表中的存储

以广州市为例：

| 列名 | 值 | 说明 |
|:-----|:---|:-----|
| metamodel_api_key | `globalPickOption` | 属于全局选项集元模型 |
| api_key | `guangZhou` | 记录标识 |
| label | `广州市` | 显示名 |
| entity_api_key | `city` | 属于"城市"分类 |
| parent_metadata_api_key | `guangdong` | 父级是广东省 |
| dbc_int1 | `196` | optionOrder（排序序号） |
| dbc_smallint1 | `0` | defaultFlg（是否默认） |
| dbc_smallint2 | `1` | enableFlg（是否启用） |

### 1.3 p_meta_item 定义 dbc 列的语义

globalPickOption 的 p_meta_item 定义了 3 个扩展字段：

| api_key (字段名) | db_column (物理列) | 说明 |
|:-----------------|:-------------------|:-----|
| optionOrder | dbc_int1 | 排序序号 |
| defaultFlg | dbc_smallint1 | 是否默认 |
| enableFlg | dbc_smallint2 | 是否启用 |

---

## 二、后端查询层

### 2.1 API 入口

```
GET /meta/metadata?metamodelApiKey=globalPickOption&entityApiKey=city
```

→ `MetamodelBrowseApiService.listMergedAuto("globalPickOption")`

### 2.2 Entity 类解析

`MetamodelApiKeyEnum` 查找 `globalPickOption` → 找到 `GlobalPickOption.class`

```java
GLOBAL_PICK_OPTION("globalPickOption", GlobalPickOption.class)
```

### 2.3 查询 + 转换流程

```
listMergedAuto("globalPickOption")
  → MetamodelApiKeyEnum 找到 GlobalPickOption.class
  → listMergedWithClass("globalPickOption", GlobalPickOption.class)
    → getColumnMapping("globalPickOption")
      → 查 p_meta_item: {dbc_int1→optionOrder, dbc_smallint1→defaultFlg, dbc_smallint2→enableFlg}
    → listCommon("globalPickOption", GlobalPickOption.class)
      → SQL: SELECT id, api_key, label, ..., entity_api_key, parent_metadata_api_key, dbc_int1, dbc_smallint1, dbc_smallint2
              FROM p_common_metadata WHERE metamodel_api_key = 'globalPickOption'
      → 返回 List<CommonMetadata>（大宽表行）
    → CommonMetadataConverter.convert(rows, GlobalPickOption.class, columnMapping)
```

### 2.4 CommonMetadataConverter 转换逻辑（关键！）

```
Step 1: 固定列同名映射（CommonMetadata → GlobalPickOption）
  遍历 CommonMetadata 的所有非 dbc 字段：
    id → GlobalPickOption.id                    ✅ 映射（BaseEntity 有）
    apiKey → GlobalPickOption.apiKey             ✅ 映射（BaseMetaCommonEntity 有）
    label → GlobalPickOption.label               ✅ 映射
    namespace → GlobalPickOption.namespace        ✅ 映射
    entityApiKey → GlobalPickOption.entityApiKey  ✅ 映射（GlobalPickOption 自己声明了）
    
    metamodelApiKey → SKIP_FIELDS 跳过           ⚠️ 不映射
    metadataApiKey → SKIP_FIELDS 跳过            ⚠️ 不映射
    parentMetadataApiKey → SKIP_FIELDS 跳过      ❌ 不映射！这是问题根源
    metadataOrder → SKIP_FIELDS 跳过             ⚠️ 不映射
    metaVersion → SKIP_FIELDS 跳过               ⚠️ 不映射

Step 2: dbc 列 → 业务字段（通过 columnMapping）
  dbc_int1 → optionOrder                         ✅ GlobalPickOption 有此字段
  dbc_smallint1 → defaultFlg                     ✅ GlobalPickOption 有此字段
  dbc_smallint2 → enableFlg                      ✅ GlobalPickOption 有此字段
```

**断点 1**：`parentMetadataApiKey` 在 `SKIP_FIELDS` 中，Converter 不会把它映射到目标 Entity。

**断点 2**：即使不在 SKIP_FIELDS 中，`GlobalPickOption` 类也没有 `parentMetadataApiKey` 字段，反射找不到目标字段也不会映射。

### 2.5 最终 GlobalPickOption 对象

```java
GlobalPickOption {
  id: 1234567890123456,
  apiKey: "guangZhou",
  label: "广州市",
  namespace: "system",
  entityApiKey: "city",
  optionOrder: 196,
  defaultFlg: 0,
  enableFlg: 1,
  // ❌ 没有 parentMetadataApiKey
}
```

### 2.6 Jackson 序列化

Jackson 全局配置 SNAKE_CASE，输出：

```json
{
  "id": 1234567890123456,
  "api_key": "guangZhou",
  "label": "广州市",
  "namespace": "system",
  "entity_api_key": "city",
  "option_order": 196,
  "default_flg": 0,
  "enable_flg": 1
}
```

**没有 `parent_metadata_api_key` 字段。**

---

## 三、前端接收层

### 3.1 Axios 拦截器

snake_case → camelCase 自动转换：

```json
{
  "id": 1234567890123456,
  "apiKey": "guangZhou",
  "label": "广州市",
  "namespace": "system",
  "entityApiKey": "city",
  "optionOrder": 196,
  "defaultFlg": 0,
  "enableFlg": 1
}
```

### 3.2 前端 listMetadata 返回

```typescript
// listMetadata('globalPickOption', 'city') 返回：
[
  { apiKey: "beijingCity", label: "北京市", entityApiKey: "city", optionOrder: 1, ... },
  { apiKey: "guangZhou", label: "广州市", entityApiKey: "city", optionOrder: 196, ... },
  // ❌ 没有 parentMetadataApiKey 字段
]
```

### 3.3 对比：GenericMetadata 的情况

如果元模型没有在 `MetamodelApiKeyEnum` 中注册（如 `uiComponent`、`menu` 等），走 `GenericMetadata` 路径：

```
listMergedAuto("uiComponent")
  → MetamodelApiKeyEnum 找不到
  → listMergedGeneric("uiComponent")
  → CommonMetadataConverter.convert(rows, GenericMetadata.class, columnMapping)
```

GenericMetadata 的 Step 1 同样跳过 `parentMetadataApiKey`（SKIP_FIELDS）。
GenericMetadata 的 Step 2 把 dbc 列值放入 `fields` Map。

```json
{
  "api_key": "dataTable",
  "label": "数据表格",
  "entity_api_key": null,
  "metamodel_api_key": "uiComponent",
  "fields": {
    "component_type": "dataTable",
    "component_category": "data",
    "component_icon": "Table",
    "component_order": 19
  }
}
```

**GenericMetadata 也没有 parentMetadataApiKey。**

---

## 四、前端 UI 组件层

### 4.1 useDataSource metadata loader

```typescript
metadata: (p) => {
  const metamodelApiKey = String(p.metamodelApiKey ?? ...);
  const entityApiKey = ...;
  return listMetadata(metamodelApiKey, entityApiKey).then(r => {
    let arr = Array.isArray(r) ? r : [];
    // 应用过滤条件
    arr = applyFilters(arr, otherFilters, filterLogic, pageState);
    return arr;
  });
}
```

### 4.2 applyFilters 过滤逻辑

```typescript
function applyFilters(data, filters, logic, pageState) {
  return data.filter(item => {
    const results = filters.map(f => {
      // 先查 item.fields.xxx，再查 item.xxx
      const fields = (item.fields ?? {}) as Record<string, unknown>;
      const raw = fields[f.field] ?? item[f.field];
      // ...
    });
  });
}
```

### 4.3 CascadePanelAtom 过滤逻辑

```typescript
// level.parentField = 'parentMetadataApiKey'
arr = arr.filter(item => {
  const fields = (item.fields ?? {}) as Record<string, unknown>;
  const v = fields[level.parentField!] ?? item[level.parentField!];
  return String(v ?? '') === parentValue;
});
```

**问题**：
- `item.fields` → GlobalPickOption 没有 fields Map，为 undefined
- `item.parentMetadataApiKey` → API 没返回这个字段，为 undefined
- 过滤结果：所有记录都不匹配，返回空列表

---

## 五、断点汇总

| # | 位置 | 问题 | 影响 |
|:--|:-----|:-----|:-----|
| 1 | CommonMetadataConverter.SKIP_FIELDS | `parentMetadataApiKey` 被显式跳过 | 即使 Entity 有此字段也不会映射 |
| 2 | GlobalPickOption.java | 没有 `parentMetadataApiKey` 字段 | 即使 Converter 不跳过，反射也找不到目标 |
| 3 | GenericMetadata.java | 没有 `parentMetadataApiKey` 字段 | 同上 |
| 4 | BaseMetaCommonEntity.java | 没有 `parentMetadataApiKey` 字段 | 所有元数据实体都缺失 |
| 5 | GlobalPickOption 没有 fields Map | 不像 GenericMetadata 有 fields | 前端 `item.fields.xxx` 取不到值 |

---

## 六、受影响的场景

以下场景依赖 `parent_metadata_api_key` 固定列：

| 场景 | 需要的字段 | 当前状态 | 说明 |
|:-----|:-----------|:---------|:-----|
| 角色树（上级角色） | parentMetadataApiKey | ❌ API 不返回（但角色树实际用 roleParentApiKey dbc_varchar5） | 角色树已通过 dbc 列绕过 |
| 部门树（上级部门） | deptParentApiKey (dbc_varchar5) | ✅ 通过 p_meta_item 映射到 Department.deptParentApiKey | 不依赖 parentMetadataApiKey |
| 选项集→子选项 | entityApiKey | ✅ GlobalPickOption 有此字段 | 不依赖 parentMetadataApiKey |
| 实体→字段 | entityApiKey | ✅ EntityItem 有此字段 | 不依赖 parentMetadataApiKey |

> ⚠️ **重要纠正**：省→市→区级联**不依赖** `parentMetadataApiKey`。
> 省市区之间的关联通过 `globalPickDependency` + `globalPickDependencyDetail` 依赖体系实现：
>
> ```
> 省份(guangdong)
>   → 查 globalPickDependencyDetail WHERE dependencyApiKey='provinceToCity' AND controlOptionApiKey='guangdong'
>   → 取 dependentOptionApiKeys = ["guangZhou","shenZhen",...] (TEXT[] 数组)
>   → 查 globalPickOption WHERE entityApiKey='city' AND apiKey IN (...)
> ```
>
> 正确的 UI 联动方式是使用 `chainQuery` 链式查询（`POST /meta/chain-query`），不是前端内存过滤 parentMetadataApiKey。

**注意**：部门树能工作是因为它用的是 `deptParentApiKey`（dbc_varchar5 映射），角色树用的是 `roleParentApiKey`（dbc_varchar5 映射）。这两个都不依赖 `parentMetadataApiKey` 固定列。

`parentMetadataApiKey` 这个固定列目前在整个系统中**从未被任何 API 返回过**，也**没有任何已实现的业务场景依赖它**。

---

## 七、两条修复路径

### 路径 A：让 parentMetadataApiKey 能被 API 返回

需要改两处：
1. `CommonMetadataConverter.SKIP_FIELDS` 中移除 `parentMetadataApiKey`
2. `BaseMetaCommonEntity` 中添加 `parentMetadataApiKey` 字段（或在各子类中添加）

优点：所有元数据自动获得层级关系能力
缺点：改基类影响面大，需要确认不会破坏现有功能

### 路径 B：不用 parentMetadataApiKey，改用 dbc 列

在 `p_meta_item` 中为 globalPickOption 注册一个新字段：

```
apiKey: parentApiKey
db_column: dbc_varchar1（或其他空闲列）
label: 上级选项
```

然后把省市区的层级关系存到 dbc_varchar1 而不是 parent_metadata_api_key。

优点：不改基类，不改 Converter
缺点：浪费一个 dbc 列，且 parent_metadata_api_key 固定列的设计初衷就是存层级关系

### 路径 C：混合方案

对 globalPickOption 走 GenericMetadata 路径（从 MetamodelApiKeyEnum 中移除），让 parentMetadataApiKey 通过 GenericMetadata 的 fields Map 返回。

但这也不行——因为 SKIP_FIELDS 同样会跳过 parentMetadataApiKey，不会放入 fields Map。

---

## 八、结论

**`parentMetadataApiKey` 固定列的现状**：被 CommonMetadataConverter 的 SKIP_FIELDS 跳过，API 不返回。但经过分析，当前系统中没有已实现的业务场景真正依赖它：

- 省→市→区级联：通过 globalPickDependency 依赖体系 + chainQuery 链式查询实现，不需要 parentMetadataApiKey
- 部门树/角色树：通过各自的 dbc 扩展列（deptParentApiKey / roleParentApiKey）实现，不需要 parentMetadataApiKey

**是否需要打通 parentMetadataApiKey**：取决于未来是否有场景需要"通用的同模型层级关系"能力。如果有，推荐路径 A（从 SKIP_FIELDS 移除 + BaseMetaCommonEntity 添加字段）。如果没有，当前不需要改动。

**省→市→区级联的正确实现路径**：
1. 后端实现 `POST /meta/chain-query` 接口
2. 前端 `useDataSource` 支持 `chainQueryRef` / `chainQuery` 配置
3. 注册 `chainQueryTemplate` 元模型，预置 provinceToCity / cityToDistrict 模板
4. 画布属性面板的"关联方式"下拉支持级联查询模板选项
