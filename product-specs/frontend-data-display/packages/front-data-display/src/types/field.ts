/**
 * 字段元数据类型定义
 *
 * 对齐老项目 formUtil/formFieldInterfac.tsx 和新项目 XEntityItem
 */

/** 字段元数据 */
export interface FieldMeta {
  apiKey: string
  label: string
  itemType: number
  itemOrder?: number
  enableFlg?: number
  visibleFlg?: number
  requiredFlg?: number
  dbColumn?: string
  helpText?: string
  /** 选项值（单选/多选） */
  options?: PickOption[]
  /** 关联实体 apiKey（lookup 字段） */
  referObjectApiKey?: string
  /** 是否锁定列 */
  lockFlg?: number
  /** 列宽 */
  width?: number
  /** 最小列宽 */
  minWidth?: number
}

/** 选项值 */
export interface PickOption {
  apiKey: string
  label: string
  value: string | number
  color?: string
  optionCode?: number
}

/** 字段分组 */
export interface FieldGroup {
  title: string
  fields: FieldMeta[]
}
