/**
 * SkillChangeLogView — 技能变更日志查看组件
 *
 * 展示技能的修改历史，支持：
 * - 查看每次变更的操作类型、版本路径、变更说明
 * - 区分正常更新和回滚操作
 * - 查看变更详情（修改了哪些字段）
 * - 作为回滚决策的参考
 *
 * 入口：
 * - 技能详情页的"变更日志"Tab
 * - 路由: /admin/skills/list/:apiKey/change-logs
 */
import React, { useEffect, useState } from 'react';
import {
  Timeline, Card, Tag, Typography, Spin, Alert, Space, Button,
  Tooltip, Empty, Pagination,
} from 'antd';
import {
  HistoryOutlined, RollbackOutlined, PlusCircleOutlined,
  SwapOutlined, DeleteOutlined, InfoCircleOutlined,
} from '@ant-design/icons';

const { Text, Paragraph } = Typography;

interface ChangeLogItem {
  id: number;
  action: string;
  from_version: string;
  to_version: string;
  changelog: string;
  change_summary: string;
  change_detail: Record<string, any>;
  analysis_report: string;
  trigger_source: string;
  thread_id: string;
  operator_id: number;
  rollback: boolean;
  rollback_from_log: number | null;
  created_at: number;
}

interface SkillChangeLogViewProps {
  apiKey: string;
}

const ACTION_CONFIG: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  create_version: { label: '创建版本', color: 'green', icon: <PlusCircleOutlined /> },
  switch_version: { label: '切换版本', color: 'orange', icon: <SwapOutlined /> },
  delete_version: { label: '删除版本', color: 'red', icon: <DeleteOutlined /> },
  create: { label: '创建技能', color: 'blue', icon: <PlusCircleOutlined /> },
  delete: { label: '删除技能', color: 'red', icon: <DeleteOutlined /> },
};

const TRIGGER_LABELS: Record<string, string> = {
  chat: '对话触发',
  api: 'API 调用',
  auto: '自动优化',
};

function formatTime(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  });
}

export default function SkillChangeLogView({ apiKey }: SkillChangeLogViewProps) {
  const [items, setItems] = useState<ChangeLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const pageSize = 15;

  useEffect(() => {
    setLoading(true);
    fetch(`/api/skills/${apiKey}/change-logs?tenant_id=0&page=${page}&page_size=${pageSize}`)
      .then(r => {
        if (!r.ok) throw new Error(`请求失败: ${r.statusText}`);
        return r.json();
      })
      .then(data => {
        setItems(data.items || []);
        setTotal(data.total || 0);
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [apiKey, page]);

  if (loading) return <Spin tip="加载变更日志..." style={{ display: 'block', margin: '40px auto' }} />;
  if (error) return <Alert type="error" message={error} />;
  if (items.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="暂无变更记录"
      />
    );
  }

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space>
          <HistoryOutlined />
          <Text strong>变更日志</Text>
          <Text type="secondary">共 {total} 条记录</Text>
        </Space>
      </div>

      <Timeline
        items={items.map(item => {
          const config = ACTION_CONFIG[item.action] || { label: item.action, color: 'default', icon: <InfoCircleOutlined /> };
          const isRollback = item.rollback;

          return {
            color: isRollback ? 'orange' : (config.color as any),
            dot: isRollback ? <RollbackOutlined style={{ fontSize: 16 }} /> : config.icon,
            children: (
              <Card
                size="small"
                style={{ marginBottom: 8 }}
                bodyStyle={{ padding: '12px 16px' }}
              >
                {/* 头部：时间 + 操作类型 + 版本路径 */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <Space size={8}>
                    <Tag color={config.color}>{config.label}</Tag>
                    {isRollback && <Tag color="orange" icon={<RollbackOutlined />}>回滚</Tag>}
                    {item.from_version && item.to_version && (
                      <Text code style={{ fontSize: 12 }}>
                        v{item.from_version} → v{item.to_version}
                      </Text>
                    )}
                  </Space>
                  <Space size={8}>
                    <Tag style={{ fontSize: 11 }}>{TRIGGER_LABELS[item.trigger_source] || item.trigger_source}</Tag>
                    <Text type="secondary" style={{ fontSize: 12 }}>{formatTime(item.created_at)}</Text>
                  </Space>
                </div>

                {/* 变更说明 */}
                {item.changelog && (
                  <Paragraph style={{ margin: '4px 0', fontSize: 13 }}>
                    {item.changelog}
                  </Paragraph>
                )}

                {/* 变更摘要 */}
                {item.change_summary && (
                  <div style={{ marginTop: 4 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      📋 {item.change_summary}
                    </Text>
                  </div>
                )}

                {/* 变更详情（修改的字段列表） */}
                {item.change_detail?.changed_fields && item.change_detail.changed_fields.length > 0 && (
                  <div style={{ marginTop: 8 }}>
                    <Space size={4} wrap>
                      <Text type="secondary" style={{ fontSize: 12 }}>修改字段:</Text>
                      {item.change_detail.changed_fields.map((f: string) => (
                        <Tag key={f} style={{ fontSize: 11 }}>{f}</Tag>
                      ))}
                    </Space>
                  </div>
                )}

                {/* 分析报告摘要（如有） */}
                {item.analysis_report && (
                  <div style={{ marginTop: 8, padding: '8px 12px', background: '#f6f8fa', borderRadius: 4 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      🔍 分析报告: {item.analysis_report.slice(0, 200)}
                      {item.analysis_report.length > 200 && '...'}
                    </Text>
                  </div>
                )}
              </Card>
            ),
          };
        })}
      />

      {total > pageSize && (
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Pagination
            current={page}
            total={total}
            pageSize={pageSize}
            onChange={setPage}
            showTotal={t => `共 ${t} 条`}
            size="small"
          />
        </div>
      )}
    </div>
  );
}
