/**
 * 技能列表页
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  Card, Table, Button, Input, Space, Tag, Switch, Modal,
  message, Popconfirm, Select, Row, Col, Statistic, Segmented,
} from 'antd';
import {
  PlusOutlined, SearchOutlined, CopyOutlined, DeleteOutlined,
  EditOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import type { Skill, SkillStats, SkillCategory } from './types';
import { skillApi } from './api';

const CATEGORY_OPTIONS = [
  { label: '全部', value: '' },
  { label: 'CRM 业务', value: 'crm' },
  { label: '元数据', value: 'metarepo' },
  { label: '数据分析', value: 'analysis' },
  { label: '自动化', value: 'automation' },
  { label: '自定义', value: 'custom' },
];

const RISK_COLORS: Record<string, string> = {
  read_only: 'green',
  mutating: 'orange',
  destructive: 'red',
};

const RISK_LABELS: Record<string, string> = {
  read_only: '只读',
  mutating: '可变更',
  destructive: '危险',
};

interface SkillListProps {
  onEdit: (apiKey: string) => void;
  onCreate: () => void;
}

export const SkillList: React.FC<SkillListProps> = ({ onEdit, onCreate }) => {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState<SkillStats | null>(null);
  const [keyword, setKeyword] = useState('');
  const [category, setCategory] = useState<string>('');
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);

  const fetchSkills = useCallback(async () => {
    setLoading(true);
    try {
      const res = await skillApi.list({
        keyword: keyword || undefined,
        category: category || undefined,
        page,
        page_size: pageSize,
      });
      setSkills(res.items);
      setTotal(res.total);
    } catch (e: any) {
      message.error(`加载失败: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [keyword, category, page, pageSize]);

  const fetchStats = useCallback(async () => {
    try {
      const s = await skillApi.stats();
      setStats(s);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    fetchSkills();
    fetchStats();
  }, [fetchSkills, fetchStats]);

  const handleToggle = async (record: Skill, enabled: boolean) => {
    try {
      await skillApi.toggle(record.api_key, { enabled });
      message.success(`技能已${enabled ? '启用' : '禁用'}`);
      fetchSkills();
      fetchStats();
    } catch (e: any) {
      message.error(e.message);
    }
  };

  const handleDelete = async (apiKey: string) => {
    try {
      await skillApi.delete(apiKey);
      message.success('技能已删除');
      fetchSkills();
      fetchStats();
    } catch (e: any) {
      message.error(e.message);
    }
  };

  const handleClone = async (apiKey: string) => {
    const newKey = `${apiKey}_copy`;
    try {
      await skillApi.clone(apiKey, { new_api_key: newKey });
      message.success(`已克隆为 ${newKey}`);
      fetchSkills();
    } catch (e: any) {
      message.error(e.message);
    }
  };

  const columns = [
    {
      title: '技能',
      dataIndex: 'name',
      key: 'name',
      render: (_: string, record: Skill) => (
        <div>
          <div style={{ fontWeight: 500 }}>{record.name}</div>
          <div style={{ fontSize: 12, color: '#666' }}>{record.api_key}</div>
        </div>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      width: 300,
    },
    {
      title: '模式',
      dataIndex: 'context',
      key: 'context',
      width: 80,
      render: (ctx: string) => (
        <Tag color={ctx === 'inline' ? 'blue' : 'purple'}>{ctx}</Tag>
      ),
    },
    {
      title: '风险',
      dataIndex: 'risk_level',
      key: 'risk_level',
      width: 80,
      render: (level: string) => (
        <Tag color={RISK_COLORS[level]}>{RISK_LABELS[level] || level}</Tag>
      ),
    },
    {
      title: '执行统计',
      key: 'stats',
      width: 150,
      render: (_: any, record: Skill) => {
        const rate = record.exec_count > 0
          ? Math.round((record.success_count / record.exec_count) * 100)
          : 0;
        return (
          <div style={{ fontSize: 12 }}>
            <div>执行 {record.exec_count} 次</div>
            <div>成功率 {rate}%</div>
          </div>
        );
      },
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 80,
      render: (enabled: boolean, record: Skill) => (
        <Switch
          checked={enabled}
          onChange={(checked) => handleToggle(record, checked)}
          checkedChildren="启用"
          unCheckedChildren="禁用"
        />
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      render: (_: any, record: Skill) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => onEdit(record.api_key)}
          />
          <Button
            type="link"
            size="small"
            icon={<CopyOutlined />}
            onClick={() => handleClone(record.api_key)}
          />
          <Popconfirm
            title="确定删除此技能？"
            onConfirm={() => handleDelete(record.api_key)}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      {/* 统计卡片 */}
      {stats && (
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col span={6}>
            <Card size="small">
              <Statistic title="技能总数" value={stats.total_skills} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="已启用" value={stats.enabled_count} valueStyle={{ color: '#52c41a' }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="总执行次数" value={stats.total_executions} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic
                title="成功率"
                value={Math.round(stats.success_rate * 100)}
                suffix="%"
                valueStyle={{ color: stats.success_rate > 0.8 ? '#52c41a' : '#faad14' }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* 筛选栏 */}
      <Card style={{ marginBottom: 16 }}>
        <Row justify="space-between" align="middle">
          <Col>
            <Space>
              <Segmented
                options={CATEGORY_OPTIONS}
                value={category}
                onChange={(val) => { setCategory(val as string); setPage(1); }}
              />
            </Space>
          </Col>
          <Col>
            <Space>
              <Input
                placeholder="搜索技能..."
                prefix={<SearchOutlined />}
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onPressEnter={() => { setPage(1); fetchSkills(); }}
                allowClear
                style={{ width: 240 }}
              />
              <Button type="primary" icon={<PlusOutlined />} onClick={onCreate}>
                创建技能
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      {/* 列表 */}
      <Card>
        <Table
          dataSource={skills}
          columns={columns}
          rowKey="api_key"
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total,
            onChange: setPage,
            showTotal: (t) => `共 ${t} 条`,
          }}
        />
      </Card>
    </div>
  );
};
