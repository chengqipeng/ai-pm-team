/**
 * FieldRenderer — 字段值渲染器
 *
 * 对齐老项目 baseBusinessElement/FieldItems 的模式
 * 根据字段类型（itemType）分发到不同的渲染策略
 * 支持 display / edit / filter / grid 四种渲染模式
 */
import { Phone, Mail, ExternalLink } from 'lucide-react'
import { ITEM_TYPE } from '../../consts'
import { formatFieldValue } from '../../util'
import { getFieldRenderer } from '../../formUtil'
import type { FieldMeta } from '../../types'

export interface FieldRendererProps {
  field: FieldMeta
  value: unknown
  mode?: 'display' | 'grid'
}

export default function FieldRenderer({ field, value, mode = 'display' }: FieldRendererProps) {
  // 优先使用注册的自定义渲染器
  const CustomRenderer = getFieldRenderer(field.itemType)
  if (CustomRenderer) {
    return <CustomRenderer field={field} value={value} mode={mode} />
  }

  const displayText = formatFieldValue(value, field)

  // 电话 — 可点击拨打
  if (field.itemType === ITEM_TYPE.PHONE && value) {
    return (
      <a href={`tel:${value}`} className="text-sm text-blue-600 hover:text-blue-700 flex items-center gap-1">
        <Phone className="w-3 h-3" /> {displayText}
      </a>
    )
  }

  // 邮箱 — 可点击发送
  if (field.itemType === ITEM_TYPE.EMAIL && value) {
    return (
      <a href={`mailto:${value}`} className="text-sm text-blue-600 hover:text-blue-700 flex items-center gap-1">
        <Mail className="w-3 h-3" /> {displayText}
      </a>
    )
  }

  // URL — 可点击打开
  if (field.itemType === ITEM_TYPE.URL && value) {
    return (
      <a href={String(value)} target="_blank" rel="noopener noreferrer"
        className="text-sm text-blue-600 hover:text-blue-700 flex items-center gap-1">
        <ExternalLink className="w-3 h-3" /> {displayText}
      </a>
    )
  }

  // 布尔 — 彩色标签
  if (field.itemType === ITEM_TYPE.BOOLEAN) {
    return (
      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
        value ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-500'
      }`}>
        {value ? '✓ 是' : '✗ 否'}
      </span>
    )
  }

  // 单选/多选 — 标签样式
  if ((field.itemType === ITEM_TYPE.SINGLE_SELECT || field.itemType === ITEM_TYPE.MULTI_SELECT) && value) {
    const values = Array.isArray(value) ? value : [value]
    return (
      <div className="flex items-center gap-1 flex-wrap">
        {values.map((v, i) => {
          const opt = field.options?.find(o => o.value === v)
          return (
            <span key={i} className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
              style={{ backgroundColor: opt?.color ? `${opt.color}15` : '#f3f4f6', color: opt?.color || '#6b7280' }}>
              {opt?.label ?? String(v)}
            </span>
          )
        })}
      </div>
    )
  }

  // 默认文本
  return <span className="text-sm text-gray-800">{displayText}</span>
}
