# CRM 前端数据展示组件库 — 模块化设计方案

## 设计参考

参考 `apass_old_projects` 中的前端模块化体系：

| 老项目 | 模式 | 本方案对应 |
|:---|:---|:---|
| `xsy-neo-ui-component` Monorepo | `packages/` 按平台分包 | `packages/` 按职责分包 |
| `neo-ui-component-web/baseUIElement/` | 每个组件一个目录（index + interface + styled） | `baseUIElement/` 原子组件 |
| `neo-ui-component-web/baseBusinessElement/` | 业务级组件（FieldItems, GridItems, SearchCondition） | `businessElement/` 业务组件 |
| `neo-ui-component-web/neoCmps/` | 外壳组件（NeoEntityGrid 等） | `neoCmps/` 外壳组件 |
| `neo-ui-component-web/layoutCmps/` | 布局组件（neoPage, neoContainer） | `layoutCmps/` 布局组件 |
| `neo-ui-component-web/formUtil/` | 表单字段工厂 + 字段渲染器 | `formUtil/` 字段渲染 |
| `neo-ui-design-token` | 设计令牌（颜色/间距/字号） | `design-token/` 设计令牌 |
| `apps-ingage-web/base/stores/` | MobX-State-Tree 全局状态 | `stores/` 状态管理 |
| `apps-ingage-web/pages/crm/` | 按业务实体一个文件 | `pages/` 页面层 |

## 目录结构

```
packages/
├── front-data-display/              # 数据展示组件包（核心）
│   └── src/
│       ├── baseUIElement/           # 原子级 UI 组件
│       │   ├── DataTable/           # 表格（index + interface + styled）
│       │   ├── DataCard/            # 卡片
│       │   ├── StatCard/            # 统计卡片
│       │   ├── FilterBar/           # 筛选栏
│       │   ├── Timeline/            # 时间线
│       │   ├── KanbanColumn/        # 看板列
│       │   └── index.ts             # 统一导出
│       ├── baseBusinessElement/     # 业务级组件
│       │   ├── FieldRenderer/       # 字段值渲染器（按 itemType 分发）
│       │   ├── DetailPanel/         # 详情面板（字段分组）
│       │   ├── GridToolbar/         # 表格工具栏（新建/导出/批量）
│       │   └── index.ts
│       ├── neoCmps/                 # 外壳组件（对外暴露的完整功能组件）
│       │   ├── NeoEntityGrid/       # 实体数据表格（完整功能）
│       │   ├── NeoEntityDetail/     # 实体详情页
│       │   ├── NeoEntityKanban/     # 实体看板
│       │   └── index.ts
│       ├── layoutCmps/              # 布局组件
│       │   ├── PageLayout/          # 页面布局（侧边栏+顶栏+内容区）
│       │   ├── SplitView/           # 分栏视图
│       │   └── index.ts
│       ├── formUtil/                # 表单/字段工具
│       │   ├── fieldFactory.ts      # 字段渲染工厂（itemType → 组件映射）
│       │   ├── fieldInterface.ts    # 字段接口定义
│       │   ├── formatters.ts        # 值格式化函数
│       │   └── index.ts
│       ├── stores/                  # 状态管理（MobX）
│       │   ├── DataListStore.ts     # 列表数据状态
│       │   ├── FilterStore.ts       # 筛选状态
│       │   └── index.ts
│       ├── consts/                  # 常量
│       │   ├── itemTypes.ts         # 字段类型枚举
│       │   └── index.ts
│       ├── types/                   # TypeScript 类型
│       │   ├── field.ts             # 字段元数据类型
│       │   ├── record.ts            # 数据记录类型
│       │   └── index.ts
│       ├── util/                    # 工具函数
│       │   ├── format.ts            # 格式化
│       │   ├── filter.ts            # 筛选逻辑
│       │   └── index.ts
│       └── index.ts                 # 包入口
├── front-design-token/              # 设计令牌包（已有，扩展）
└── front-data-display-i18n/         # 国际化资源包
```

## 技术栈

- React 19 + TypeScript 5.9
- Ant Design 6（baseUIElement 层封装）
- MobX + mobx-react-lite（状态管理，对齐老项目 MobX-State-Tree 模式）
- TailwindCSS（样式，对齐新项目 paas-front-platform）
- Vite 8（构建）
