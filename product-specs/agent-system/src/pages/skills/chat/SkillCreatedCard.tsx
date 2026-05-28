/**
 * SkillCreatedCard — 技能创建成功后的提示卡片
 *
 * 在 Agent 调用 manage_skill(create) 成功后，
 * 通过 CUSTOM 事件渲染此卡片，展示使用提示。
 */
import React from 'react';
import { Card, Space, Typography, Tag, Button } from 'antd';
import { CheckCircleFilled, MessageOutlined, SettingOutlined } from '@ant-design/icons';

const { Text, Paragraph } = Typography;

interface SkillCreatedCardProps {
  /** 技能 api_key */
  apiKey: string;
  /** 技能名称 */
  name: string;
  /** 触发关键词 */
  whenToUse?: string;
  /** 点击"管理页查看"的回调 */
  onNavigateToAdmin?: (apiKey: string) => void;
}

export default function SkillCreatedCard({
  apiKey,
  name,
  whenToUse,
  onNavigateToAdmin,
}: SkillCreatedCardProps) {
  // 从 when_to_use 中提取示例触发语句
  const triggerExamples = whenToUse
    ? whenToUse.split('|').slice(0, 3).map(kw => kw.trim())
    : [];

  return (
    <Card
      size="small"
      style={{
        maxWidth: 440,
        margin: '12px 0',
        borderColor: '#b7eb8f',
        background: '#f6ffed',
      }}
      bodyStyle={{ padding: '12px 16px' }}
    >
      {/* 标题行 */}
      <Space style={{ marginBottom: 8 }}>
        <CheckCircleFilled style={{ color: '#52c41a', fontSize: 18 }} />
        <Text strong style={{ fontSize: 14 }}>技能已创建</Text>
      </Space>

      {/* 技能信息 */}
      <div style={{ marginBottom: 12, paddingLeft: 26 }}>
        <div>
          <Text strong>{name}</Text>
          <Text code style={{ marginLeft: 8, fontSize: 11 }}>{apiKey}</Text>
        </div>
      </div>

      {/* 使用方式 */}
      {triggerExamples.length > 0 && (
        <div style={{ paddingLeft: 26, marginBottom: 12 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>使用方式：</Text>
          <div style={{ marginTop: 4 }}>
            {triggerExamples.map((example, idx) => (
              <div key={idx} style={{ marginBottom: 2 }}>
                <MessageOutlined style={{ color: '#1890ff', marginRight: 6, fontSize: 11 }} />
                <Text style={{ fontSize: 12 }}>"{example}..."</Text>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 操作按钮 */}
      <div style={{ paddingLeft: 26 }}>
        <Space size="small">
          {onNavigateToAdmin && (
            <Button
              size="small"
              type="link"
              icon={<SettingOutlined />}
              onClick={() => onNavigateToAdmin(apiKey)}
              style={{ padding: 0, fontSize: 12 }}
            >
              管理页查看
            </Button>
          )}
        </Space>
      </div>
    </Card>
  );
}
