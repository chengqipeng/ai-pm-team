/**
 * SkillPreview — 技能定义只读预览
 *
 * 在 SkillConfirmCard 中展示 Agent 生成的技能定义摘要。
 * 包含：描述、api_key、参数、工具、配置、Prompt（折叠）。
 */
import React from 'react';
import { Typography, Tag, Space, Collapse } from 'antd';
import type { SkillDefinition } from './types';
import { RISK_LEVEL_OPTIONS } from './types';

const { Text, Paragraph } = Typography;

interface SkillPreviewProps {
  definition: SkillDefinition;
}

function getRiskColor(level: string): string {
  const found = RISK_LEVEL_OPTIONS.find(o => o.value === level);
  return found?.color ?? 'default';
}

export default function SkillPreview({ definition }: SkillPreviewProps) {
  return (
    <div className="skill-preview">
      {/* 描述 */}
      <Paragraph type="secondary" style={{ marginBottom: 12 }}>
        {definition.description}
      </Paragraph>

      {/* api_key */}
      <div style={{ marginBottom: 12 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>标识: </Text>
        <Text code>{definition.api_key}</Text>
      </div>

      {/* 参数 */}
      {definition.arguments.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <Text strong style={{ fontSize: 13 }}>📥 输入参数</Text>
          <ul style={{ margin: '4px 0 0', paddingLeft: 20, listStyle: 'disc' }}>
            {definition.arguments.map(arg => (
              <li key={arg} style={{ fontSize: 13, marginBottom: 2 }}>
                <code style={{ fontSize: 12 }}>{arg}</code>
                {definition.argument_descriptions?.[arg] && (
                  <Text type="secondary"> — {definition.argument_descriptions[arg]}</Text>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 使用工具 */}
      <div style={{ marginBottom: 12 }}>
        <Text strong style={{ fontSize: 13 }}>🔧 使用工具</Text>
        <div style={{ marginTop: 4 }}>
          {definition.allowed_tools.map(tool => (
            <Tag key={tool} style={{ marginBottom: 4 }}>{tool}</Tag>
          ))}
          {definition.allowed_tools.length === 0 && (
            <Text type="secondary" style={{ fontSize: 12 }}>无限制</Text>
          )}
        </div>
      </div>

      {/* 配置摘要 */}
      <div style={{ marginBottom: 12 }}>
        <Text strong style={{ fontSize: 13 }}>⚙️ 配置</Text>
        <div style={{ marginTop: 4 }}>
          <Space size="middle" wrap>
            <span style={{ fontSize: 12 }}>
              风险: <Tag color={getRiskColor(definition.risk_level)}>{definition.risk_level}</Tag>
            </span>
            <span style={{ fontSize: 12 }}>
              最大调用: {definition.max_tool_calls} 次
            </span>
            <span style={{ fontSize: 12 }}>
              超时: {(definition.timeout_ms / 1000).toFixed(0)}s
            </span>
          </Space>
        </div>
      </div>

      {/* 触发关键词 */}
      {definition.when_to_use && (
        <div style={{ marginBottom: 12 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            💬 触发词: {definition.when_to_use}
          </Text>
        </div>
      )}

      {/* Prompt 折叠 */}
      <Collapse
        ghost
        size="small"
        items={[{
          key: 'prompt',
          label: <Text style={{ fontSize: 12 }}>查看完整 Prompt</Text>,
          children: (
            <pre style={{
              background: '#f5f5f5',
              padding: 12,
              borderRadius: 6,
              fontSize: 11,
              lineHeight: 1.5,
              maxHeight: 280,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              margin: 0,
            }}>
              {definition.prompt}
            </pre>
          ),
        }]}
      />
    </div>
  );
}
