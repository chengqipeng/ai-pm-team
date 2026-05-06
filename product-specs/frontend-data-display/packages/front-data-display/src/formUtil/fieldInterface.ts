/**
 * 字段渲染器接口定义
 *
 * 对齐老项目 formUtil/formFieldInterfac.tsx
 * 定义字段渲染器的标准接口，所有字段类型渲染器都实现此接口
 */
import type { FieldMeta } from '../types'

/** 字段渲染模式 */
export type FieldRenderMode = 'display' | 'edit' | 'filter' | 'grid'

/** 字段渲染器 Props */
export interface FieldRendererProps {
  /** 字段元数据 */
  field: FieldMeta
  /** 字段值 */
  value: unknown
  /** 渲染模式 */
  mode: FieldRenderMode
  /** 值变更回调（编辑模式） */
  onChange?: (value: unknown) => void
  /** 自定义样式 */
  className?: string
}

/** 字段渲染器注册表项 */
export interface FieldRendererEntry {
  /** 支持的 itemType 列表 */
  itemTypes: number[]
  /** 渲染器组件 */
  component: React.ComponentType<FieldRendererProps>
}
