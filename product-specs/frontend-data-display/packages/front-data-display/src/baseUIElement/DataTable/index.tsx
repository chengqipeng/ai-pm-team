/**
 * DataTable — 元数据驱动的数据表格
 *
 * 对齐老项目 baseUIElement/NeoGrid 的组件结构：
 * - index.tsx: 组件入口 + 注册
 * - interface.ts: Props 接口
 * - component.tsx: 组件实现（此处合并到 index）
 *
 * 功能：动态列渲染、排序、分页、行选择、行内操作
 */
import { useState, useMemo, useCallback } from 'react'
import {
  ChevronLeft, ChevronRight, ChevronUp, ChevronDown,
  Eye, Edit2, Trash2, Plus, RefreshCw, Download,
} from 'lucide-react'
import { formatFieldValue } from '../../util'
import type { DataTableProps } from './interface'

export type { DataTableProps } from './interface'

export default function DataTable({
  fields, records, pagination, loading, maxColumns = 8,
  selectable, sort, onSortChange, onPageChange,
  onView, onEdit, onDelete, onCreate, onRefresh, onExport,
  onBatchAction,
}: DataTableProps) {
  const [selectedIds, setSelectedIds] = useState<Set<number | string>>(new Set())

  const displayFields = useMemo(() =>
    fields
      .filter(f => f.enableFlg !== 0 && f.visibleFlg !== 0)
      .sort((a, b) => (a.itemOrder ?? 999) - (b.itemOrder ?? 999))
      .slice(0, maxColumns),
    [fields, maxColumns]
  )

  const totalPages = Math.ceil(pagination.total / pagination.pageSize) || 1
  const hasActions = onView || onEdit || onDelete

  const toggleSelect = useCallback((id: number | string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }, [])

  const toggleSelectAll = useCallback(() => {
    setSelectedIds(prev =>
      prev.size === records.length ? new Set() : new Set(records.map(r => r.id))
    )
  }, [records])

  const handleSort = (field: string) => {
    if (!onSortChange) return
    onSortChange({ field, order: sort?.field === field && sort.order === 'asc' ? 'desc' : 'asc' })
  }

  return (
    <div className="flex flex-col h-full bg-white rounded-xl border border-gray-200/80 overflow-hidden">
      {/* 工具栏 — 对齐老项目 GridToolbar 模式 */}
      <div className="shrink-0 px-5 py-3 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">共 <b className="text-gray-700">{pagination.total}</b> 条</span>
          {onRefresh && (
            <button onClick={onRefresh} className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors">
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          )}
          {selectedIds.size > 0 && onBatchAction && (
            <div className="flex items-center gap-2 ml-2 pl-3 border-l border-gray-200">
              <span className="text-xs text-blue-600">已选 {selectedIds.size} 条</span>
              <button onClick={() => onBatchAction('delete', [...selectedIds])}
                className="text-xs text-red-500 hover:text-red-600 px-2 py-1 rounded hover:bg-red-50">批量删除</button>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          {onExport && (
            <button onClick={onExport} className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50">
              <Download className="w-3.5 h-3.5" /> 导出
            </button>
          )}
          {onCreate && (
            <button onClick={onCreate} className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 shadow-sm">
              <Plus className="w-4 h-4" /> 新建
            </button>
          )}
        </div>
      </div>

      {/* 表格主体 */}
      {loading ? (
        <div className="flex-1 flex items-center justify-center">
          <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
        </div>
      ) : records.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-gray-400">
          <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mb-3">
            <Plus className="w-6 h-6 text-gray-300" />
          </div>
          <p className="text-sm">暂无数据</p>
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 sticky top-0 z-10">
              <tr>
                {selectable && (
                  <th className="w-10 px-3 py-2.5">
                    <input type="checkbox" checked={selectedIds.size === records.length && records.length > 0}
                      onChange={toggleSelectAll} className="w-3.5 h-3.5 rounded border-gray-300 text-blue-600" />
                  </th>
                )}
                <th className="text-left px-4 py-2.5 font-medium text-gray-500 text-xs uppercase tracking-wider">名称</th>
                {displayFields.map(field => (
                  <th key={field.apiKey}
                    className="text-left px-4 py-2.5 font-medium text-gray-500 text-xs uppercase tracking-wider max-w-[180px] cursor-pointer select-none hover:text-gray-700"
                    onClick={() => handleSort(field.apiKey)}>
                    <div className="flex items-center gap-1">
                      {field.label}
                      {sort?.field === field.apiKey && (sort.order === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />)}
                    </div>
                  </th>
                ))}
                {hasActions && <th className="text-center px-3 py-2.5 font-medium text-gray-500 text-xs w-28">操作</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {records.map(record => (
                <tr key={String(record.id)} className="hover:bg-blue-50/30 transition-colors group">
                  {selectable && (
                    <td className="px-3 py-2.5">
                      <input type="checkbox" checked={selectedIds.has(record.id)} onChange={() => toggleSelect(record.id)}
                        className="w-3.5 h-3.5 rounded border-gray-300 text-blue-600" />
                    </td>
                  )}
                  <td className="px-4 py-2.5">
                    <button onClick={() => onView?.(record)} className="text-blue-600 hover:text-blue-700 hover:underline font-medium text-sm">
                      {String(record.name || '—')}
                    </button>
                  </td>
                  {displayFields.map(field => (
                    <td key={field.apiKey} className="px-4 py-2.5 text-gray-600 max-w-[180px] truncate text-sm">
                      {formatFieldValue(record[field.apiKey], field)}
                    </td>
                  ))}
                  {hasActions && (
                    <td className="text-center px-3 py-2.5">
                      <div className="flex items-center justify-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        {onView && <button onClick={() => onView(record)} className="p-1 text-gray-400 hover:text-blue-600 rounded"><Eye className="w-3.5 h-3.5" /></button>}
                        {onEdit && <button onClick={() => onEdit(record)} className="p-1 text-gray-400 hover:text-blue-600 rounded"><Edit2 className="w-3.5 h-3.5" /></button>}
                        {onDelete && <button onClick={() => onDelete(record)} className="p-1 text-gray-400 hover:text-red-500 rounded"><Trash2 className="w-3.5 h-3.5" /></button>}
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 分页 — 对齐老项目 baseUIElement/Pagination */}
      {pagination.total > pagination.pageSize && (
        <div className="shrink-0 px-5 py-3 border-t border-gray-100 flex items-center justify-between bg-white">
          <span className="text-xs text-gray-400">第 {pagination.current}/{totalPages} 页 · 共 {pagination.total} 条</span>
          <div className="flex items-center gap-1">
            <button onClick={() => onPageChange?.(pagination.current - 1)} disabled={pagination.current <= 1}
              className="p-1.5 text-gray-400 hover:text-gray-600 disabled:opacity-30 rounded-lg hover:bg-gray-100">
              <ChevronLeft className="w-4 h-4" />
            </button>
            {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
              const start = Math.max(1, Math.min(pagination.current - 2, totalPages - 4))
              const p = start + i
              return p <= totalPages ? (
                <button key={p} onClick={() => onPageChange?.(p)}
                  className={`w-8 h-8 text-xs rounded-lg ${p === pagination.current ? 'bg-blue-600 text-white' : 'text-gray-500 hover:bg-gray-100'}`}>
                  {p}
                </button>
              ) : null
            })}
            <button onClick={() => onPageChange?.(pagination.current + 1)} disabled={pagination.current >= totalPages}
              className="p-1.5 text-gray-400 hover:text-gray-600 disabled:opacity-30 rounded-lg hover:bg-gray-100">
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
