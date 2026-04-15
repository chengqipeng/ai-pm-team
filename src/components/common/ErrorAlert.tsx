import { Alert, Button } from 'antd';

interface ErrorAlertProps {
  message: string;
  onRetry?: () => void;
}

export default function ErrorAlert({ message, onRetry }: ErrorAlertProps) {
  return (
    <Alert
      type="error"
      showIcon
      message="请求失败"
      description={message}
      action={onRetry ? <Button size="small" onClick={onRetry}>重试</Button> : undefined}
      style={{ margin: 16 }}
    />
  );
}
