/**
 * SkillSuggestionBubble — "要不要保存为技能？"建议气泡
 *
 * 当 Agent 完成复杂任务后（5+ 工具调用），主动建议用户保存为技能。
 * 通过 CUSTOM 事件 (type="skill_suggestion") 触发渲染。
 */
import React, { useState } from 'react';
import { Card, Button, Space, Typography } from 'antd';
import { BulbOutlined, CheckOutlined, CloseOutlined } from '@ant-design/icons';

const { Text } = Typography;

interface SkillSuggestionBubbleProps {
  /** 建议的技能名称 */
  suggestedName: string;
  /** 建议的技能描述 */
  suggestedDescription: string;
  /** 用户点击"保存为技能"后的回调（发送消息给 Agent） */
  onAccept: (name: string) => void;
  /** 用户点击"不需要"后的回调 */
  onDismiss: () => void;
}

export default function SkillSuggestionBubble({
  suggestedName,
  suggestedDescription,
  onAccept,
  onDismiss,
}: SkillSuggestionBubbleProps) {
  const [dismissed, setDismissed] = useState(false);
  const [accepted, setAccepted] = useState(false);

  if (dismissed) return null;

  if (accepted) {
    return (
      <Card
        size="small"
        style={{ maxWidth: 400, margin: '8px 0', opacity: 0.7 }}
        bodyStyle={{ padding: '8px 12px' }}
      >
        <Space>
          <CheckOutlined style={{ color: '#52c41a' }} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            正在创建技能「{suggestedName}」...
          </Text>
        </Space>
      </Card>
    );
  }

  return (
    <Card
      size="small"
      style={{
        maxWidth: 440,
        margin: '8px 0',
        borderColor: '#ffe58f',
        background: '#fffbe6',
      }}
      bodyStyle={{ padding: '10px 14px' }}
    >
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <Space>
          <BulbOutlined style={{ color: '#faad14', fontSize: 14 }} />
          <Text style={{ fontSize: 13 }}>
            这个分析流程比较常用，要不要保存为技能？
          </Text>
        </Space>

        <div style={{ paddingLeft: 22 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            「{suggestedName}」— {suggestedDescription}
          </Text>
        </div>

        <Space style={{ paddingLeft: 22 }}>
          <Button
            size="small"
            type="primary"
            icon={<CheckOutlined />}
            onClick={() => {
              setAccepted(true);
              onAccept(suggestedName);
            }}
          >
            保存为技能
          </Button>
          <Button
            size="small"
            icon={<CloseOutlined />}
            onClick={() => {
              setDismissed(true);
              onDismiss();
            }}
          >
            不需要
          </Button>
        </Space>
      </Space>
    </Card>
  );
}
