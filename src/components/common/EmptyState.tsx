import { Empty } from 'antd';

interface EmptyStateProps {
  description?: string;
}

export default function EmptyState({ description = '暂无数据' }: EmptyStateProps) {
  return <Empty description={description} style={{ padding: 64 }} />;
}
