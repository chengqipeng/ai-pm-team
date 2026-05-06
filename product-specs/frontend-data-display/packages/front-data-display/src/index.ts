/**
 * front-data-display 包入口
 *
 * 对齐老项目 neo-ui-component-web/src/index.tsx 的导出模式
 *
 * 分层导出：
 * - baseUIElement: 原子级 UI 组件（DataTable, DataCard, StatPanel）
 * - baseBusinessElement: 业务级组件（FieldRenderer, DetailPanel）
 * - neoCmps: 外壳组件（NeoEntityGrid, NeoEntityDetail）
 * - layoutCmps: 布局组件（PageLayout）
 * - formUtil: 字段渲染工厂
 * - stores: 状态管理
 * - types: 类型定义
 * - consts: 常量
 * - util: 工具函数
 */

// ── 原子级 UI 组件 ──
export { DataTable, DataCard, DataCardGrid, StatPanel } from './baseUIElement'
export type { DataTableProps, DataCardProps, DataCardGridProps, StatPanelProps, StatItem } from './baseUIElement'

// ── 业务级组件 ──
export { FieldRenderer, DetailPanel } from './baseBusinessElement'
export type { FieldRendererProps } from './baseBusinessElement'
export type { DetailPanelProps } from './baseBusinessElement'

// ── 外壳组件 ──
export { NeoEntityGrid, NeoEntityDetail } from './neoCmps'
export type { NeoEntityGridProps, NeoEntityDetailProps } from './neoCmps'

// ── 布局组件 ──
export { PageLayout } from './layoutCmps'
export type { PageLayoutProps } from './layoutCmps'

// ── 字段渲染工厂 ──
export { registerFieldRenderer, getFieldRenderer } from './formUtil'
export type { FieldRendererEntry } from './formUtil'

// ── 状态管理 ──
export { DataListStore } from './stores'

// ── 类型 ──
export type { FieldMeta, PickOption, FieldGroup, DataRecord, Pagination, SortParam, FilterCondition } from './types'

// ── 常量 ──
export { ITEM_TYPE, ITEM_TYPE_LABEL } from './consts'

// ── 工具函数 ──
export { formatFieldValue, formatNumber, formatRelativeTime, truncate } from './util'
