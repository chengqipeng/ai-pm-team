/**
 * SkillDetailView — 技能详情只读查看页
 *
 * 用于 system_flg=1 的系统预置技能（如 create_skill），只能查看不能编辑。
 * 普通技能也可以用此组件查看完整定义。
 *
 * 入口：
 * - 技能列表页点击系统技能的"查看"按钮
 * - 路由: /admin/skills/list/:apiKey (当 skill.system=true 时渲染此组件)
 */
import React, { useEffect, useState } from 'react';
import {
  Card, Typography, Tag, Space, Descriptions, Collapse, Spin, Alert, Badge, Divider,
} from 'antd';
import {
  LockOutlined, CodeOutlined, FileTextOutlined,
  ClockCircleOutlined, ThunderboltOutlined, SafetyOutlined,
} from '@ant-design/icons';

const { Title, Text, Paragraph } = Typography;

interface SkillDetail {
  api_key: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  icon: string;
  version: string;
  enabled: boolean;
  system: boolean;
  readonly: boolean;
  owner: string;
  when_to_use: string;
  context: string;
  agent: string;
  model: string;
  allowed_tools: string[];
  arguments: string[];
  argument_descriptions: Record<string, string>;
  prompt: string;
  requires_confirmation: boolean;
  max_tool_calls: number;
  timeout_ms: number;
  output_mode: string;
  post_output_behavior: string;
  exec_count: number;
  success_count: number;
  avg_duration_ms: number;
  ext_info: Record<string, any>;
  created_at: number;
  updated_at: number;
}

interface SkillDetailViewProps {
  apiKey: string;
  onBack?: () => void;
}

async function fetchSkillDetail(apiKey: string): Promise<SkillDetail> {
  const resp = await fetch(`/api/skills/${apiKey}?tenant_id=0`);
  if (!resp.ok) throw new Error(`获取技能详情失败: ${resp.statusText}`);
  return resp.json();
}

export default function SkillDetailView({ apiKey, onBack }: SkillDetailViewProps) {
  const [skill, setSkill] = useState<SkillDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    fetchSkillDetail(apiKey)
      .then(setSkill)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [apiKey]);

  if (loading) return <Spin tip="加载中..." style={{ display: 'block', margin: '40px auto' }} />;
  if (error) return <Alert type="error" message={error} />;
  if (!skill) return <Alert type="warning" message="技能不存在" />;

  const successRate = skill.exec_count > 0
    ? Math.round((skill.success_count / skill.exec_count) * 100)
    : 0;

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '24px 0' }}>
      {/* 标题栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Space>
          <span style={{ fontSize: 24 }}>{skill.icon || '📋'}</span>
          <Title level={4} style={{ margin: 0 }}>{skill.name}</Title>
          <Tag>{skill.version}</Tag>
          {skill.system && (
            <Tag icon={<LockOutlined />} color="gold">系统预置 · 只读</Tag>
          )}
          {skill.enabled ? (
            <Badge status="success" text="启用" />
          ) : (
            <Badge status="default" text="禁用" />
          )}
        </Space>
        {onBack && (
          <a onClick={onBack} style={{ cursor: 'pointer' }}>← 返回列表</a>
        )}
      </div>

      {/* 系统预置提示 */}
      {skill.system && (
        <Alert
          type="info"
          showIcon
          icon={<LockOutlined />}
          message="系统预置技能，不可编辑或删除"
          description="此技能由平台预置，保证所有租户的一致性。如需自定义类似技能，请使用"克隆"功能。"
          style={{ marginBottom: 16 }}
        />
      )}

      {/* 基本信息 */}
      <Card title="基本信息" size="small" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small">
          <Descriptions.Item label="API Key">
            <Text code>{skill.api_key}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="分类">
            <Tag>{skill.category}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="描述" span={2}>
            {skill.description}
          </Descriptions.Item>
          <Descriptions.Item label="触发关键词" span={2}>
            {skill.when_to_use ? (
              skill.when_to_use.split('|').map(kw => (
                <Tag key={kw} style={{ marginBottom: 4 }}>{kw.trim()}</Tag>
              ))
            ) : (
              <Text type="secondary">无</Text>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="归属">{skill.owner || '-'}</Descriptions.Item>
          <Descriptions.Item label="标签">
            {skill.tags.map(t => <Tag key={t}>{t}</Tag>)}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 执行配置 */}
      <Card title="执行配置" size="small" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small">
          <Descriptions.Item label="执行模式">
            <Tag color={skill.context === 'fork' ? 'purple' : 'blue'}>{skill.context}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="子 Agent">
            {skill.agent || <Text type="secondary">无（使用默认）</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="指定模型">
            {skill.model || <Text type="secondary">继承主模型</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="风险等级">
            <Tag color={skill.requires_confirmation ? 'orange' : 'green'}>
              {skill.requires_confirmation ? '需确认' : '无需确认'}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="最大工具调用">
            {skill.max_tool_calls} 次
          </Descriptions.Item>
          <Descriptions.Item label="超时时间">
            {(skill.timeout_ms / 1000).toFixed(0)} 秒
          </Descriptions.Item>
          <Descriptions.Item label="输出模式">{skill.output_mode}</Descriptions.Item>
          <Descriptions.Item label="输出后行为">{skill.post_output_behavior}</Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 参数 */}
      {skill.arguments.length > 0 && (
        <Card title="参数列表" size="small" style={{ marginBottom: 16 }}>
          <table style={{ width: '100%', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #f0f0f0' }}>
                <th style={{ padding: '8px 12px', textAlign: 'left' }}>参数名</th>
                <th style={{ padding: '8px 12px', textAlign: 'left' }}>描述</th>
              </tr>
            </thead>
            <tbody>
              {skill.arguments.map(arg => (
                <tr key={arg} style={{ borderBottom: '1px solid #f0f0f0' }}>
                  <td style={{ padding: '8px 12px' }}><Text code>{arg}</Text></td>
                  <td style={{ padding: '8px 12px' }}>
                    {skill.argument_descriptions?.[arg] || <Text type="secondary">-</Text>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* 允许工具 */}
      <Card title="允许工具" size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          {skill.allowed_tools.map(tool => (
            <Tag key={tool} icon={<ThunderboltOutlined />}>{tool}</Tag>
          ))}
          {skill.allowed_tools.length === 0 && (
            <Text type="secondary">无限制（继承主 Agent 工具集）</Text>
          )}
        </Space>
      </Card>

      {/* Prompt 完整内容 */}
      <Card
        title={
          <Space>
            <FileTextOutlined />
            <span>Prompt 完整内容</span>
            <Text type="secondary" style={{ fontSize: 12 }}>
              ({skill.prompt.length.toLocaleString()} 字符)
            </Text>
          </Space>
        }
        size="small"
        style={{ marginBottom: 16 }}
      >
        <pre style={{
          background: '#fafafa',
          border: '1px solid #f0f0f0',
          borderRadius: 6,
          padding: 16,
          fontSize: 12,
          lineHeight: 1.6,
          maxHeight: 600,
          overflow: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          margin: 0,
        }}>
          {skill.prompt}
        </pre>
      </Card>

      {/* ext_info（如有 preload_resources 等配置） */}
      {skill.ext_info && Object.keys(skill.ext_info).length > 0 && (
        <Card title="扩展配置 (ext_info)" size="small" style={{ marginBottom: 16 }}>
          <pre style={{
            background: '#fafafa',
            border: '1px solid #f0f0f0',
            borderRadius: 6,
            padding: 12,
            fontSize: 11,
            maxHeight: 300,
            overflow: 'auto',
            margin: 0,
          }}>
            {JSON.stringify(skill.ext_info, null, 2)}
          </pre>
        </Card>
      )}

      {/* 执行统计 */}
      <Card title="执行统计" size="small">
        <Descriptions column={4} size="small">
          <Descriptions.Item label="执行次数">{skill.exec_count}</Descriptions.Item>
          <Descriptions.Item label="成功次数">{skill.success_count}</Descriptions.Item>
          <Descriptions.Item label="成功率">{successRate}%</Descriptions.Item>
          <Descriptions.Item label="平均耗时">{skill.avg_duration_ms}ms</Descriptions.Item>
        </Descriptions>
      </Card>
    </div>
  );
}
