/**
 * NeoEntityDetail — 实体详情外壳组件
 *
 * 对齐老项目 neoCmps 的外壳组件模式
 * 封装完整的实体详情功能：自动加载字段 + 数据 + 渲染详情面板
 */
import { useState, useEffect } from 'react'
import DetailPanel from '../../baseBusinessElement/DetailPanel'
import type { FieldMeta, DataRecord } from '../../types'

export interface NeoEntityDetailProps {
  entityApiKey: string
  recordId: number | string
  onEdit?: () => void
  onDelete?: () => void
  onBack?: () => void
  fetchRecord?: (entityApiKey: string, recordId: number | string) => Promise<DataRecord>
  fetchFields?: (entityApiKey: string) => Promise<FieldMeta[]>
  className?: string
}

export default function NeoEntityDetail({
  entityApiKey, recordId, onEdit, onDelete, onBack,
  fetchRecord: customFetchRecord, fetchFields: customFetchFields, className,
}: NeoEntityDetailProps) {
  const [fields, setFields] = useState<FieldMeta[]>([])
  const [record, setRecord] = useState<DataRecord | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = customFetchFields || (async () => [])
    load(entityApiKey).then(setFields).catch(() => setFields([]))
  }, [entityApiKey])

  useEffect(() => {
    setLoading(true)
    const load = customFetchRecord || (async () => null as any)
    load(entityApiKey, recordId)
      .then(setRecord)
      .catch(() => setRecord(null))
      .finally(() => setLoading(false))
  }, [entityApiKey, recordId])

  if (loading) return <div className="flex items-center justify-center h-64 text-gray-400">加载中...</div>
  if (!record) return <div className="flex items-center justify-center h-64 text-gray-400">记录不存在</div>

  return (
    <div className={className}>
      {onBack && (
        <button onClick={onBack} className="text-sm text-blue-600 hover:text-blue-700 mb-4">← 返回列表</button>
      )}
      <DetailPanel record={record} fields={fields} onEdit={onEdit} onDelete={onDelete} />
    </div>
  )
}
