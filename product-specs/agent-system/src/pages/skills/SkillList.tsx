/**
 * SkillList — 技能列表页
 *
 * 展示所有技能卡片，支持：
 * - 分类筛选 Tab
 * - 搜索
 * - 启用/禁用切换
 * - 操作按钮：编辑、克隆、删除、变更日志
 *
 * 路由: /admin/skills/list
 */
import React, { useEffect, useState } from 'react';
import {
  Card, Tag, Space, Button, Input, Badge, Switch, Popconfirm,
  Spin, Alert, Empty, Pagination, Modal, message, Typography, Tooltip,
} from 'antd';
import {
  PlusOutlined, EditOutlined, CopyOutlined, DeleteOutlined,
  SearchOutlined, HistoryOutlined, LockOutlined, EyeOutlined,
} from '@ant-design/icons';
import SkillChangeLogView from './SkillChangeLogView';
import SkillDetailView from './SkillDetailView';

const { Text } = Typography;

interface SkillItem {
  api_key: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  icon: string;
  version: string;
  enabled: boolean;
  system: boolean;
  exec_count: number;
  success_count: number;
  avg_duration_ms: number;
  updated_at: number;
}

interface CategoryItem {
  api_key: string;
  name: string;
  icon: string;
}

interface SkillListProps {
  onEdit?: (apiKey: string) => void;
  onCreate?: () => void;
}

export default function SkillList({ onEdit, onCreate }: SkillListProps) {
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [categories, setCategories] = useState<CategoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [activeCategory, setActiveCategory] = useState('all');
  const [changeLogModal, setChangeLogModal] = useState<{ open: boolean; apiKey: string; name: string }>({
    open: false, apiKey: '', name: '',
  });
  const [detailModal, setDetailModal] = useState<{ open: boolean; apiKey: string }>({
    open: false, apiKey: '',
  });

  const pageSize = 20;

  // 加载分类
  useEffect(() => {
    fetch('/api/skill-categories?tenant_id=0')
      .then(r => r.json())
      .then(data => setCategories(data.items || data || []))
      .catch(() => {});
  }, []);

  // 加载技能列表
  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams({
      tenant_id: '0',
      page: String(page),
      page_size: String(pageSize),
    });
    if (search) params.set('keyword', search);
    if (activeCategory !== 'all') params.set('category', activeCategory);

    fetch(`/api/skills?${params}`)
      .then(r => {
        if (!r.ok) throw new Error(`请求失败: ${r.statusText}`);
        return r.json();
      })
      .then(data => {
        setSkills(data.items || []);
        setTotal(data.total || 0);
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [page, search, activeCategory]);

  // 启用/禁用切换
  const handleToggle = async (apiKey: string, enabled: boolean) => {
    try {
      const resp = await fetch(`/api/skills/${apiKey}/toggle`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled, tenant_id: 0 }),
      });
      if (!resp.ok) throw new Error('操作失败');
      setSkills(prev => prev.map(s => s.api_key === apiKey ? { ...s, enabled } : s));
      message.success(enabled ? '已启用' : '已禁用');
    } catch {
      message.error('操作失败');
    }
  };

  // 克隆
  const handleClone = async (apiKey: string) => {
    try {
      const resp = await fetch(`/api/skills/${apiKey}/clone`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenant_id: 0 }),
      });
      if (!resp.ok) throw new Error('克隆失败');
      message.success('克隆成功');
      setPage(1); // 刷新列表
    } catch {
      message.error('克隆失败');
    }
  };

  // 删除
  const handleDelete = async (apiKey: string) => {
    try {
      const resp = await fetch(`/api/skills/${apiKey}?tenant_id=0`, { method: 'DELETE' });
      if (!resp.ok) throw new Error('删除失败');
      message.success('已删除');
      setSkills(prev => prev.filter(s => s.api_key !== apiKey));
    } catch {
      message.error('删除失败');
    }
  };

  // 打开变更日志弹框
  const openChangeLog = (apiKey: string, name: string) => {
    setChangeLogModal({ open: true, apiKey, name });
  };

  if (error) return <Alert type="error" message={error} />;

  return (
    <div>
      {/* 顶部操作栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Text strong style={{ fontSize: 18 }}>技能列表</Text>
        <Button type="primary" icon={<PlusOutlined />} onClick={onCreate}>
          创建技能
        </Button>
      </div>

      {/* 分类筛选 + 搜索 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Space size={8}>
          <Tag.CheckableTag
            checked={activeCategory === 'all'}
            onChange={() => { setActiveCategory('all'); setPage(1); }}
          >
            全部
          </Tag.CheckableTag>
          {categories.map(cat => (
            <Tag.CheckableTag
              key={cat.api_key}
              checked={activeCategory === cat.api_key}
              onChange={() => { setActiveCategory(cat.api_key); setPage(1); }}
            >
              {cat.icon} {cat.name}
            </Tag.CheckableTag>
          ))}
        </Space>
        <Input
          placeholder="搜索技能..."
          prefix={<SearchOutlined />}
          style={{ width: 220 }}
          allowClear
          value={search}
          onChange={e => { setSearch(e.target.value); setPage(1); }}
        />
      </div>

      {/* 技能卡片列表 */}
      {loading ? (
        <Spin tip="加载中..." style={{ display: 'block', margin: '40px auto' }} />
      ) : skills.length === 0 ? (
        <Empty description="暂无技能" />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {skills.map(skill => {
            const successRate = skill.exec_count > 0
              ? Math.round((skill.success_count / skill.exec_count) * 100)
              : 0;

            return (
              <Card
                key={skill.api_key}
                size="small"
                bodyStyle={{ padding: '12px 16px' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  {/* 左侧：名称 + 描述 */}
                  <div style={{ flex: 1 }}>
                    <Space size={8} style={{ marginBottom: 4 }}>
                      <span style={{ fontSize: 16 }}>{skill.icon || '📋'}</span>
                      <Text strong>{skill.name}</Text>
                      <Text code style={{ fontSize: 11 }}>{skill.api_key}</Text>
                      <Tag>{skill.version}</Tag>
                      {skill.system && (
                        <Tag icon={<LockOutlined />} color="gold" style={{ fontSize: 11 }}>系统</Tag>
                      )}
                    </Space>
                    <div style={{ marginTop: 4 }}>
                      <Text type="secondary" style={{ fontSize: 13 }}>
                        {skill.description}
                      </Text>
                    </div>
                    <Space size={12} style={{ marginTop: 8, fontSize: 12 }}>
                      <Tag>{skill.category}</Tag>
                      <Text type="secondary">执行 {skill.exec_count} 次</Text>
                      <Text type="secondary">成功率 {successRate}%</Text>
                    </Space>
                  </div>

                  {/* 右侧：操作按钮 */}
                  <Space size={8}>
                    <Switch
                      size="small"
                      checked={skill.enabled}
                      onChange={checked => handleToggle(skill.api_key, checked)}
                      disabled={skill.system}
                    />

                    {skill.system ? (
                      <Tooltip title="查看详情">
                        <Button
                          size="small"
                          icon={<EyeOutlined />}
                          onClick={() => setDetailModal({ open: true, apiKey: skill.api_key })}
                        />
                      </Tooltip>
                    ) : (
                      <Tooltip title="编辑">
                        <Button
                          size="small"
                          icon={<EditOutlined />}
                          onClick={() => onEdit?.(skill.api_key)}
                        />
                      </Tooltip>
                    )}

                    <Tooltip title="变更日志">
                      <Button
                        size="small"
                        icon={<HistoryOutlined />}
                        onClick={() => openChangeLog(skill.api_key, skill.name)}
                      />
                    </Tooltip>

                    <Tooltip title="克隆">
                      <Button
                        size="small"
                        icon={<CopyOutlined />}
                        onClick={() => handleClone(skill.api_key)}
                      />
                    </Tooltip>

                    {!skill.system && (
                      <Popconfirm
                        title="确定删除此技能？"
                        onConfirm={() => handleDelete(skill.api_key)}
                      >
                        <Tooltip title="删除">
                          <Button size="small" danger icon={<DeleteOutlined />} />
                        </Tooltip>
                      </Popconfirm>
                    )}
                  </Space>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* 分页 */}
      {total > pageSize && (
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Pagination
            current={page}
            total={total}
            pageSize={pageSize}
            onChange={setPage}
            showTotal={t => `共 ${t} 条`}
          />
        </div>
      )}

      {/* 变更日志弹框 */}
      <Modal
        title={
          <Space>
            <HistoryOutlined />
            <span>{changeLogModal.name} — 变更日志</span>
          </Space>
        }
        open={changeLogModal.open}
        onCancel={() => setChangeLogModal({ open: false, apiKey: '', name: '' })}
        footer={null}
        width={720}
        destroyOnClose
      >
        {changeLogModal.apiKey && (
          <SkillChangeLogView apiKey={changeLogModal.apiKey} />
        )}
      </Modal>

      {/* 系统技能详情弹框 */}
      <Modal
        open={detailModal.open}
        onCancel={() => setDetailModal({ open: false, apiKey: '' })}
        footer={null}
        width={960}
        destroyOnClose
      >
        {detailModal.apiKey && (
          <SkillDetailView
            apiKey={detailModal.apiKey}
            onBack={() => setDetailModal({ open: false, apiKey: '' })}
          />
        )}
      </Modal>
    </div>
  );
}
