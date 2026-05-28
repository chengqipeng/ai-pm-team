/**
 * InterruptSkillRenderer — 中断渲染路由（Skill 相关）
 *
 * 在 Chat 组件的 InterruptRenderer 中注册，当 interrupt_type="skill_confirm" 时
 * 路由到 SkillConfirmCard 组件。
 *
 * 集成方式：
 * 在主 Chat 组件的 InterruptRenderer 中添加：
 *
 * ```tsx
 * import { isSkillInterrupt, InterruptSkillRenderer } from '@/pages/skills/chat';
 *
 * function InterruptRenderer({ data, onResume, disabled }) {
 *   if (isSkillInterrupt(data)) {
 *     return <InterruptSkillRenderer data={data} onResume={onResume} disabled={disabled} />;
 *   }
 *   // ... 其他 interrupt 类型
 * }
 * ```
 */
import React from 'react';
import SkillConfirmCard from './SkillConfirmCard';
import type { SkillInterruptData, SkillResumePayload } from './types';

interface InterruptData {
  interrupt_id: string;
  type: string;
  title: string;
  message: string;
  options: Array<{ id: string; label: string; description: string }>;
  default_value?: string;
}

interface InterruptSkillRendererProps {
  data: InterruptData;
  onResume: (value: any) => void;
  disabled?: boolean;
}

/**
 * 判断中断数据是否为 Skill 确认类型
 */
export function isSkillInterrupt(data: InterruptData): boolean {
  return data.type === 'skill_confirm';
}

/**
 * Skill 中断渲染器
 *
 * 将通用的 InterruptData 转为 SkillInterruptData 并渲染 SkillConfirmCard。
 */
export default function InterruptSkillRenderer({
  data,
  onResume,
  disabled,
}: InterruptSkillRendererProps) {
  const skillData: SkillInterruptData = {
    interrupt_id: data.interrupt_id,
    type: 'skill_confirm',
    title: data.title,
    message: data.message,
    options: data.options,
    default_value: data.default_value,
  };

  const handleResume = (value: SkillResumePayload) => {
    // 将 SkillResumePayload 转为 ask_user 期望的 resume 格式
    onResume(value);
  };

  return (
    <SkillConfirmCard
      data={skillData}
      onResume={handleResume}
      disabled={disabled}
    />
  );
}
