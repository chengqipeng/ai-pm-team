/**
 * DataTable 接口定义
 *
 * 对齐老项目 baseUIElement/Table/interface.tsx 和 NeoGrid/interface.tsx 的模式
 */
import type { FieldMeta, DataRecord, Pagination, SortParam } from '../../types'

export interface DataTableProps {
  /** 字段元数据列表 */
  fields: FieldMeta[]
  /** 数据记录 */
  records: DataRecord[]
  /** 分页信息 */
  pagination: Pagination
  /** 加载状态 */
  loading?: boolean
  /** 最大显示列数 */
  maxColumns?: number
  /** 是否显示行选择框 */
  selectable?: boolean
  /** 排序参数 */
  sort?: SortParam
  /** 排序变更 */
  onSortChange?: (sort: SortParam) => void
  /** 分页变更 */
  onPageChange?: (page: number) => void
  /** 查看记录 */
  onView?: (record: DataRecord) => void
  /** 编辑记录 */
  onEdit?: (record: DataRecord) => void
  /** 删除记录 */
  onDelete?: (record: DataRecord) => void
  /** 新建记录 */
  onCreate?: () => void
  /** 刷新数据 */
  onRefresh?: () => void
  /** 导出数据 */
  onExport?: () => void
  /** 批量操作 */
  onBatchAction?: (action: string, ids: (number | string)[]) => void
  /** 主题扩展属性（对齐老项目 themeTokens） */
  themeTokens?: Record<string, string>
}
