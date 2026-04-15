import { Tag, Space, Typography } from 'antd';
import type { XPickOption } from '@/types/metamodel';

interface PickOptionTagProps {
  options: XPickOption[];
}

/** 选项值标签组 —— 展示字段的选项值列表 */
export default function PickOptionTag({ options }: PickOptionTagProps) {
  if (!options.length) return null;

  const sorted = [...options].sort((a, b) => (a.optionOrder ?? 0) - (b.optionOrder ?? 0));

  return (
    <div style={{ padding: '8px 0' }}>
      <Typography.Text type="secondary" style={{ marginRight: 8 }}>选项值:</Typography.Text>
      <Space size={4} wrap>
        {sorted.map((opt) => (
          <Tag
            key={opt.id}
            color={opt.defaultFlg === 1 ? 'blue' : undefined}
          >
            {opt.label ?? opt.apiKey}
            {opt.optionCode != null && ` (${opt.optionCode})`}
          </Tag>
        ))}
      </Space>
    </div>
  );
}
