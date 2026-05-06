import { Tag } from 'antd';

interface StatusTagProps {
  value?: number;
  enabledText?: string;
  disabledText?: string;
}

/** 通用启用/禁用状态标签（null/undefined 视为启用，与老系统 isActive 默认行为一致） */
export default function StatusTag({ value, enabledText = '启用', disabledText = '禁用' }: StatusTagProps) {
  return value === 0
    ? <Tag color="default">{disabledText}</Tag>
    : <Tag color="green">{enabledText}</Tag>;
}
