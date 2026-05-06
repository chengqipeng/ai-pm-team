/**
 * NeoEntityGrid — 实体数据表格外壳组件
 *
 * 对齐老项目 neoCmps/business/NeoEntityGrid 的模式
 * 封装完整的实体数据列表功能：
 * - 自动加载字段元数据
 * - 自动加载业务数据
 * - 内置筛选、排序、分页
 * - 内置新建/编辑/删除操作
 *
 * 外部使用方式（对齐老项目 README.md 示例）：
 * ```tsx
 * <NeoEntityGrid
 *   entityApiKey="account"
 *   onItemClick={(record) => navigate(`/detail/${record.id}`)}
 * />
 * ```
 */
import { useState, useEffect, useCallback } from 'react'
import DataTable from '../../baseUIElement/DataTable'
import type { FieldMeta, DataRecord, Pagination, SortParam, FilterCondition } from '../../types'

export interface NeoEntityGridProps {
  /** 实体 apiKey */
  entityApiKey: string
  /** 点击行回调 */
  onItemClick?: (record: DataRecord) => void
  /** 自定义数据加载函数（不提供则使用默认 API） */
  fetchData?: (params: { entityApiKey: string; page: number; pageSize: number; sort?: SortParam; filters?: FilterCondition[] }) => Promise<{ records: DataRecord[]; total: number }>
  /** 自定义字段加载函数 */
  fetchFields?: (entityApiKey: string) => Promise<FieldMeta[]>
  /** 是否禁用搜索 */
  disableSearch?: boolean
  /** 是否禁用排序 */
  disableSort?: boolean
  /** 是否禁用筛选 */
  disableFilter?: boolean
  /** 每页条数 */
  pageSize?: number
  /** 自定义样式 */
  className?: string
  style?: React.CSSProperties
}

export default function NeoEntityGrid({
  entityApiKey, onItemClick, fetchData: customFetchData, fetchFields: customFetchFields,
  disableSearch, disableSort, disableFilter, pageSize = 20, className, style,
}: NeoEntityGridProps) {
  const [fields, setFields] = useState<FieldMeta[]>([])
  const [records, setRecords] = useState<DataRecord[]>([])
  const [pagination, setPagination] = useState<Pagination>({ current: 1, pageSize, total: 0 })
  const [sort, setSort] = useState<SortParam | undefined>()
  const [loading, setLoading] = useState(false)

  // 加载字段元数据
  useEffect(() => {
    const load = customFetchFields || defaultFetchFields
    load(entityApiKey).then(setFields).catch(() => setFields([]))
  }, [entityApiKey])

  // 加载数据
  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const fetcher = customFetchData || defaultFetchData
      const result = await fetcher({ entityApiKey, page: pagination.current, pageSize, sort })
      setRecords(result.records)
      setPagination(prev => ({ ...prev, total: result.total }))
    } catch {
      setRecords([])
    } finally {
      setLoading(false)
    }
  }, [entityApiKey, pagination.current, pageSize, sort])

  useEffect(() => { loadData() }, [loadData])
  useEffect(() => { setPagination(prev => ({ ...prev, current: 1 })) }, [entityApiKey])

  return (
    <div className={className} style={style}>
      <DataTable
        fields={fields}
        records={records}
        pagination={pagination}
        loading={loading}
        selectable
        sort={sort}
        onSortChange={disableSort ? undefined : setSort}
        onPageChange={page => setPagination(prev => ({ ...prev, current: page }))}
        onView={onItemClick}
        onRefresh={loadData}
      />
    </div>
  )
}

// 默认 API 函数（占位，实际项目中替换为真实 API 调用）
async function defaultFetchFields(entityApiKey: string): Promise<FieldMeta[]> {
  // TODO: 替换为 listEntityItems(entityApiKey) 调用
  return []
}

async function defaultFetchData(params: { entityApiKey: string; page: number; pageSize: number }): Promise<{ records: DataRecord[]; total: number }> {
  // TODO: 替换为 listBizData(entityApiKey, page, pageSize) 调用
  return { records: [], total: 0 }
}
