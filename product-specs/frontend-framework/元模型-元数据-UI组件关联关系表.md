# 元模型 · 元数据 · UI 组件 关联关系表

> 日期：2026-04-23

---

## 一、数据层：三种关联方式对比

| 关联方式 | 存储位置 | 关联字段 | Converter 是否映射 | API 是否返回 | 前端能否读取 |
|:---------|:---------|:---------|:-------------------|:-------------|:-------------|
| **固定列关联** | entity_api_key（大宽表固定列） | 直接字段 | ✅ 不在 SKIP_FIELDS | ✅ 返回 | ✅ item.entityApiKey |
| **dbc 列关联** | dbc_varchar5 → deptParentApiKey（p_meta_item 注册） | 通过列映射 | ✅ Step2 映射 | ✅ 返回 | ✅ item.deptParentApiKey |
| **parent 固定列** | parent_metadata_api_key（大宽表固定列） | 直接字段 | ❌ 在 SKIP_FIELDS | ❌ 不返回 | ❌ 取不到 |

---

## 二、现有可工作的主子/层级联动

| 场景 | 左侧数据 | 右侧数据 | 关联字段 | 关联方式 | 状态 |
|:-----|:---------|:---------|:---------|:---------|:-----|
| 实体→字段 | entity | item | entityApiKey | 固定列 | ✅ |
| 实体→校验规则 | entity | checkRule | entityApiKey | 固定列 | ✅ |
| 实体→业务类型 | entity | busiType | entityApiKey | 固定列 | ✅ |
| 实体→关联关系 | entity | entityLink | entityApiKey | 固定列 | ✅ |
| 字段→选项值 | item | pickOption | itemApiKey | dbc 列 | ✅ |
| 字段→计算公式 | item | formulaCompute | itemApiKey | dbc 列 | ✅ |
| 选项集→依赖 | globalPickOption | globalPickDependency | entityApiKey | 固定列 | ✅ |
| 元模型→字段定义 | metaModel | metaItem | metamodelApiKey | 固定列 | ✅ |
| 元模型→关联关系 | metaModel | metaLink | parentMetamodelApiKey | 固定列 | ✅ |
| 部门→子部门（树） | department | department | **deptParentApiKey** (dbc_varchar5) | dbc 列 | ✅ |
| 角色→子角色（树） | role | role | **roleParentApiKey** (dbc_varchar5) | dbc 列 | ✅ |
| 部门→用户 | department | user | departApiKey | filterField | ✅ |
| 角色→用户 | role | user | roleApiKey | custom API | ✅ |

---

## 三、省市区场景的问题

| 场景 | 左侧数据 | 右侧数据 | 关联方式 | 实际情况 | 状态 |
|:-----|:---------|:---------|:---------|:---------|:-----|
| 省→市 | globalPickOption(province) | globalPickOption(city) | chainQuery(provinceToCity) 通过 globalPickDependencyDetail 中间表 | 需要 `/meta/chain-query` 接口 | ⚠️ 需 chainQuery |
| 市→区 | globalPickOption(city) | globalPickOption(district) | chainQuery(cityToDistrict) 通过 globalPickDependencyDetail 中间表 | 同上 | ⚠️ 需 chainQuery |

> ⚠️ 省→市→区级联**不是**通过 `parentMetadataApiKey` 直接关联，而是通过 `globalPickDependency` + `globalPickDependencyDetail` 依赖体系实现。

### 补充说明

> 虽然 `parent_metadata_api_key` 固定列中确实存储了省市区的层级关系数据，但省→市→区级联的正确实现路径
> 是通过 `globalPickDependency` + `globalPickDependencyDetail` 依赖体系 + `chainQuery` 链式查询，
> 不依赖 `parentMetadataApiKey` 字段的 API 返回。

`parentMetadataApiKey` 固定列的技术断点仍然存在（SKIP_FIELDS 跳过、Entity 无此字段），
但它不是省市区级联的阻塞项：

1. `CommonMetadataConverter.SKIP_FIELDS` 包含 `parentMetadataApiKey`，转换时跳过
2. `GlobalPickOption.java` 没有 `parentMetadataApiKey` 字段
3. `BaseMetaCommonEntity.java` 没有 `parentMetadataApiKey` 字段

### 对比：部门树为什么能工作

部门的"上级部门"不是存在 `parent_metadata_api_key` 固定列，而是存在 **dbc_varchar5** 扩展列，通过 p_meta_item 注册为 `deptParentApiKey`：

```
p_meta_item: metamodelApiKey=department, apiKey=deptParentApiKey, db_column=dbc_varchar5
```

Converter Step2 会把 `dbc_varchar5` 的值映射到 `Department.deptParentApiKey` 字段，API 正常返回。

---

## 四、globalPickOption 当前字段清单

### 4.1 Java Entity 字段（API 返回的）

| 字段 | 来源 | 说明 |
|:-----|:-----|:-----|
| id | BaseEntity | 主键 |
| apiKey | BaseMetaCommonEntity | 标识 |
| label | BaseMetaCommonEntity | 显示名 |
| labelKey | BaseMetaCommonEntity | 多语言 Key |
| namespace | BaseMetaCommonEntity | 命名空间 |
| description | BaseMetaCommonEntity | 描述 |
| customFlg | BaseMetaCommonEntity | 自定义标记 |
| tenantId | BaseMetaTenantEntity | 租户 ID |
| entityApiKey | GlobalPickOption | 所属选项集（province/city/district） |
| optionOrder | GlobalPickOption (dbc_int1) | 排序 |
| defaultFlg | GlobalPickOption (dbc_smallint1) | 是否默认 |
| enableFlg | GlobalPickOption (dbc_smallint2) | 是否启用 |

### 4.2 数据库有但 API 不返回的

| 字段 | 大宽表列 | 原因 |
|:-----|:---------|:-----|
| parentMetadataApiKey | parent_metadata_api_key | SKIP_FIELDS + Entity 无此字段 |
| metamodelApiKey | metamodel_api_key | SKIP_FIELDS |
| metadataApiKey | metadata_api_key | SKIP_FIELDS |
| metadataOrder | metadata_order | SKIP_FIELDS |
| metaVersion | meta_version | SKIP_FIELDS |

### 4.3 p_meta_item 注册的扩展字段

| apiKey | db_column | 说明 | API 返回 |
|:-------|:----------|:-----|:---------|
| optionOrder | dbc_int1 | 排序序号 | ✅ |
| defaultFlg | dbc_smallint1 | 是否默认 | ✅ |
| enableFlg | dbc_smallint2 | 是否启用 | ✅ |
| ❌ 无 parentApiKey | — | 上级选项 | — |

---

## 五、两条修复路径对比

### 路径 A：打通 parent_metadata_api_key 固定列

| 改动 | 文件 | 影响范围 |
|:-----|:-----|:---------|
| SKIP_FIELDS 移除 parentMetadataApiKey | CommonMetadataConverter.java | 所有元模型的 Converter 行为 |
| BaseMetaCommonEntity 加 parentMetadataApiKey 字段 | BaseMetaCommonEntity.java | 所有继承此基类的 Entity |

优点：一次改动，所有元模型自动获得层级能力
风险：需要确认现有功能不受影响（新增字段，原来 null 的仍然 null）

### 路径 B：用 dbc 列存储层级关系（和部门树一样）

| 改动 | 位置 | 说明 |
|:-----|:-----|:-----|
| p_meta_item 注册 parentApiKey | init_local_dev.py | `apiKey=parentApiKey, db_column=dbc_varchar1, metamodelApiKey=globalPickOption` |
| GlobalPickOption.java 加 parentApiKey 字段 | GlobalPickOption.java | `private String parentApiKey;` |
| init_local_dev.py 改存储位置 | _ensure_gpo 函数 | 层级关系写入 dbc_varchar1 而不是 parent_metadata_api_key |
| 前端 CascadePanelAtom 改 parentField | CascadePanelAtom.tsx | `parentField: 'parentApiKey'` |

优点：不改基类，不改 Converter，和部门树模式一致
缺点：需要改数据存储位置，多一个 p_meta_item 注册

---

## 六、UI 组件与数据源的绑定关系

### 6.1 画布组件 → 数据源类型

| 组件 | 角色 | 数据源类型 | 写入 stateKey | 读取 depends |
|:-----|:-----|:-----------|:-------------|:-------------|
| listPanel | 左侧选择器 | metadata / metaModel | ✅ 选中写入 | — |
| tree | 左侧选择器 | metadata | ✅ 选中写入 | — |
| cascadePanel | 左侧多级选择器 | metadata（内部多次调用） | ✅ 每级写入 | — |
| detailHeader | 右侧详情 | metadata | — | ✅ 监听左侧 |
| dataTable | 右侧列表 | metadata / entityData / custom | — | ✅ 监听左侧 |
| dynamicTabs | 右侧 Tab 容器 | — | — | — |

### 6.2 数据源类型 → 后端 API

| 数据源类型 | 后端 API | 参数 | 返回格式 |
|:-----------|:---------|:-----|:---------|
| metaModel | GET /meta/metamodels | — | MetaModel[] |
| metaItem | GET /meta/meta-items | metamodelApiKey | MetaItem[] |
| metaLink | GET /meta/meta-links | — | MetaLink[] |
| metaOption | GET /meta/meta-options | metamodelApiKey | MetaOption[] |
| metadata | GET /meta/metadata | metamodelApiKey, entityApiKey? | Entity[]（类型由 MetamodelApiKeyEnum 决定） |
| entityData | GET /entity/data/{entityApiKey} | page, size, filterField | 分片表数据 |
| custom | GET {apiPath} | paramMapping | 自定义 |

### 6.3 metadata 类型的 Entity 解析路径

| metamodelApiKey | Entity 类 | 解析路径 | 有 fields Map |
|:----------------|:----------|:---------|:-------------|
| entity | Entity.class | MetamodelApiKeyEnum 注册 | ❌ |
| item | EntityItem.class | MetamodelApiKeyEnum 注册 | ❌ |
| role | Role.class | MetamodelApiKeyEnum 注册 | ❌ |
| department | Department.class | MetamodelApiKeyEnum 注册 | ❌ |
| globalPickOption | GlobalPickOption.class | MetamodelApiKeyEnum 注册 | ❌ |
| menu | GenericMetadata.class | 未注册，走 Generic | ✅ |
| uiComponent | GenericMetadata.class | 未注册，走 Generic | ✅ |
| page | GenericMetadata.class | 未注册，走 Generic | ✅ |
| pageSection | GenericMetadata.class | 未注册，走 Generic | ✅ |

### 6.4 前端读取字段值的方式

| Entity 类型 | 固定列字段 | 扩展字段（dbc 列映射） | 前端读取方式 |
|:------------|:-----------|:----------------------|:-------------|
| 注册类（GlobalPickOption 等） | item.apiKey, item.label, item.entityApiKey | item.optionOrder, item.defaultFlg | `item.xxx` |
| GenericMetadata | item.apiKey, item.label, item.entityApiKey | item.fields.componentType, item.fields.iconGroup | `item.fields.xxx ?? item.xxx` |

---

## 七、结论

省市区级联通过 `globalPickDependency` + `globalPickDependencyDetail` 依赖体系 + `chainQuery` 链式查询实现，不依赖 `parentMetadataApiKey` 字段。

`parentMetadataApiKey` 固定列当前在 API 层断裂（SKIP_FIELDS 跳过），但省市区场景不需要它。是否打通取决于未来是否有场景需要通用的同模型层级关系能力：

- **路径 A**（改基类）：让 `parent_metadata_api_key` 成为所有元数据的通用能力，一劳永逸
- **路径 B**（用 dbc 列）：和部门树/角色树保持一致的模式，不动基类

省→市→区的正确实现路径是 chainQuery：后端 `POST /meta/chain-query` + 前端 `chainQueryRef` 模板引用。
