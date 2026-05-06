/**
 * 数据记录类型定义
 */

/** 通用数据记录 */
export type DataRecord = Record<string, unknown> & {
  id: number | string
  name?: string
  createdAt?: number
  updatedAt?: number
  ownerId?: number | string
  deleteFlg?: number
}

/** 分页参数 */
export interface Pagination {
  current: number
  pageSize: number
  total: number
}

/** 排序参数 */
export interface SortParam {
  field: string
  order: 'asc' | 'desc'
}

/** 筛选条件 */
export interface FilterCondition {
  field: string
  operator: 'eq' | 'ne' | 'gt' | 'lt' | 'gte' | 'lte' | 'like' | 'in' | 'between'
  value: unknown
}
