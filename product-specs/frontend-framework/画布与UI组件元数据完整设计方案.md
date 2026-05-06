# 画布与 UI 组件元数据完整设计方案

> 版本：1.0 | 日期：2026-04-18
> 定位：前端画布编辑器架构 + 后台 UI 组件元数据体系的统一设计

---

## 一、设计目标

将"页面长什么样"从硬编码变为元数据配置：

```
当前：每个管理页面 = 一个手写 React 组件（UserManagementView.tsx）
目标：每个管理页面 = 一份 JSON Schema（存在 p_common_metadata 中）
      → 画布编辑器可视化编辑
      → PageRuntime 运行时渲染
      → 租户可自定义覆盖（Tenant 级）
```

核心价值：新增一个管理页面从"写代码 + 发版"变为"画布拖拽 + 保存"。

---

## 二、整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        元模型层（p_meta_model）                  │
│  uiComponent    UI 组件定义（原子组件注册表）                     │
│  uiComposite    复合组件定义（原子组件的预组合模板）               │
│  page           页面定义                                        │
│  pageSection    页面区域定义（画布 JSON Schema 存储）             │
│  menu           菜单定义                                        │
├─────────────────────────────────────────────────────────────────┤
│                        元数据层（p_common_metadata）              │
│  uiComponent 实例：52 个原子组件注册（type/category/propSchema） │
│  uiComposite 实例：5+ 个复合模板注册                             │
│  page 实例：语言管理、时区管理、用户管理...                       │
│  pageSection 实例：每个 page 的画布 JSON Schema                  │
│  menu 实例：12+ 条菜单项                                        │
├─────────────────────────────────────────────────────────────────┤
│                        前端运行时                                │
│  CanvasEditor  画布编辑器（管理员使用）                           │
│  PageRuntime   页面运行时渲染器（所有用户使用）                   │
│  registry.ts   组件注册表（前端内存，与 uiComponent 元数据同步）  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、UI 组件元模型设计（uiComponent）

### 3.1 元模型注册

在 p_meta_model 中注册 `uiComponent` 元模型：

```sql
INSERT INTO p_meta_model (api_key, label, namespace, enable_common, enable_tenant, db_table, description)
VALUES ('uiComponent', 'UI组件', 'system', 1, 1, 'p_tenant_metadata',
        '画布原子组件注册表，定义每种可用的 UI 组件');
```

- `enable_common=1`：系统出厂 52 个原子组件作为 Common 级数据
- `enable_tenant=1`：租户可自定义扩展组件（Tenant 覆盖 Common）

### 3.2 字段定义（p_meta_item）

| api_key | label | item_type | db_column | 说明 |
|:---|:---|:---:|:---|:---|
| componentType | 组件类型 | 1(TEXT) | dbc_varchar1 | 唯一标识，如 `title`、`dataTable`、`fieldSelect` |
| componentCategory | 组件分类 | 2(SELECT) | dbc_varchar2 | layout/data/action/form |
| componentIcon | 图标名 | 1(TEXT) | dbc_varchar3 | lucide-react 图标名 |
| defaultProps | 默认属性 | 4(TEXTAREA) | dbc_textarea1 | JSON 字符串 |
| propSchema | 属性定义 | 4(TEXTAREA) | dbc_textarea2 | JSON 字符串，PropField[] |
| componentOrder | 排序 | 5(NUMBER) | dbc_int1 | 组件面板中的排序 |
| enableFlg | 启用标记 | 31(BOOLEAN) | dbc_smallint1 | 0=禁用 1=启用 |
| visibleFlg | 可见标记 | 31(BOOLEAN) | dbc_smallint2 | 0=隐藏 1=可见（面板中） |
| itemTypeBinding | 绑定字段类型 | 5(NUMBER) | dbc_int2 | 对应 ItemTypeEnum code，0=无绑定 |

### 3.3 组件分类体系

```
uiComponent
├── layout（布局类）
│   ├── title          标题
│   ├── text           文本
│   ├── divider        分割线
│   ├── spacer         间距
│   ├── card           卡片容器
│   ├── row            行容器（多列网格）
│   ├── tabs           标签页
│   ├── collapse       折叠面板
│   ├── alert          提示框
│   ├── breadcrumb     面包屑
│   ├── image          图片
│   ├── steps          步骤条
│   ├── emptyState     空状态
│   ├── avatar         头像
│   └── iframe         内嵌页面
│
├── data（数据类）
│   ├── dataTable      数据表格
│   ├── tree           树形列表
│   ├── detailPanel    详情面板
│   ├── descriptionList 描述列表
│   ├── statCard       统计卡片
│   ├── statRow        统计行
│   ├── filterBar      筛选栏
│   ├── pagination     分页器
│   ├── progress       进度条
│   ├── badgeList      标签列表
│   ├── timeline       时间线
│   ├── transfer       穿梭框
│   └── qrCode         二维码
│
├── action（操作类）
│   ├── button         按钮
│   ├── buttonGroup    按钮组
│   ├── modalTrigger   弹框触发
│   └── drawerTrigger  抽屉触发
│
└── form（表单字段类，与 ItemTypeEnum 一一绑定）
    ├── fieldText          TEXT(1)
    ├── fieldSelect        SELECT(2)
    ├── fieldMultiSelect   MULTI_SELECT(3)
    ├── fieldTextarea      TEXTAREA(4)
    ├── fieldNumber        NUMBER(5)
    ├── fieldCurrency      CURRENCY(6)
    ├── fieldDate          DATE(7)
    ├── fieldAutoNumber    AUTONUMBER(9)
    ├── fieldRelation      RELATION_SHIP(10)
    ├── fieldMultiTag      MULTI_TAG(16)
    ├── fieldPhone         PHONE(22)
    ├── fieldEmail         EMAIL(23)
    ├── fieldUrl           URL(24)
    ├── fieldImage         IMAGE(29)
    ├── fieldBoolean       BOOLEAN(31)
    ├── fieldPercent       PERCENT(33)
    ├── fieldDatetime      DATETIME(38)
    ├── fieldFile          FILE(39)
    └── fieldRichtext      RICHTEXT(40)
```

---

## 四、复合组件元模型设计（uiComposite）

### 4.1 元模型注册

```sql
INSERT INTO p_meta_model (api_key, label, namespace, enable_common, enable_tenant, db_table, description)
VALUES ('uiComposite', 'UI复合组件', 'system', 1, 1, 'p_tenant_metadata',
        '复合组件模板，由多个原子组件预组合');
```

### 4.2 字段定义

| api_key | label | item_type | db_column | 说明 |
|:---|:---|:---:|:---|:---|
| compositeType | 模板类型 | 1(TEXT) | dbc_varchar1 | 如 `crudPage`、`formPage` |
| compositeCategory | 分类 | 2(SELECT) | dbc_varchar2 | page/dialog/drawer/widget |
| compositeIcon | 图标名 | 1(TEXT) | dbc_varchar3 | lucide-react 图标名 |
| templateSchema | 模板 Schema | 4(TEXTAREA) | dbc_textarea1 | JSON，CanvasNode[] 模板 |
| generateMode | 生成模式 | 2(SELECT) | dbc_varchar4 | crud/form/detail/list/dashboard |
| compositeOrder | 排序 | 5(NUMBER) | dbc_int1 | 面板中的排序 |
| enableFlg | 启用标记 | 31(BOOLEAN) | dbc_smallint1 | 0=禁用 1=启用 |

### 4.3 预置复合模板

| compositeType | label | generateMode | 包含的原子组件 |
|:---|:---|:---|:---|
| crudPage | CRUD 页面 | crud | title + filterBar + buttonGroup + dataTable + pagination |
| formPage | 表单页面 | form | title + field* + divider + buttonGroup |
| detailPage | 详情页面 | detail | breadcrumb + title + descriptionList + divider + buttonGroup |
| settingsPage | 设置页面 | — | title + text + buttonGroup + dataTable |
| treeListPage | 树形+列表 | — | title + row + tree + dataTable |
| dashboardCard | 仪表盘卡片 | dashboard | statRow + spacer + card + dataTable |

---

## 五、页面与区域元模型（page / pageSection）

### 5.1 page 元模型（已注册）

| api_key | label | item_type | db_column | 说明 |
|:---|:---|:---:|:---|:---|
| pageName | 页面名称 | 1(TEXT) | dbc_varchar1 | 显示名 |
| pageType | 页面类型 | 2(SELECT) | dbc_smallint1 | 1=全屏 2=弹框 3=抽屉 4=内嵌 |
| entityApiKey | 主实体 | 1(TEXT) | dbc_varchar2 | 绑定的业务实体 |
| pageDescription | 描述 | 1(TEXT) | dbc_varchar3 | |
| dialogWidth | 弹框宽度 | 1(TEXT) | dbc_varchar4 | 仅 pageType=2 |
| layoutColumns | 表单列数 | 5(NUMBER) | dbc_smallint2 | 1/2/3 |
| enableFlg | 启用标记 | 31(BOOLEAN) | dbc_smallint3 | |
| routePath | 路由路径 | 1(TEXT) | dbc_varchar5 | 前端路由匹配 |

### 5.2 pageSection 元模型（已注册）

| api_key | label | item_type | db_column | 说明 |
|:---|:---|:---:|:---|:---|
| sectionKey | 区域标识 | 1(TEXT) | dbc_varchar1 | 如 canvas、header、sidebar |
| componentType | 组件类型 | 1(TEXT) | dbc_varchar2 | CanvasSchema / GlobalPickManager / ... |
| componentProps | 组件配置 | 4(TEXTAREA) | dbc_textarea1 | **核心：画布 JSON Schema 存储在此** |
| sectionOrder | 排序 | 5(NUMBER) | dbc_int1 | |
| layoutMode | 布局模式 | 2(SELECT) | dbc_smallint1 | 1=整行 2=半行 3=三分之一 |

### 5.3 画布 JSON Schema 格式（存储在 componentProps 中）

```json
{
  "version": "1.0",
  "components": [
    {
      "id": "c_1713456789_1",
      "type": "title",
      "props": { "text": "语言管理", "level": 2, "align": "left" }
    },
    {
      "id": "c_1713456789_2",
      "type": "dataTable",
      "props": {
        "metamodelApiKey": "globalPickOption",
        "entityApiKey": "language",
        "columns": ["apiKey", "label", "defaultFlg", "enableFlg"],
        "showActions": true,
        "pageSize": 10
      }
    }
  ]
}
```

---

## 六、前端画布编辑器架构

### 6.1 三栏布局

```
┌──────────┬──────────────────────┬───────────────────┐
│ 组件面板  │      画布区域         │     属性面板       │
│ (200px)  │    (flex-1)          │    (260px)        │
│          │                      │                   │
│ ▸ 布局   │  ┌──────────────┐   │  组件: title      │
│  标题    │  │ [title]      │←──│  ─────────        │
│  文本    │  │ "语言管理"    │   │  文本: [语言管理]  │
│  卡片    │  ├──────────────┤   │  级别: [H2 ▼]     │
│  ...     │  │ [dataTable]  │   │  对齐: [左 ▼]     │
│ ▸ 数据   │  │ 📊 表格      │   │                   │
│  表格    │  ├──────────────┤   │                   │
│  树形    │  │ [buttonGroup]│   │                   │
│  ...     │  │ [新增] [删除] │   │                   │
│ ▸ 操作   │  └──────────────┘   │                   │
│  按钮    │                      │                   │
│  ...     │  从左侧拖入或点击添加  │  选中组件查看属性  │
│ ▸ 表单   │                      │                   │
│  文本输入 │                      │                   │
│  单选    │                      │                   │
│  ...     │                      │                   │
│──────────│                      │                   │
│ ▸ 复合模板│                      │                   │
│  CRUD页面│                      │                   │
│  表单页面│                      │                   │
│  详情页面│                      │                   │
└──────────┴──────────────────────┴───────────────────┘
```

### 6.2 文件结构

```
src/pages/canvas/
├── CanvasEditor.tsx              主编辑器（三栏 + 顶栏工具条）
├── types.ts                      类型定义（AtomDef/CanvasNode/PageSchema）
├── registry.ts                   组件注册表（52 个原子 + 映射）
├── compositeGenerator.ts         复合组件自动生成器
│
├── components/
│   ├── ComponentPanel.tsx        左侧组件面板
│   ├── CanvasArea.tsx            中间画布区域（拖拽/选中/排序）
│   ├── PropertyPanel.tsx         右侧属性面板
│   └── GenerateDialog.tsx        从元模型生成弹框
│
├── atoms/                        原子组件（每个文件导出一个 AtomDef）
│   ├── TitleAtom.tsx             标题
│   ├── TextAtom.tsx              文本
│   ├── CardAtom.tsx              卡片
│   ├── TabsAtom.tsx              标签页
│   ├── DataTableAtom.tsx         数据表格
│   ├── TreeAtom.tsx              树形列表
│   ├── ButtonAtom.tsx            按钮
│   ├── ... (共 33 个通用原子)
│   │
│   └── fields/                   表单字段原子（与 ItemTypeEnum 绑定）
│       ├── index.ts              导出 + ITEM_TYPE_TO_FIELD 映射表
│       ├── fieldUtils.tsx        共用工具（FieldWrapper/样式）
│       ├── FieldText.tsx         TEXT(1)
│       ├── FieldSelect.tsx       SELECT(2)
│       ├── ... (共 19 个字段原子)
│
└── composites/                   复合组件模板
    ├── CrudPageComposite.ts
    ├── FormComposite.ts
    ├── DetailPageComposite.ts
    ├── SettingsPageComposite.ts
    └── TreeListComposite.ts
```

### 6.3 核心交互流程

```
管理员打开"页面管理" → 点击某页面的"画布"按钮
    ↓
CanvasEditor 加载
    ↓ listMetadata('page') + listMetadata('pageSection', pageApiKey)
从 pageSection.componentProps 解析 PageSchema
    ↓
三栏渲染：ComponentPanel | CanvasArea | PropertyPanel
    ↓ 用户操作
拖拽添加 / 点击添加 / 从元模型生成 / 属性编辑 / 排序 / 删除 / 复制
    ↓
点击"保存"
    ↓ batchSaveMetadata → pageSection.componentProps = JSON.stringify(schema)
存入 p_common_metadata（Common 级）或 p_tenant_metadata（Tenant 级）
```

### 6.4 运行时渲染流程

```
用户点击菜单 → AdminConsolePage 路由到 pageApiKey
    ↓
PAGE_COMPONENTS 中有注册？→ 使用手写组件（当前过渡阶段）
PAGE_COMPONENTS 中无注册？→ PageRuntime
    ↓
PageRuntime:
  listMetadata('page') → 找到页面定义
  listMetadata('pageSection', pageApiKey) → 找到区域列表
    ↓
  componentType === 'CanvasSchema'？
    → 解析 componentProps 为 PageSchema
    → 遍历 components[]，按 type 从 registry 查找 AtomDef
    → 调用 AtomDef.render(props, { mode: 'preview' })
    → 渲染完整页面
```

---

## 七、复合组件自动生成机制

### 7.1 生成流程

```
用户在画布编辑器点击"从元模型生成"
    ↓
GenerateDialog 弹框
    ↓ 选择元模型（从 listMetaModels 加载）
    ↓ 选择生成模式（crud/form/detail/list/dashboard）
    ↓
compositeGenerator.generateComposite(opts)
    ↓
  1. listMetaItems(metamodelApiKey) → MetaItem[]
  2. listMetaOptions(metamodelApiKey) → MetaOption[]
  3. filterVisibleItems() → 排除系统字段和虚拟字段
  4. 按 mode 组合原子组件：
     - crud:      title + filterBar + buttonGroup + dataTable + pagination
     - form:      title + field*(按 itemType 映射) + buttonGroup
     - detail:    breadcrumb + title + descriptionList + buttonGroup
     - list:      title + dataTable
     - dashboard: statRow + card + dataTable
    ↓
预览 CanvasNode[] → 确认 → 插入画布
```

### 7.2 字段类型 → 组件映射表（ITEM_TYPE_TO_FIELD）

| ItemTypeEnum | code | 前端组件 type | 说明 |
|:---|:---:|:---|:---|
| TEXT | 1 | fieldText | 单行文本 |
| SELECT | 2 | fieldSelect | 单选下拉，自动注入 MetaOption |
| MULTI_SELECT | 3 | fieldMultiSelect | 多选下拉 |
| TEXTAREA | 4 | fieldTextarea | 多行文本 |
| NUMBER | 5,11 | fieldNumber | 整数，支持 min/max |
| CURRENCY | 6 | fieldCurrency | 金额，支持精度和前缀 |
| DATE | 7 | fieldDate | 日期选择 |
| AUTONUMBER | 9 | fieldAutoNumber | 自动编号（只读） |
| RELATION_SHIP | 10,34,41 | fieldRelation | 关联选择弹窗 |
| MULTI_TAG | 16 | fieldMultiTag | 自由标签输入 |
| PHONE | 22,13 | fieldPhone | 电话格式 |
| EMAIL | 23 | fieldEmail | 邮箱格式 |
| URL | 24 | fieldUrl | 网址格式 |
| IMAGE | 29 | fieldImage | 图片上传 |
| BOOLEAN | 31 | fieldBoolean | 开关，0/1 |
| PERCENT | 33 | fieldPercent | 百分比，带 % 后缀 |
| DATETIME | 38,15 | fieldDatetime | 日期+时间 |
| FILE | 39 | fieldFile | 文件上传 |
| RICHTEXT | 40 | fieldRichtext | 富文本编辑器 |

---

## 八、Common/Tenant 双层机制

### 8.1 数据分层

| 层级 | 写入方 | 存储位置 | 场景 |
|:---|:---|:---|:---|
| Common | 平台初始化/Module 安装 | p_common_metadata | 系统出厂组件、默认页面、默认菜单 |
| Tenant | 租户管理员 | p_tenant_metadata | 租户自定义组件、自定义页面布局 |

### 8.2 合并读取规则

```
listMerged('uiComponent')
  → Common: 52 个系统出厂组件
  → Tenant: 租户自定义的 3 个组件
  → 合并结果: 55 个（同 apiKey 的 Tenant 覆盖 Common）

listMerged('page')
  → Common: 系统默认页面（语言管理、时区管理...）
  → Tenant: 租户自定义页面
  → 合并结果: Common + Tenant 去重

listMerged('pageSection')
  → Common: 系统默认画布 Schema
  → Tenant: 租户修改后的画布 Schema（覆盖 Common）
```

### 8.3 租户自定义场景

1. 租户管理员打开"页面管理"→ 编辑画布 → 保存
2. 保存时写入 p_tenant_metadata（Tenant 级），不修改 Common
3. 下次读取时 Tenant 覆盖 Common，该租户看到自定义布局
4. 其他租户不受影响，仍看到 Common 默认布局
5. 租户删除自定义（delete_flg=1）→ 回退到 Common 默认

---

## 九、初始化数据设计

### 9.1 元模型注册 SQL

```sql
-- uiComponent 元模型
INSERT INTO p_meta_model (api_key, label, namespace, enable_common, enable_tenant, db_table)
VALUES ('uiComponent', 'UI组件', 'system', 1, 1, 'p_tenant_metadata');

-- uiComposite 元模型
INSERT INTO p_meta_model (api_key, label, namespace, enable_common, enable_tenant, db_table)
VALUES ('uiComposite', 'UI复合组件', 'system', 1, 1, 'p_tenant_metadata');
```

### 9.2 p_meta_item 字段注册

uiComponent 的 9 个字段 + uiComposite 的 7 个字段，按上文表格注册。

### 9.3 Common 级组件种子数据

52 个原子组件 + 5 个复合模板，每个写入一条 p_common_metadata 记录。
前端 registry.ts 中的硬编码注册作为兜底，元数据加载成功后以元数据为准。

---

## 十、迁移路径

### 阶段一（当前）：前端硬编码 + 元数据存储画布 Schema

- 52 个原子组件在前端 registry.ts 中硬编码注册
- 画布 JSON Schema 存储在 pageSection.componentProps
- PageRuntime 从元数据加载并渲染
- 手写组件（UserManagementView 等）通过 PAGE_COMPONENTS 映射保留

### 阶段二：组件注册元数据化

- 注册 uiComponent/uiComposite 元模型
- 52 个组件写入 p_common_metadata
- 前端启动时从元数据加载组件注册表，与硬编码合并
- 租户可在管理后台禁用/隐藏/排序组件

### 阶段三：全面画布驱动

- 逐步将 PAGE_COMPONENTS 中的手写组件迁移到画布 Schema
- 新增页面全部通过画布编辑器创建
- 手写组件仅保留极少数无法画布化的特殊页面

---

## 十一、属性面板 PropSchema 规范

每个原子组件通过 `propSchema: PropField[]` 声明可编辑属性：

```typescript
interface PropField {
  key: string;           // 属性路径
  label: string;         // 显示名称
  type: PropFieldType;   // 编辑器类型
  defaultValue?: unknown;
  options?: { label: string; value: string | number }[];
  required?: boolean;
  group?: string;        // 基础 | 数据 | 样式
  placeholder?: string;
}

type PropFieldType =
  | 'string'           // 文本输入
  | 'number'           // 数字输入
  | 'boolean'          // 开关
  | 'select'           // 单选下拉
  | 'multiSelect'      // 多选标签
  | 'json'             // JSON 编辑器
  | 'color'            // 颜色选择器
  | 'metamodelPicker'  // 元模型选择器（从 listMetaModels 加载）
  | 'fieldPicker';     // 字段选择器（从 listMetaItems 加载）
```

属性分组约定：
- **基础**：文本、标签、必填、只读等核心属性
- **数据**：metamodelApiKey、entityApiKey、columns、optionSource 等数据绑定
- **样式**：颜色、间距、对齐、尺寸等视觉属性
