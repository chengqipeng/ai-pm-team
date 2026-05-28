/**
 * SkillPromptStarters — 创建技能的快捷提示词入口
 *
 * 两种使用场景：
 * 1. WelcomeScreen 中作为快捷卡片之一（新对话首屏）
 * 2. InputBox 上方作为快捷操作按钮（对话进行中）
 *
 * 集成方式：
 *
 * ```tsx
 * // 场景 1: WelcomeScreen 中
 * import { SkillPromptStarters } from '@/pages/skills/chat';
 *
 * function WelcomeScreen({ onSend }) {
 *   return (
 *     <div className="welcome-grid">
 *       <SkillPromptStarters onSelect={onSend} variant="card" />
 *       {/* 其他快捷卡片 *\/}
 *     </div>
 *   );
 * }
 *
 * // 场景 2: InputBox 上方
 * import { SkillPromptStarters } from '@/pages/skills/chat';
 *
 * function InputBox({ onSend }) {
 *   return (
 *     <>
 *       <SkillPromptStarters onSelect={onSend} variant="chip" />
 *       <textarea ... />
 *     </>
 *   );
 * }
 * ```
 */
import React from 'react';
import { Card, Tag, Space, Typography } from 'antd';
import { PlusCircleOutlined, ThunderboltOutlined } from '@ant-design/icons';

const { Text } = Typography;

/** 预置的创建技能提示词模板 */
export const SKILL_PROMPT_STARTERS = [
  {
    id: 'create_skill_general',
    icon: <PlusCircleOutlined style={{ color: '#1890ff' }} />,
    title: '创建技能',
    description: '通过对话创建一个可复用的 Agent 技能',
    prompt: '帮我创建一个技能',
  },
  {
    id: 'create_skill_analysis',
    icon: <ThunderboltOutlined style={{ color: '#722ed1' }} />,
    title: '创建分析技能',
    description: '创建一个数据分析类的技能',
    prompt: '帮我创建一个数据分析技能，分析客户的商机健康度',
  },
  {
    id: 'create_skill_query',
    icon: <ThunderboltOutlined style={{ color: '#13c2c2' }} />,
    title: '创建查询技能',
    description: '创建一个业务数据查询类的技能',
    prompt: '帮我创建一个技能，查询指定客户的所有联系人并按职位分类',
  },
] as const;

interface SkillPromptStartersProps {
  /** 用户选择某个提示词后的回调（将 prompt 发送到对话） */
  onSelect: (prompt: string) => void;
  /** 展示样式：card=卡片（WelcomeScreen 用）, chip=胶囊按钮（InputBox 用） */
  variant?: 'card' | 'chip';
  /** 是否只显示第一个（用于空间有限的场景） */
  compact?: boolean;
}

export default function SkillPromptStarters({
  onSelect,
  variant = 'chip',
  compact = false,
}: SkillPromptStartersProps) {
  const items = compact ? SKILL_PROMPT_STARTERS.slice(0, 1) : SKILL_PROMPT_STARTERS;

  // ── 卡片模式（WelcomeScreen 2×2 网格中的一格）──
  if (variant === 'card') {
    return (
      <>
        {items.map(item => (
          <Card
            key={item.id}
            size="small"
            hoverable
            onClick={() => onSelect(item.prompt)}
            style={{
              cursor: 'pointer',
              borderRadius: 12,
              border: '1px solid #f0f0f0',
              transition: 'all 0.2s',
            }}
            bodyStyle={{ padding: '16px' }}
          >
            <Space direction="vertical" size={4}>
              <Space>
                {item.icon}
                <Text strong style={{ fontSize: 14 }}>{item.title}</Text>
              </Space>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {item.description}
              </Text>
            </Space>
          </Card>
        ))}
      </>
    );
  }

  // ── 胶囊按钮模式（InputBox 上方）──
  return (
    <Space size={8} wrap style={{ marginBottom: 8 }}>
      {items.map(item => (
        <Tag
          key={item.id}
          onClick={() => onSelect(item.prompt)}
          style={{
            cursor: 'pointer',
            borderRadius: 16,
            padding: '4px 12px',
            fontSize: 12,
            background: '#f5f5f5',
            border: '1px solid #e8e8e8',
            transition: 'all 0.2s',
          }}
          // hover 效果通过 CSS 类实现
          className="skill-prompt-chip"
        >
          {item.icon}
          <span style={{ marginLeft: 4 }}>{item.title}</span>
        </Tag>
      ))}
    </Space>
  );
}
