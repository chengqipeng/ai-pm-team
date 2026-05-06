/**
 * 格式化工具函数
 *
 * 对齐老项目 neo-ui-component-web/src/util/ 的工具函数模式
 */
import { ITEM_TYPE } from '../consts'
import type { FieldMeta } from '../types'

/** 格式化字段值为展示文本 */
export function formatFieldValue(value: unknown, field: FieldMeta): string {
  if (value == null || value === '') return '—'

  switch (field.itemType) {
    case ITEM_TYPE.BOOLEAN:
      return value ? '是' : '否'
    case ITEM_TYPE.DATE: {
      const n = Number(value)
      return !isNaN(n) && n > 1e9 ? new Date(n).toLocaleDateString('zh-CN') : String(value)
    }
    case ITEM_TYPE.DATETIME: {
      const n = Number(value)
      return !isNaN(n) && n > 1e9 ? new Date(n).toLocaleString('zh-CN') : String(value)
    }
    case ITEM_TYPE.PERCENT:
      return `${Number(value).toFixed(1)}%`
    case ITEM_TYPE.CURRENCY:
    case ITEM_TYPE.DECIMAL:
      return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2 })
    case ITEM_TYPE.INTEGER:
      return Number(value).toLocaleString('zh-CN')
    case ITEM_TYPE.SINGLE_SELECT:
    case ITEM_TYPE.MULTI_SELECT: {
      const vals = Array.isArray(value) ? value : [value]
      return vals.map(v => field.options?.find(o => o.value === v)?.label ?? String(v)).join(', ')
    }
    default:
      return String(value)
  }
}

/** 格式化数字简写 */
export function formatNumber(n: number): string {
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return String(n)
}

/** 格式化相对时间 */
export function formatRelativeTime(ts: number): string {
  const now = Date.now()
  const diff = now - (ts > 1e12 ? ts : ts * 1000)
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  if (diff < 604800000) return `${Math.floor(diff / 86400000)} 天前`
  return new Date(ts > 1e12 ? ts : ts * 1000).toLocaleDateString('zh-CN')
}

/** 截断文本 */
export function truncate(text: string, maxLen: number): string {
  return text.length > maxLen ? text.slice(0, maxLen) + '...' : text
}
