# 数据关联与 UI 组件结合逻辑梳理

> 日期：2026-04-23
> 目标：梳理从数据库到 UI 组件的完整数据流，定位当前断点

---

## 一、完整数据流

```
┌─────────────────────────────────────────────────────────────────────┐
│ 1. 数据库（PostgreSQL）                                              │
│    p_common_metadata 表                                              │
│    ┌──────────────────┬──────────┬──────────────┬──────────────────┐ │
│    │ metamodel_api_key│ api_key  │entity_api_key│parent_metadata_  │ │
│    │                  │          │              │api_key           │ │
│    ├──────────────────┼──────────┼──────────────┼──────────────────┤ │
│    │ globalPickOption │ beijing  │ province     │ NULL             │ │
│    │ globalPickOption │ guangZhou│ city         │ guangdong        │ │
│    │ globalPickOption │ tianHe   │ district     │ guangZhou        │ │
│    └──────────────────┴──────────┴──────────────┴──────────────────┘ │
│    + dbc_int1(optionOrder), dbc_smallint1(defaultFlg), ...           │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 2. Java Entity（MyBatis-Plus 映射）                                  │
│                                                                      │
│    GlobalPickOption extends BaseMetaTenantEntity                     │
│    ├── id, apiKey, label, labelKey, namespace,                      │
│    │   description, descriptionKey, customFlg    ← BaseMetaCommon   │
│    ├── tenantId                                  ← BaseMetaTenant   │
│    ├── entityApiKey                              ← GlobalPickOption │
│    ├── optionOrder, defaultFlg, enableFlg        ← GlobalPickOption │
│    └── ❌ parentMetadataApiKey                   ← 缺失！           │
│                                                                      │
│    GenericMetadata extends BaseMetaTenantEntity                      │
│    ├── metamodelApiKey, entityApiKey             ← GenericMetadata  │
│    ├── fields: Map<String, Object>               ← dbc 列映射       │
│    └── ❌ parentMetadataApiKey                   ← 缺失！           │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 3. 后端 API（Jackson SNAKE_CASE 序列化）                             │
│                                                                      │
│    GET /meta/metadata?metamodelApiKey=globalPickOption               │
│        &entityApiKey=city                                            │
│                                                                      │
│    → MetamodelBrowseApiService.listMergedAuto()                     │
│    → MetamodelApiKeyEnum 找到 GlobalPickOption.class                │
│    → listMergedWithClass() 查询 + 合并                               │
│    → Jackson 序列化为 JSON                                           │
│                                                                      │
│    返回 JSON:                                                        │
│    {                                                                 │
│      "api_key": "guangZhou",                                        │
│      "label": "广州市",                                              │
│      "entity_api_key": "city",                                      │
│      "option_order": 196,                                            │
│      "default_flg": 0,                                               │
│      "enable_flg": 1,                                                │
│      "namespace": "system",                                          │
│      ❌ 没有 parent_metadata_api_key                                 │
│    }                                                                 │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 4. 前端 Axios 拦截器（snake_case → camelCase）                       │
│                                                                      │
│    {                                                                 │
│      "apiKey": "guangZhou",                                         │
│      "label": "广州市",                                              │
│      "entityApiKey": "city",                                        │
│      "optionOrder": 196,                                             │
│      "defaultFlg": 0,                                                │
│      "enableFlg": 1,                                                 │
│      ❌ 没有 parentMetadataApiKey                                    │
│    }                                                                 │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ 5. 前端组件（CascadePanelAtom）                                      │
│                                                                      │
│    过滤逻辑:                                                         │
│    arr.filter(item => {                                              │
│      const v = item.fields?.parentMetadataApiKey                    │
│             ?? item.parentMetadataApiKey;                            │
│      return String(v) === parentValue;                               │
│    })                                                                │
│                                                                      │
│    item.parentMetadataApiKey = undefined  ← 因为 API 没返回          │
│    item.fields = undefined               ← GlobalPickOption 没有     │
│                                             fields Map               │
│    → 过滤结果: 0 条 ❌                                               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 二、断点定位

| 层级 | 状态 | 问题 |
|:-----|:-----|:-----|
| 数据库 | ✅ | parent_metadata_api_key 有正确值 |
| Java Entity | ❌ | GlobalPickOption 和 GenericMetadata 都没有 parentMetadataApiKey 字段 |
| API 返回 | ❌ | JSON 中不包含 parentMetadataApiKey |
| 前端过滤 | ❌ | 无法按 parentMetadataApiKey 过滤 |

**根因**：`BaseMetaCommonEntity` 基类没有 `parentMetadataApiKey` 字段，导致所有元数据实体都无法返回这个值。

---

## 三、修复方案

### 方案 A：在 BaseMetaCommonEntity 中添加字段（推荐）

`parent_metadata_api_key` 是 `p_common_metadata` 表的固定列，所有元数据都可能用到（省市区层级、角色树、部门树等），应该在基类中声明。

```java
// BaseMetaCommonEntity.java
@Data
@EqualsAndHashCode(callSuper = true)
public class BaseMetaCommonEntity extends BaseEntity {
    private String apiKey;
    private String label;
    private String labelKey;
    private String namespace;
    private String description;
    private String descriptionKey;
    private Integer customFlg;
    private String parentMetadataApiKey;   // ← 新增
    private String metadataApiKey;         // ← 新增（部分元数据用到）
    private String entityApiKey;           // ← 新增（从子类上提）
}
```

影响范围：所有继承 BaseMetaCommonEntity 的实体类自动获得这个字段，API 返回自动包含。

### 方案 B：仅在 GenericMetadata 中添加

如果不想改基类，可以只在 GenericMetadata 中添加：

```java
public class GenericMetadata extends BaseMetaTenantEntity {
    private String metamodelApiKey;
    private String entityApiKey;
    private String parentMetadataApiKey;   // ← 新增
    private Map<String, Object> fields = new LinkedHashMap<>();
}
```

但这样 GlobalPickOption 等专用实体类仍然不返回 parentMetadataApiKey。

### 方案 C：在 GlobalPickOption 中添加

最小改动，只影响全局选项集：

```java
public class GlobalPickOption extends BaseMetaTenantEntity {
    private String entityApiKey;
    private String parentMetadataApiKey;   // ← 新增
    private Integer optionOrder;
    private Integer defaultFlg;
    private Integer enableFlg;
}
```

---

## 四、推荐方案 A

`parentMetadataApiKey` 是 `p_common_metadata` 的固定列，和 `apiKey`/`label`/`entityApiKey` 一样是通用字段。放在基类中最合理：

1. 省市区层级关系需要它
2. 角色/部门树形结构需要它（role.parentMetadataApiKey 指向上级角色）
3. 任何有层级关系的元数据都需要它
4. 不影响现有功能（新增字段，MyBatis-Plus 自动映射）

同时建议把 `entityApiKey` 也上提到基类（当前在 GenericMetadata 和 GlobalPickOption 中重复声明）。

---

## 五、修复后的数据流

```
数据库: parent_metadata_api_key = 'guangdong' ✅
    ↓
Java Entity: BaseMetaCommonEntity.parentMetadataApiKey ✅ 新增
    ↓
API 返回: { "parent_metadata_api_key": "guangdong", ... } ✅
    ↓
Axios 转换: { "parentMetadataApiKey": "guangdong", ... } ✅
    ↓
CascadePanelAtom: item.parentMetadataApiKey === 'guangdong' ✅
    ↓
过滤: 广东下的城市 21 条 ✅
```
