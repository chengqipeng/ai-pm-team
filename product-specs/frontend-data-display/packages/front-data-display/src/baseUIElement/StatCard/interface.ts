/**
 * StatCard 接口定义
 *
 * 对齐老项目 baseUIElement/Statistic/interface.tsx
 */
export interface StatItem {
  label: string
  value: number | string
  prefix?: string
  suffix?: string
  trend?: number
  icon?: string
  color?: string
}

export interface StatPanelProps {
  items: StatItem[]
  title?: string
  layout?: 'horizontal' | 'vertical'
  themeTokens?: Record<string, string>
}
