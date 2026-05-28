/**
 * SkillConfirmCard — 对话式创建 Skill 的确认卡片
 *
 * 核心交互组件：
 * 1. Agent 生成技能定义后调用 ask_user(interrupt_type="skill_confirm")
 * 2. 前端渲染此卡片，展示技能预览
 * 3. 用户可以：确认创建 / 修改后确认 / 取消
 * 4. 用户操作后调用 onResume 恢复 Agent 执行
 * 5. Agent 收到确认后调用 manage_skill(create) 写入数据库
 *
 * 关键约束：只有用户点击"确认创建"后，Agent 才会执行实际的保存操作。
 */
import React, { useState, useMemo } from 'react';
import { Card, Tag, Button, Space, Divider, Typography, Result } from 'antd';
import {
  CheckOutlined, EditOutlined, CloseOutlined,
  CheckCircleFilled, FileTextOutlined,
} from '@ant-design/icons';
import SkillPreview from './SkillPreview';
import SkillInlineEditor from './SkillInlineEditor';
import type { SkillDefinition, SkillInterruptData, SkillResumePayload } from './types';

const { Text } = Typography;

interface SkillConfirmCardProps {
  /** interrupt() 传递的中断数据 */
  data: SkillInterruptData;
  /** 调用后端 resume 接口，恢复 Agent 执行 */
  onResume: (value: SkillResumePayload) => void;
  /** 是否已经 resume 过（防止重复提交） */
  disabled?: boolean;
}

type CardMode = 'preview' | 'edit';

export default function SkillConfirmCard({ data, onResume, disabled }: SkillConfirmCardProps) {
  // 从 interrupt_value 中解析技能定义
  const initialDefinition = useMemo<SkillDefinition>(() => {
    try {
      const raw = data.options?.[0]?.description;
      if (!raw) throw new Error('No definition in options');
      return JSON.parse(raw);
    } catch {
      // fallback: 空定义
      return {
        api_key: '',
        name: data.options?.[0]?.label || '未命名技能',
        description: '',
        when_to_use: '',
        category: 'custom',
        arguments: [],
        argument_descriptions: {},
        allowed_tools: [],
        risk_level: 'read_only' as const,
        max_tool_calls: 15,
        timeout_ms: 45000,
        prompt: '',
      };
    }
  }, [data]);

  const [mode, setMode] = useState<CardMode>('preview');
  const [definition, setDefinition] = useState<SkillDefinition>(initialDefinition);
  const [confirmed, setConfirmed] = useState(false);
  const [cancelled, setCancelled] = useState(false);

  // 确认创建
  const handleConfirm = () => {
    setConfirmed(true);
    onResume({ action: 'confirm', value: definition });
  };

  // 修改后保存（回到预览模式，不立即 resume）
  const handleEditorSave = (modified: SkillDefinition) => {
    setDefinition(modified);
    setMode('preview');
  };

  // 取消
  const handleCancel = () => {
    setCancelled(true);
    onResume({ cancelled: true });
  };

  // ── 已确认状态 ──
  if (confirmed) {
    return (
      <Card
        size="small"
        style={{ maxWidth: 480, margin: '12px 0', borderColor: '#b7eb8f' }}
        bodyStyle={{ padding: '12px 16px' }}
      >
        <Space>
          <CheckCircleFilled style={{ color: '#52c41a', fontSize: 16 }} />
          <Text>已确认创建技能</Text>
          <Text strong>{definition.name}</Text>
          <Text code style={{ fontSize: 11 }}>{definition.api_key}</Text>
        </Space>
      </Card>
    );
  }

  // ── 已取消状态 ──
  if (cancelled) {
    return (
      <Card
        size="small"
        style={{ maxWidth: 480, margin: '12px 0', opacity: 0.6 }}
        bodyStyle={{ padding: '12px 16px' }}
      >
        <Space>
          <CloseOutlined style={{ color: '#999' }} />
          <Text type="secondary">已取消创建技能</Text>
        </Space>
      </Card>
    );
  }

  // ── 解析失败 ──
  if (!definition.api_key && !definition.prompt) {
    return (
      <Card size="small" style={{ maxWidth: 480, margin: '12px 0' }}>
        <Result
          status="warning"
          title="技能定义解析失败"
          subTitle="Agent 生成的定义格式有误，请重新描述需求"
        />
      </Card>
    );
  }

  // ── 正常交互状态 ──
  return (
    <Card
      size="small"
      title={
        <Space>
          <FileTextOutlined />
          <span>{definition.name}</span>
        </Space>
      }
      extra={
        <Tag color="blue">{definition.category || 'custom'}</Tag>
      }
      style={{ maxWidth: 560, margin: '12px 0' }}
      bodyStyle={{ padding: '16px' }}
    >
      {/* 预览 / 编辑 切换 */}
      {mode === 'preview' ? (
        <SkillPreview definition={definition} />
      ) : (
        <SkillInlineEditor
          definition={definition}
          onSave={handleEditorSave}
          onCancel={() => setMode('preview')}
        />
      )}

      {/* 操作按钮（仅预览模式显示） */}
      {mode === 'preview' && (
        <>
          <Divider style={{ margin: '12px 0' }} />
          <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
            <Button
              icon={<CloseOutlined />}
              onClick={handleCancel}
              disabled={disabled}
            >
              取消
            </Button>
            <Button
              icon={<EditOutlined />}
              onClick={() => setMode('edit')}
              disabled={disabled}
            >
              修改
            </Button>
            <Button
              type="primary"
              icon={<CheckOutlined />}
              onClick={handleConfirm}
              disabled={disabled}
            >
              确认创建
            </Button>
          </Space>
        </>
      )}
    </Card>
  );
}
