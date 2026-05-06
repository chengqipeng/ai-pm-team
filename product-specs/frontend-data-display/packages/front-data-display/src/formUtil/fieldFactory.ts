/**
 * 字段渲染工厂
 *
 * 对齐老项目 formUtil/formAmisFactory.tsx 的工厂模式
 * 根据 itemType 分发到对应的字段渲染器
 *
 * 老项目通过 amis 注册机制实现，新项目改为 React 组件注册表
 */
import type { FieldRendererEntry, FieldRendererProps } from './fieldInterface'

/** 字段渲染器注册表 */
const rendererRegistry = new Map<number, React.ComponentType<FieldRendererProps>>()

/** 注册字段渲染器 */
export function registerFieldRenderer(entry: FieldRendererEntry): void {
  entry.itemTypes.forEach(type => {
    rendererRegistry.set(type, entry.component)
  })
}

/** 获取字段渲染器 */
export function getFieldRenderer(itemType: number): React.ComponentType<FieldRendererProps> | undefined {
  return rendererRegistry.get(itemType)
}

/** 获取所有已注册的 itemType */
export function getRegisteredItemTypes(): number[] {
  return Array.from(rendererRegistry.keys())
}
