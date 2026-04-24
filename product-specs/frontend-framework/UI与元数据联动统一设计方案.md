# UI 与元数据联动统一设计方案

> 版本：1.0 | 日期：2026-04-24
> 目标：统一所有 UI 组件与元数据之间的联动机制，一套 DataSourceConfig 覆盖全部场景

---

## 一、设计全景

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          画布 JSON Schema                               │
│  splitPanel + listPanel(左) + detailHeader(右) + dynamicTabs(右)        │
│  每个组件声明 dataSource: DataSourceConfig                               │
├─────────────────────────────────────────────────────────────────────────┤
│                          联动协议层                                      │
│                                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────────┐  │
│  │ PageContext   │    │ useDataSource│    │ 关系推导引擎              │  │
│  │ .state        │───▶│ hook         │◀───│ (p_meta_link +           │  │
│  │ .setState()   │    │ LOADERS      │    │  chainQueryTemplate)     │  │
│  │ .on/.emit     │    │ applyFilters │    │                          │  │
│  └──────────────┘    └──────────────┘    └──────────────────────────┘  │
├─────────────────────────────────────────────────────────────────────────┤
│                          后端查询层                                      │
│                                                                         │
│  GET /meta/metadata          单模型直接查询                              │
│  POST /meta/chain-query      多模型链式查询                              │
│  GET /entity/data/{key}      业务数据查询                                │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 二、五种联动模式（完整定义）

所有 UI 组件间的数据联动归纳为五种模式，每种模式有明确的数据来源、配置方式和运行时行为。

### 模式 A：直接父子联动

p_meta_link 中有直接的 parent→child 关系，系统自动推导过滤条件。

| 要素 | 说明 |
|:-----|:-----|
| 数据来源 | p_meta_link（referItemApiKey 指定子数据的关联字段） |
| 过滤方式 | 子数据的 `referItemApiKey` 字段 = 父数据的 apiKey |
| 配置方式 | depends 自动推导，零配置 |
| 后端接口 | `GET /meta/metadata?metamodelApiKey=item&entityApiKey=account` |

适用场景：

| 左侧 | 右侧 | referItemApiKey |
|:------|:------|:----------------|
| entity | item | entityApiKey |
| entity | checkRule / busiType / duplicateRule / sharingRule | entityApiKey |
| item | pickOption | itemApiKey |
| item | formulaCompute / aggregationCompute | itemApiKey |
| globalPickOption | globalPickDependency | entityApiKey |
| globalPickDependency | globalPickDependencyDetail | dependencyApiKey |
| metaModel | metaItem | metamodelApiKey |
| metaModel | metaLink | parentMetamodelApiKey |
| page | pageSection / pageAction | entityApiKey |
| sharingRule | sharingRuleCondition | ruleApiKey |

DataSourceConfig 示例：

```json
// 左侧
{ "type": "metadata", "metamodelApiKey": "entity", "stateKey": "selectedEntity" }
// 右侧（系统自动推导 depends + 过滤）
{ "type": "metadata", "metamodelApiKey": "item", "depends": ["selectedEntity"] }
```

### 模式 B：同模型详情联动

左右两侧是同一个 metamodelApiKey，右侧按 apiKey 过滤出选中的那条记录。

| 要素 | 说明 |
|:-----|:-----|
| 数据来源 | 同一个 metamodelApiKey |
| 过滤方式 | 右侧数据的 apiKey = 左侧选中值 |
| 配置方式 | depends 自动推导 |
| 后端接口 | 同模式 A，前端内存过滤 |

适用场景：角色→角色详情、部门→部门详情、任意元模型的列表→详情。

```json
// 左侧
{ "type": "metadata", "metamodelApiKey": "role", "stateKey": "selectedRole" }
// 右侧 detailHeader
{ "type": "metadata", "metamodelApiKey": "role", "depends": ["selectedRole"] }
```

### 模式 C：跨模型关联联动（filterField）

左侧选中元数据，右侧通过指定的 filterField 过滤业务数据或其他元数据。

| 要素 | 说明 |
|:-----|:-----|
| 数据来源 | 无 p_meta_link 直接关系，需手动配置 filterField |
| 过滤方式 | 右侧数据的 `filterField` 字段 = 左侧选中值的 `filterFrom` 字段 |
| 配置方式 | 显式配置 filterField + filterFrom |
| 后端接口 | `GET /entity/data/user?departApiKey=xxx` 或 paramMapping |

适用场景：

| 左侧 | 右侧 | filterField | filterFrom |
|:------|:------|:------------|:-----------|
| department | user | departApiKey | apiKey |
| role | user | roleApiKey | apiKey |
| account | contact | accountApiKey | apiKey |

```json
{ "type": "entityData", "entityApiKey": "user",
  "depends": ["selectedDept"],
  "filterField": "departApiKey", "filterFrom": "apiKey" }
```

### 模式 D：同模型树形联动（dbc 列驱动）

同一个元模型内的层级关系，通过各元模型自行注册的 dbc 扩展列实现。

| 要素 | 说明 |
|:-----|:-----|
| 数据来源 | 各元模型的 dbc 扩展列（如 department.deptParentApiKey = dbc_varchar5） |
| 过滤方式 | 子数据的 dbc 层级字段 = 父数据的 apiKey |
| 配置方式 | filters + $动态值 |
| 后端接口 | `GET /meta/metadata`，前端内存过滤 |

适用场景：

| 元模型 | 层级字段 | db_column |
|:-------|:---------|:----------|
| department | deptParentApiKey | dbc_varchar5 |
| role | roleParentApiKey | dbc_varchar5 |

```json
{ "type": "metadata", "metamodelApiKey": "department",
  "filters": [{ "field": "deptParentApiKey", "op": "eq", "value": "$selectedDept" }] }
```

### 模式 E：跨中间表链式联动（chainQuery 驱动）

需要经过中间表提取字段值（可能是数组），再反查目标表。这是最复杂的联动模式。

| 要素 | 说明 |
|:-----|:-----|
| 数据来源 | globalPickDependency 依赖体系 或 p_meta_link 多级链路 |
| 过滤方式 | 中间表的字段值（TEXT[] 数组）作为 IN 条件反查目标表 |
| 配置方式 | chainQueryRef（模板引用）或 chainQuery（内联配置）|
| 后端接口 | `POST /meta/chain-query` |

适用场景：

| 链路 | 中间表 | 关键字段 |
|:-----|:-------|:---------|
| 省→市 | globalPickDependencyDetail | dependentOptionApiKeys (TEXT[]) |
| 市→区 | globalPickDependencyDetail | dependentOptionApiKeys (TEXT[]) |
| 实体→所有选项值 | item（collect apiKey） | apiKey |
| 实体→所有计算公式 | item → formulaCompute | apiKey |

```json
// 方式一：模板引用（推荐）
{ "chainQueryRef": "provinceToCity", "chainQueryInputKey": "selectedProvince" }

// 方式二：内联配置
{ "chainQuery": {
    "inputStateKey": "selectedProvince",
    "steps": [{ "metamodelApiKey": "globalPickDependencyDetail", ... }],
    "target": { "metamodelApiKey": "globalPickOption", ... }
  }
}

// 方式三：cascadePanel + $dep() 表达式
{ "filter": "entityApiKey = 'city' AND apiKey IN $dep('provinceToCity', $prev.apiKey)" }
```

---

## 三、统一 DataSourceConfig 定义

```typescript
interface DataSourceConfig {
  /** 数据源类型 */
  type: 'metaModel' | 'metaItem' | 'metaLink' | 'metaOption'
        | 'metadata' | 'entityData' | 'columnMapping' | 'custom';

  /** 元数据类型标识 */
  metamodelApiKey?: string;
  /** 业务对象标识 */
  entityApiKey?: string;

  // ── 联动（模式 A/B/C） ──
  /** 监听哪些 stateKey 的变化 */
  depends?: string[];
  /** 选中后写入 PageContext 的 key */
  stateKey?: string;
  /** 跨模型联动：目标数据的过滤字段名（模式 C） */
  filterField?: string;
  /** 跨模型联动：从选中值取哪个字段（模式 C） */
  filterFrom?: string;
  /** state key → API 参数名映射（模式 C 高级） */
  paramMapping?: Record<string, string>;

  // ── 过滤（模式 D + 通用） ──
  /** 可视化条件编辑器配置的过滤条件，支持 $动态值 */
  filters?: FilterCondition[];
  /** 过滤条件组合逻辑 */
  filterLogic?: 'and' | 'or';
  /** filter 表达式（高级，如 "entityApiKey = 'city' AND apiKey IN $dep(...)") */
  filter?: string;

  // ── 链式查询（模式 E） ──
  /** 引用预定义的链式查询模板 */
  chainQueryRef?: string;
  /** 链式查询输入值来源的 stateKey */
  chainQueryInputKey?: string;
  /** 内联链式查询配置（模板不够用时的兜底） */
  chainQuery?: {
    inputStateKey: string;
    steps?: ChainQueryStep[];
    target: ChainQueryTarget;
  };

  /** 懒加载 */
  lazy?: boolean;
}
```

---

## 四、useDataSource 统一执行流程

```
useDataSource(config, pageContext) {

  // 1. 收集依赖值
  depValues = config.depends?.map(key => pageContext.state[key])
  if (depValues 有 undefined) return []  // 上游未选中，不加载

  // 2. 判断查询路径（按优先级）
  if (config.chainQueryRef) {
    // ── 模式 E：模板引用 ──
    template = chainQueryTemplateCache[config.chainQueryRef]
    input = pageContext.state[config.chainQueryInputKey]
    if (!input) return []
    return POST /meta/chain-query { input, steps: template.steps, target: template.target }
  }

  if (config.chainQuery) {
    // ── 模式 E：内联配置 ──
    input = pageContext.state[config.chainQuery.inputStateKey]
    if (!input) return []
    return POST /meta/chain-query { input, steps, target }
  }

  if (config.filter) {
    // ── filter 表达式 ──
    parsedFilters = parseFilterExpression(config.filter, pageContext)
    data = LOADERS[config.type](config)
    return applyFilters(data, parsedFilters)
  }

  // 3. 标准 LOADER 加载
  data = LOADERS[config.type](config)

  // 4. 应用 filters（支持 $动态值）
  if (config.filters?.length) {
    data = applyFilters(data, config.filters, config.filterLogic, pageContext.state)
  }

  // 5. 应用 filterField（模式 C）
  if (config.filterField && config.depends) {
    selectedValue = pageContext.state[config.depends[0]]
    data = data.filter(item => item[config.filterField] === selectedValue)
  }

  return data
}
```

优先级：`chainQueryRef > chainQuery > filter表达式 > LOADER + filters + filterField`

---

## 五、关系推导引擎

画布属性面板中，用户选择数据源后，系统自动推导可用的联动方式。

### 5.1 推导输入

```
当前组件的 metamodelApiKey（如 globalPickOption）
同页面中其他组件的 stateKey 列表（如 [selectedEntity, selectedProvince]）
```

### 5.2 推导逻辑

```typescript
function inferLinkageOptions(
  currentMM: string,
  pageComponents: ComponentInfo[]
): LinkageOption[] {
  const options: LinkageOption[] = [];

  for (const comp of pageComponents) {
    const parentMM = comp.dataSource?.metamodelApiKey;
    if (!parentMM) continue;

    // 1. p_meta_link 直接关系（模式 A）
    const link = metaLinks.find(l =>
      l.parentMetamodelApiKey === parentMM && l.childMetamodelApiKey === currentMM);
    if (link) {
      options.push({
        mode: 'A',
        label: `${parentMM}→${currentMM}（${link.referItemApiKey} = 上级.apiKey）`,
        config: { depends: [comp.stateKey] }
      });
    }

    // 2. 同模型详情（模式 B）
    if (parentMM === currentMM) {
      options.push({
        mode: 'B',
        label: `同记录详情（apiKey = 上级.apiKey）`,
        config: { depends: [comp.stateKey] }
      });
    }

    // 3. chainQueryTemplate 匹配（模式 E）
    const templates = chainQueryTemplates.filter(t =>
      t.sourceMetamodelApiKey === parentMM && t.targetMetamodelApiKey === currentMM);
    for (const tpl of templates) {
      options.push({
        mode: 'E',
        label: `${tpl.label}（级联查询）`,
        config: { chainQueryRef: tpl.apiKey, chainQueryInputKey: comp.stateKey }
      });
    }

    // 4. p_meta_link 两级链路（模式 E，自动推导）
    for (const link1 of metaLinks.filter(l => l.parentMetamodelApiKey === parentMM)) {
      const link2 = metaLinks.find(l =>
        l.parentMetamodelApiKey === link1.childMetamodelApiKey && l.childMetamodelApiKey === currentMM);
      if (link2) {
        options.push({
          mode: 'E',
          label: `${parentMM}→${link1.childMetamodelApiKey}→${currentMM}（两级链式）`,
          config: {
            chainQuery: {
              inputStateKey: comp.stateKey,
              steps: [{ metamodelApiKey: link1.childMetamodelApiKey,
                        matchField: link1.referItemApiKey,
                        outputField: 'apiKey', outputFormat: 'collect' }],
              target: { metamodelApiKey: currentMM,
                        matchField: link2.referItemApiKey, matchMode: 'IN' }
            }
          }
        });
      }
    }
  }

  return options;
}
```

### 5.3 属性面板 UI

```
┌─────────────────────────────────────────────────┐
│ 数据源                                           │
│   数据分类: [元数据]                              │
│   选择对象: [全局选项集 (globalPickOption) ▼]     │
│                                                   │
│ 关联上级                                          │
│   上级组件: [列表面板 - globalPickOption ▼]       │
│                                                   │
│   关联方式:                                       │
│   ┌─────────────────────────────────────────────┐ │
│   │ ── 直接关联（模式 A） ──                     │ │
│   │ entityApiKey = 上级.apiKey                   │ │
│   │ ── 同记录详情（模式 B） ──                   │ │
│   │ apiKey = 上级.apiKey                         │ │
│   │ ── 级联查询模板（模式 E） ──                 │ │
│   │ 省份→城市 (provinceToCity)                   │ │
│   │ 城市→区县 (cityToDistrict)                   │ │
│   │ ── 两级链式（模式 E，自动推导） ──           │ │
│   │ entity→item→pickOption                       │ │
│   └─────────────────────────────────────────────┘ │
│                                                   │
│ 联动标识                                          │
│   [selectedCity          ] [自动]                 │
│                                                   │
│ 过滤条件                                          │
│   + 添加条件                                      │
│   entityApiKey = province                         │
│   enableFlg = 1                                   │
└─────────────────────────────────────────────────┘
```

用户选择"关联方式"后，系统自动生成对应的 DataSourceConfig 字段，用户不需要理解底层机制。

---

## 六、splitPanel 左右分栏与联动的结合

### 6.1 splitPanel 的角色

splitPanel 是纯布局容器，不参与数据联动逻辑。它只做一件事：把子组件分配到左右两侧。

```
splitPanel
├── 左侧（layoutZone="left"）: listPanel / tree / cascadePanel
│   → 用户选中 → setState(stateKey, value)
│
└── 右侧（其余组件）: detailHeader / dynamicTabs / dataTable
    → useDataSource 检测 depends/chainQueryInputKey 变化 → 重新加载
```

联动逻辑完全由 DataSourceConfig + PageContext 驱动，与 splitPanel 无关。

### 6.2 完整页面配置示例

#### 示例一：角色管理（模式 A + B + C）

```json
{
  "components": [
    { "type": "splitPanel", "props": { "leftWidth": 280 } },
    { "type": "listPanel", "props": {
      "layoutZone": "left",
      "dataSource": { "type": "metadata", "metamodelApiKey": "role",
                      "stateKey": "selectedRole" }
    }},
    { "type": "detailHeader", "props": {
      "dataSource": { "type": "metadata", "metamodelApiKey": "role",
                      "depends": ["selectedRole"] }
    }},
    { "type": "dynamicTabs", "props": {
      "tabs": [
        { "key": "users", "label": "角色成员",
          "slot": [{ "type": "dataTable", "props": {
            "dataSource": { "type": "entityData", "entityApiKey": "user",
              "depends": ["selectedRole"],
              "filterField": "roleApiKey", "filterFrom": "apiKey" }
          }}]},
        { "key": "children", "label": "子角色",
          "slot": [{ "type": "dataTable", "props": {
            "dataSource": { "type": "metadata", "metamodelApiKey": "role",
              "filters": [{ "field": "roleParentApiKey", "op": "eq",
                            "value": "$selectedRole" }] }
          }}]}
      ]
    }}
  ]
}
```

联动链路：
- listPanel(role) → detailHeader(role)：模式 B，同模型详情
- listPanel(role) → dataTable(user)：模式 C，filterField=roleApiKey
- listPanel(role) → dataTable(role children)：模式 D，$动态值过滤 roleParentApiKey

#### 示例二：全局选项集管理 + 省→市级联（模式 A + E）

```json
{
  "components": [
    { "type": "splitPanel", "props": { "leftWidth": 280 } },
    { "type": "listPanel", "props": {
      "layoutZone": "left",
      "dataSource": { "type": "metadata", "metamodelApiKey": "globalPickOption",
        "filters": [{ "field": "entityApiKey", "op": "eq", "value": "province" }],
        "stateKey": "selectedProvince" }
    }},
    { "type": "dynamicTabs", "props": {
      "tabs": [
        { "key": "cities", "label": "城市",
          "slot": [{ "type": "dataTable", "props": {
            "dataSource": { "chainQueryRef": "provinceToCity",
                            "chainQueryInputKey": "selectedProvince" }
          }}]},
        { "key": "deps", "label": "依赖定义",
          "slot": [{ "type": "dataTable", "props": {
            "dataSource": { "type": "metadata",
              "metamodelApiKey": "globalPickDependency",
              "depends": ["selectedProvince"] }
          }}]}
      ]
    }}
  ]
}
```

联动链路：
- listPanel(province) → dataTable(city)：模式 E，chainQueryRef=provinceToCity
- listPanel(province) → dataTable(dependency)：模式 A，depends 自动推导

#### 示例三：实体→字段→选项值 三级级联（cascadePanel + 模式 A）

```json
{
  "components": [
    { "type": "splitPanel", "props": { "leftWidth": 360 } },
    { "type": "cascadePanel", "props": {
      "layoutZone": "left",
      "levels": [
        { "label": "实体", "metamodelApiKey": "entity",
          "stateKey": "selectedEntity" },
        { "label": "字段", "metamodelApiKey": "item",
          "stateKey": "selectedItem" },
        { "label": "选项值", "metamodelApiKey": "pickOption" }
      ]
    }},
    { "type": "detailHeader", "props": {
      "dataSource": { "type": "metadata", "metamodelApiKey": "pickOption",
                      "depends": ["selectedItem"] }
    }}
  ]
}
```

cascadePanel 内部自动查 p_meta_link 推导每级的过滤条件，零配置。

---

## 七、运行时数据流总图

```
用户操作（点击左侧列表项）
    │
    ▼
PageContext.setState("selectedProvince", "guangdong")
    │
    ├──▶ detailHeader (depends: ["selectedProvince"])
    │      useDataSource 检测到 depends 值变化
    │      → LOADERS.metadata("globalPickOption")
    │      → applyFilters: apiKey === "guangdong"
    │      → 渲染省份详情
    │
    ├──▶ dataTable[cities] (chainQueryRef: "provinceToCity")
    │      useDataSource 检测到 chainQueryInputKey 值变化
    │      → 从 chainQueryTemplate 缓存获取模板
    │      → POST /meta/chain-query { input: "guangdong", steps: [...], target: {...} }
    │      → 后端执行链式查询
    │      → 返回 21 个城市
    │      → 渲染城市表格
    │
    └──▶ dataTable[deps] (depends: ["selectedProvince"])
           useDataSource 检测到 depends 值变化
           → LOADERS.metadata("globalPickDependency")
           → 后端按 entityApiKey="province" 过滤
           → 返回 provinceToCity 依赖定义
           → 渲染依赖表格
```

---

## 八、实现状态与待办

| 能力 | 状态 | 说明 |
|:-----|:-----|:-----|
| 模式 A：直接父子联动 | ✅ 已实现 | depends 自动推导 + metadata loader |
| 模式 B：同模型详情联动 | ✅ 已实现 | metadata loader 按 apiKey 过滤 |
| 模式 C：跨模型 filterField | ✅ 已实现 | filterField + filterFrom |
| 模式 D：$动态值过滤 | ✅ 已实现 | applyFilters 支持 $stateKey |
| 模式 E：chainQuery 内联 | 📋 待实现 | 后端 `/meta/chain-query` 接口 |
| 模式 E：chainQueryRef 模板 | 📋 待实现 | chainQueryTemplate 元模型 + useDataSource 集成 |
| 模式 E：cascadePanel + $dep() | 📋 待实现 | filterExpression.ts 表达式引擎 |
| 关系推导引擎 | 📋 待实现 | p_meta_link 图遍历 + chainQueryTemplate 匹配 |
| stateKey 可编辑 | ✅ 已实现 | LinkageKeyEditor 组件 |
| 联动标识辅助 | ✅ 已实现 | collectLinkageKeys 扫描同页面组件 |
| splitPanel 布局容器 | ✅ 已实现 | layoutZone 分配左右 |
| cascadePanel 多级级联 | ✅ 已实现 | CascadePanelAtom 组件 |
| cascadePanel p_meta_link 自动推导 | 📋 待实现 | 当前需手写 filter |

---

## 九、实施路径

### Phase 1：chainQuery 后端接口（3 天）

| 任务 | 文件 |
|:-----|:-----|
| ChainQueryRequest/Step/Target 数据模型 | Java DTO |
| `/meta/chain-query` Controller 方法 | MetamodelBrowseApiService.java |
| single/collect 两个内置处理器 | StepOutputProcessor 接口 + 实现 |
| 单元测试（省→市、实体→字段→选项值） | test |

### Phase 2：前端 chainQuery 集成（2 天）

| 任务 | 文件 |
|:-----|:-----|
| DataSourceConfig 类型扩展 chainQuery/chainQueryRef | types.ts |
| useDataSource 支持 chainQuery 和 chainQueryRef | useDataSource.ts |
| chainQueryTemplate 元模型注册 + 预置 4 个模板 | init_local_dev.py |
| useCanvasMetadata 启动时加载 chainQueryTemplate | useCanvasMetadata.tsx |

### Phase 3：属性面板关系推导（3 天）

| 任务 | 文件 |
|:-----|:-----|
| inferLinkageOptions 推导函数 | linkageInference.ts |
| ParentRefEditor 关联方式下拉（直接/模板/两级链式） | PropertyPanel.tsx |
| 选择关联方式后自动生成 DataSourceConfig | PropertyPanel.tsx |

### Phase 4：cascadePanel 增强（2 天）

| 任务 | 文件 |
|:-----|:-----|
| cascadePanel 支持 p_meta_link 自动推导 | CascadePanelAtom.tsx |
| filter 表达式引擎（$prev / $levelN / $dep()） | filterExpression.ts |
| cascadePanel 支持 filter 表达式 | CascadePanelAtom.tsx |

总计约 10 天。
