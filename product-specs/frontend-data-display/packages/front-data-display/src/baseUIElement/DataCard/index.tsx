/**
 * DataCard — 卡片式数据展示
 *
 * 对齐老项目 baseUIElement/Card 的组件结构
 */
import { MoreHorizontal } from 'lucide-react'
import { formatFieldValue } from '../../util'
import type { DataCardProps, DataCardGridProps } from './interface'

export type { DataCardProps, DataCardGridProps } from './interface'

export default function DataCard({
  record, fields, maxFields = 4, accentColor,
  tags, headerExtra, onClick, onMoreAction,
}: DataCardProps) {
  const displayFields = fields
    .filter(f => f.enableFlg !== 0 && f.visibleFlg !== 0)
    .slice(0, maxFields)

  return (
    <div onClick={() => onClick?.(record)}
      className={`bg-white rounded-xl border border-gray-200/80 overflow-hidden transition-all duration-200 group hover:border-blue-300 hover:shadow-md ${onClick ? 'cursor-pointer' : ''}`}>
      {accentColor && <div className="h-1" style={{ backgroundColor: accentColor }} />}
      <div className="px-4 pt-4 pb-2 flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <h4 className="text-sm font-semibold text-gray-800 truncate">{String(record.name || '未命名')}</h4>
          {tags && tags.length > 0 && (
            <div className="flex items-center gap-1.5 mt-1.5">
              {tags.map((tag, i) => (
                <span key={i} className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium"
                  style={{ backgroundColor: tag.color ? `${tag.color}15` : '#f3f4f6', color: tag.color || '#6b7280' }}>
                  {tag.label}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {headerExtra}
          {onMoreAction && (
            <button onClick={e => { e.stopPropagation(); onMoreAction(record) }}
              className="p-1 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100 opacity-0 group-hover:opacity-100 transition-all">
              <MoreHorizontal className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
      <div className="px-4 pb-4 space-y-2">
        {displayFields.map(field => (
          <div key={field.apiKey} className="flex items-center justify-between">
            <span className="text-xs text-gray-400 shrink-0">{field.label}</span>
            <span className="text-xs text-gray-700 text-right truncate ml-3 max-w-[60%]">
              {formatFieldValue(record[field.apiKey], field)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/** DataCardGrid — 卡片网格布局容器 */
export function DataCardGrid({ children, columns = 3 }: DataCardGridProps) {
  const colClass = { 2: 'grid-cols-1 sm:grid-cols-2', 3: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3', 4: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4' }[columns]
  return <div className={`grid ${colClass} gap-4 p-5`}>{children}</div>
}
