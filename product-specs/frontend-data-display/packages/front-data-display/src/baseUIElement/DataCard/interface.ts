/**
 * DataCard 接口定义
 */
import type { FieldMeta, DataRecord } from '../../types'

export interface DataCardProps {
  record: DataRecord
  fields: FieldMeta[]
  maxFields?: number
  accentColor?: string
  tags?: { label: string; color?: string }[]
  headerExtra?: React.ReactNode
  onClick?: (record: DataRecord) => void
  onMoreAction?: (record: DataRecord) => void
  themeTokens?: Record<string, string>
}

export interface DataCardGridProps {
  children: React.ReactNode
  columns?: 2 | 3 | 4
}
