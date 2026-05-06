/**
 * DetailPanel — 详情面板
 *
 * 对齐老项目 baseBusinessElement/CommonView 的模式
 * 根据字段元数据动态渲染详情，支持字段分组
 */
import { Edit2, Trash2 } from 'lucide-react'
import FieldRenderer from '../FieldRenderer'
import { formatRelativeTime } from '../../util'
import type { FieldMeta, FieldGroup, DataRecord } from '../../types'

export interface DetailPanelProps {
  record: DataRecord
  groups?: FieldGroup[]
  fields?: FieldMeta[]
  onEdit?: () => void
  onDelete?: () => void
  headerExtra?: React.ReactNode
}

export default function DetailPanel({ record, groups, fields, onEdit, onDelete, headerExtra }: DetailPanelProps) {
  const fieldGroups: FieldGroup[] = groups || autoGroupFields(fields || [])

  return (
    <div className="space-y-5">
      {/* 头部 */}
      <div className="bg-white rounded-xl border border-gray-200/80 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold text-gray-800">{String(record.name || '未命名')}</h2>
            <p className="text-xs text-gray-400 mt-1">
              ID: {String(record.id)}
              {record.createdAt && ` · 创建于 ${formatRelativeTime(record.createdAt)}`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {headerExtra}
            {onEdit && (
              <button onClick={onEdit} className="flex items-center gap-1.5 px-4 py-2 text-sm text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-50">
                <Edit2 className="w-3.5 h-3.5" /> 编辑
              </button>
            )}
            {onDelete && (
              <button onClick={onDelete} className="flex items-center gap-1.5 px-4 py-2 text-sm text-red-500 border border-red-200 rounded-lg hover:bg-red-50">
                <Trash2 className="w-3.5 h-3.5" /> 删除
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 字段分组 */}
      {fieldGroups.map((group, gi) => (
        <div key={gi} className="bg-white rounded-xl border border-gray-200/80 overflow-hidden">
          <div className="px-5 py-3 bg-gray-50 border-b border-gray-100">
            <h3 className="text-sm font-semibold text-gray-700">{group.title}</h3>
          </div>
          <div className="grid grid-cols-2 gap-px bg-gray-100">
            {group.fields.map(field => (
              <div key={field.apiKey} className="bg-white px-5 py-3">
                <div className="text-xs text-gray-400 mb-1">{field.label}</div>
                <FieldRenderer field={field} value={record[field.apiKey]} />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function autoGroupFields(fields: FieldMeta[]): FieldGroup[] {
  const visible = fields.filter(f => f.enableFlg !== 0 && f.visibleFlg !== 0)
    .sort((a, b) => (a.itemOrder ?? 999) - (b.itemOrder ?? 999))
  const systemKeys = new Set(['createdAt', 'updatedAt', 'createdBy', 'updatedBy', 'deleteFlg'])
  const basic = visible.filter(f => !systemKeys.has(f.apiKey))
  const system = visible.filter(f => systemKeys.has(f.apiKey))
  const groups: FieldGroup[] = []
  if (basic.length) groups.push({ title: '基本信息', fields: basic })
  if (system.length) groups.push({ title: '系统信息', fields: system })
  return groups
}
