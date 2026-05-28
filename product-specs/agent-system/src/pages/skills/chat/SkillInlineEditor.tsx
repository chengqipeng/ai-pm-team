/**
 * SkillInlineEditor — 内联编辑技能定义
 *
 * 在 Chat 对话中直接编辑 Agent 生成的技能定义。
 * 用户点击"修改"后切换到此组件，编辑完成后回到预览模式。
 */
import React from 'react';
import {
  Form, Input, Select, InputNumber, Button, Space, Typography,
} from 'antd';
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import type { SkillDefinition } from './types';
import { AVAILABLE_TOOLS, CATEGORY_OPTIONS, RISK_LEVEL_OPTIONS } from './types';

const { TextArea } = Input;
const { Text } = Typography;

interface SkillInlineEditorProps {
  definition: SkillDefinition;
  onSave: (modified: SkillDefinition) => void;
  onCancel: () => void;
}

export default function SkillInlineEditor({
  definition,
  onSave,
  onCancel,
}: SkillInlineEditorProps) {
  const [form] = Form.useForm();

  const handleFinish = (values: any) => {
    // 将 argumentItems 转回 arguments + argument_descriptions
    const argItems: Array<{ name: string; description: string }> = values.argumentItems || [];
    const args = argItems.map(item => item.name).filter(Boolean);
    const argDescs: Record<string, string> = {};
    argItems.forEach(item => {
      if (item.name && item.description) {
        argDescs[item.name] = item.description;
      }
    });

    const modified: SkillDefinition = {
      ...definition,
      name: values.name,
      description: values.description,
      when_to_use: values.when_to_use || '',
      category: values.category || 'custom',
      arguments: args,
      argument_descriptions: argDescs,
      allowed_tools: values.allowed_tools || [],
      risk_level: values.risk_level || 'read_only',
      max_tool_calls: values.max_tool_calls || 15,
      timeout_ms: values.timeout_ms || 45000,
      prompt: values.prompt || '',
    };
    onSave(modified);
  };

  // 将 arguments + argument_descriptions 转为 argumentItems 供 Form.List 使用
  const initialArgumentItems = definition.arguments.map(arg => ({
    name: arg,
    description: definition.argument_descriptions?.[arg] || '',
  }));

  return (
    <Form
      form={form}
      layout="vertical"
      size="small"
      initialValues={{
        name: definition.name,
        description: definition.description,
        when_to_use: definition.when_to_use,
        category: definition.category,
        allowed_tools: definition.allowed_tools,
        risk_level: definition.risk_level,
        max_tool_calls: definition.max_tool_calls,
        timeout_ms: definition.timeout_ms,
        prompt: definition.prompt,
        argumentItems: initialArgumentItems,
      }}
      onFinish={handleFinish}
      style={{ maxHeight: 480, overflowY: 'auto', paddingRight: 4 }}
    >
      {/* 基本信息 */}
      <Form.Item
        label="名称"
        name="name"
        rules={[{ required: true, message: '请输入技能名称' }]}
      >
        <Input placeholder="简短的中文名称" />
      </Form.Item>

      <Form.Item
        label="描述"
        name="description"
        rules={[{ required: true, message: '请输入技能描述' }]}
      >
        <TextArea rows={2} placeholder="一句话描述技能用途" />
      </Form.Item>

      <Form.Item label="触发关键词" name="when_to_use">
        <Input placeholder="关键词1|关键词2|关键词3（用 | 分隔）" />
      </Form.Item>

      <Form.Item label="分类" name="category">
        <Select options={[...CATEGORY_OPTIONS]} />
      </Form.Item>

      {/* 参数列表 — 动态增删 */}
      <div style={{ marginBottom: 16 }}>
        <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
          参数列表
        </Text>
        <Form.List name="argumentItems">
          {(fields, { add, remove }) => (
            <>
              {fields.map((field) => (
                <Space key={field.key} align="baseline" style={{ display: 'flex', marginBottom: 4 }}>
                  <Form.Item
                    {...field}
                    name={[field.name, 'name']}
                    rules={[{ required: true, message: '参数名' }]}
                    style={{ marginBottom: 0 }}
                  >
                    <Input placeholder="参数名" style={{ width: 120 }} />
                  </Form.Item>
                  <Form.Item
                    {...field}
                    name={[field.name, 'description']}
                    style={{ marginBottom: 0 }}
                  >
                    <Input placeholder="参数描述" style={{ width: 180 }} />
                  </Form.Item>
                  <MinusCircleOutlined
                    onClick={() => remove(field.name)}
                    style={{ color: '#999' }}
                  />
                </Space>
              ))}
              <Button
                type="dashed"
                size="small"
                onClick={() => add({ name: '', description: '' })}
                icon={<PlusOutlined />}
                style={{ width: '100%' }}
              >
                添加参数
              </Button>
            </>
          )}
        </Form.List>
      </div>

      {/* 工具选择 */}
      <Form.Item label="允许工具" name="allowed_tools">
        <Select
          mode="multiple"
          placeholder="选择技能可使用的工具"
          options={AVAILABLE_TOOLS.map(t => ({ label: t, value: t }))}
        />
      </Form.Item>

      {/* 安全配置 */}
      <Space size="middle" style={{ marginBottom: 16 }}>
        <Form.Item label="风险等级" name="risk_level" style={{ marginBottom: 0 }}>
          <Select style={{ width: 100 }} options={[...RISK_LEVEL_OPTIONS]} />
        </Form.Item>
        <Form.Item label="最大调用" name="max_tool_calls" style={{ marginBottom: 0 }}>
          <InputNumber min={1} max={50} style={{ width: 70 }} />
        </Form.Item>
        <Form.Item label="超时(ms)" name="timeout_ms" style={{ marginBottom: 0 }}>
          <InputNumber min={5000} max={300000} step={5000} style={{ width: 100 }} />
        </Form.Item>
      </Space>

      {/* Prompt 编辑器 */}
      <Form.Item
        label="Prompt"
        name="prompt"
        rules={[{ required: true, message: '请输入技能 Prompt' }]}
      >
        <TextArea
          rows={8}
          placeholder="技能执行的详细 Prompt（Markdown 格式，用 {参数名} 作占位符）"
          style={{ fontFamily: 'monospace', fontSize: 12 }}
        />
      </Form.Item>

      {/* 操作按钮 */}
      <Space>
        <Button onClick={onCancel}>取消修改</Button>
        <Button type="primary" htmlType="submit">保存修改</Button>
      </Space>
    </Form>
  );
}
