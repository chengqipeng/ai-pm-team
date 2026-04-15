import { Spin } from 'antd';

interface LoadingProps {
  tip?: string;
}

export default function Loading({ tip = '加载中...' }: LoadingProps) {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', padding: 64 }}>
      <Spin size="large" tip={tip}>
        <div style={{ padding: 50 }} />
      </Spin>
    </div>
  );
}
