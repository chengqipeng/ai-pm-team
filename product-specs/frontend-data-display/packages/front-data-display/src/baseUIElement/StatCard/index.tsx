/**
 * StatCard / StatPanel — 统计面板
 *
 * 对齐老项目 baseUIElement/Statistic 的组件结构
 */
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { formatNumber } from '../../util'
import type { StatPanelProps, StatItem } from './interface'

export type { StatPanelProps, StatItem } from './interface'

export default function StatPanel({ items, title, layout = 'horizontal' }: StatPanelProps) {
  return (
    <div className="bg-white rounded-xl border border-gray-200/80 overflow-hidden">
      {title && <div className="px-5 py-3 border-b border-gray-100"><h3 className="text-sm font-semibold text-gray-700">{title}</h3></div>}
      <div className={`p-4 ${layout === 'horizontal' ? 'flex items-stretch gap-4 overflow-x-auto' : 'grid grid-cols-2 gap-4'}`}>
        {items.map((item, idx) => <StatCardItem key={idx} item={item} />)}
      </div>
    </div>
  )
}

function StatCardItem({ item }: { item: StatItem }) {
  const trendColor = item.trend ? (item.trend > 0 ? 'text-green-600' : 'text-red-500') : 'text-gray-400'
  const TrendIcon = item.trend ? (item.trend > 0 ? TrendingUp : TrendingDown) : Minus
  const displayValue = typeof item.value === 'number' ? formatNumber(item.value) : item.value

  return (
    <div className="flex-1 min-w-[120px] bg-gray-50/80 rounded-xl p-4 flex flex-col items-center text-center">
      {item.icon && <span className="text-lg mb-1">{item.icon}</span>}
      <div className="flex items-baseline gap-0.5">
        {item.prefix && <span className="text-sm text-gray-400">{item.prefix}</span>}
        <span className="text-2xl font-bold" style={{ color: item.color || '#1677ff' }}>{displayValue}</span>
        {item.suffix && <span className="text-sm text-gray-400">{item.suffix}</span>}
      </div>
      <span className="text-xs text-gray-500 mt-1">{item.label}</span>
      {item.trend != null && (
        <div className={`flex items-center gap-0.5 mt-1.5 ${trendColor}`}>
          <TrendIcon className="w-3 h-3" />
          <span className="text-[10px] font-medium">{item.trend > 0 ? '+' : ''}{item.trend.toFixed(1)}%</span>
        </div>
      )}
    </div>
  )
}
