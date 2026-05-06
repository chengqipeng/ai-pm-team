import { Tag, Tooltip } from 'antd';

interface CustomTagProps {
  customFlg?: number;
  namespace?: string;
}

/**
 * 来源标签 —— 根据 namespace + customFlg 区分
 *
 * | namespace | customFlg | 含义                     | 标签           |
 * |-----------|-----------|--------------------------|----------------|
 * | system    | 0         | 系统出厂标准             | 标准           |
 * | product   | 0         | 产品预置                 | 产品           |
 * | tenant    | 1         | 租户自定义               | 自定义         |
 * | system    | 1         | 标准字段的租户覆盖       | 标准(已修改)   |
 * | 其他      | —         | 兼容旧逻辑               | 标准/自定义    |
 */
export default function CustomTag({ customFlg, namespace }: CustomTagProps) {
  // 有 namespace 时用精确区分
  if (namespace) {
    if (namespace === 'tenant' && customFlg === 1) {
      return <Tag color="blue">自定义</Tag>;
    }
    if (namespace === 'system' && customFlg === 1) {
      return (
        <Tooltip title="系统标准字段，租户已修改">
          <Tag color="geekblue">标准(已修改)</Tag>
        </Tooltip>
      );
    }
    if (namespace === 'product') {
      return <Tag color="cyan">产品</Tag>;
    }
    if (namespace === 'system') {
      return <Tag color="orange">标准</Tag>;
    }
    if (namespace === 'tenant') {
      return <Tag color="blue">自定义</Tag>;
    }
  }

  // 兼容：无 namespace 时按 customFlg 判断
  return customFlg === 1
    ? <Tag color="blue">自定义</Tag>
    : <Tag color="orange">标准</Tag>;
}
