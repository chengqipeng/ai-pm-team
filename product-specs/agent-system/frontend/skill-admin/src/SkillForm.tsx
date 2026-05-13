/**
 * 技能创建/编辑表单
 */
import React, { useState, useEffect } from 'react';
import {
  Card, Form, Input, Select, Button, Space, Switch, InputNumber,
  Tag, message, Row, Col, Divider, Collapse,
} from 'antd';
import { ArrowLeftOutlined, SaveOutlined, ThunderboltOutlined } from '@ant-design/icons';
import type { Skill, SkillCreateRequest, SkillUpdateRequest, SkillCategory, RiskLevel, SkillContext } from './types';
import { skillApi } from './api';

const { TextArea } = Input;
const { Option } = Select;

interface SkillFormProps {
  apiKey?: string;  // 有值=编辑模式，无值=创建模式
  onBack: () => void;
  onSaved: () => void;
}

export const SkillForm: React.FC<SkillFormProps> = ({ apiKey, onBack, onSaved }) => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testOutput, setTestOutput] = useState('');
  const isEdit = !!apiKey;

  useEffect(() => {
    if (apiKey) {
      loadSkill(apiKey);
    }
  }, [apiKey]);

  const loadSkill = async (key: string) => {
    setLoading(true);
    try {
      const skill = await skillApi.get(key);
      form.setFieldsValue({
        ...skill,
        allowed_tools: skill.allowed_tools || [],
        arguments: skill.arguments || [],
        tags: skill.tags || [],
      });
    } catch (e: any) {
      message.error(`加载失败: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);

      if (isEdit) {
        const req: SkillUpdateRequest = { ...values };
        await skillApi.update(apiKey!, req);
        message.success('保存成功');
      } else {
        const req: SkillCreateRequest = { ...values };
        await skillApi.create(req);
        message.success('创建成功');
      }
      onSaved();
    } catch (e: any) {
      if (e.errorFields) return; // 表单校验失败
      message.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    const args = form.getFieldValue('arguments') || [];
    const testArgs: Record<string, string> = {};
    args.forEach((arg: string) => {
      testArgs[arg] = `<测试值_${arg}>`;
    });

    setTesting(true);
    setTestOutput('');
    try {
      if (isEdit) {
        const res = await skillApi.test(apiKey!, { arguments: testArgs });
        setTestOutput(res.output);
      } else {
        // 创建模式下本地预览
        let prompt = form.getFieldValue('prompt') || '';
        for (const [k, v] of Object.entries(testArgs)) {
          prompt = prompt.replaceAll(`{${k}}`, v);
        }
        setTestOutput(prompt);
      }
    } catch (e: any) {
      setTestOutput(`错误: ${e.message}`);
    } finally {
      setTesting(false);
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={onBack} type="text" />
            <span>{isEdit ? `编辑技能: ${apiKey}` : '创建技能'}</span>
          </Space>
        }
        extra={
          <Space>
            <Button icon={<ThunderboltOutlined />} onClick={handleTest} loading={testing}>
              测试
            </Button>
            <Button type="primary" icon={<SaveOutlined />} onClick={handleSave} loading={saving}>
              {isEdit ? '保存' : '创建'}
            </Button>
          </Space>
        }
        loading={loading}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            context: 'inline',
            risk_level: 'read_only',
            max_tool_calls: 20,
            timeout_ms: 60000,
            requires_confirmation: false,
            category: '',
            tags: [],
            allowed_tools: [],
            arguments: [],
          }}
        >
          {/* 基本信息 */}
          <Divider orientation="left">基本信息</Divider>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                name="api_key"
                label="API Key"
                rules={[
                  { required: true, message: '请输入 API Key' },
                  { pattern: /^[a-zA-Z][a-zA-Z0-9_-]{1,98}$/, message: '字母开头，只能包含字母数字下划线连字符' },
                ]}
              >
                <Input placeholder="customer_health_check" disabled={isEdit} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
                <Input placeholder="客户健康度检查" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="category" label="分类">
                <Select placeholder="选择分类">
                  <Option value="">未分类</Option>
                  <Option value="crm">CRM 业务</Option>
                  <Option value="metarepo">元数据管理</Option>
                  <Option value="analysis">数据分析</Option>
                  <Option value="automation">自动化</Option>
                  <Option value="custom">自定义</Option>
                </Select>
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={16}>
            <Col span={16}>
              <Form.Item name="description" label="描述" rules={[{ required: true, message: '请输入描述' }]}>
                <TextArea rows={2} placeholder="一句话描述技能用途，LLM 根据此判断何时调用" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="when_to_use" label="触发关键词">
                <Input placeholder="客户健康|健康度|活跃度（|分隔）" />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="owner" label="归属">
                <Input placeholder="CRM-Platform" />
              </Form.Item>
            </Col>
            <Col span={16}>
              <Form.Item name="tags" label="标签">
                <Select mode="tags" placeholder="输入标签后回车" />
              </Form.Item>
            </Col>
          </Row>

          {/* 执行配置 */}
          <Divider orientation="left">执行配置</Divider>
          <Row gutter={16}>
            <Col span={6}>
              <Form.Item name="context" label="执行模式">
                <Select>
                  <Option value="inline">inline（注入主对话）</Option>
                  <Option value="fork">fork（独立子 Agent）</Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="agent" label="子 Agent（fork 模式）">
                <Input placeholder="空=使用默认 Agent" />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="model" label="指定模型">
                <Input placeholder="空=继承主模型" />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="allowed_tools" label="允许的工具">
                <Select mode="tags" placeholder="输入工具名后回车，如 query_data" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="arguments" label="参数列表">
                <Select mode="tags" placeholder="输入参数名后回车，如 account_id" />
              </Form.Item>
            </Col>
          </Row>

          {/* 安全配置 */}
          <Divider orientation="left">安全配置</Divider>
          <Row gutter={16}>
            <Col span={6}>
              <Form.Item name="risk_level" label="风险等级">
                <Select>
                  <Option value="read_only">只读 (read_only)</Option>
                  <Option value="mutating">可变更 (mutating)</Option>
                  <Option value="destructive">危险 (destructive)</Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="requires_confirmation" label="需要确认" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="max_tool_calls" label="最大工具调用次数">
                <InputNumber min={1} max={100} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="timeout_ms" label="超时时间 (ms)">
                <InputNumber min={5000} max={300000} step={5000} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>

          {/* 提示词 */}
          <Divider orientation="left">提示词 (Prompt)</Divider>
          <Form.Item
            name="prompt"
            rules={[{ required: true, message: '请输入提示词' }]}
            extra="支持 Markdown 格式，使用 {参数名} 作为占位符"
          >
            <TextArea
              rows={16}
              placeholder={`你是一位专家。请对 {account_id} 进行分析。\n\n## 步骤 1: 获取数据\n调用 query_data(...)\n\n## 步骤 2: 分析\n...`}
              style={{ fontFamily: 'monospace', fontSize: 13 }}
            />
          </Form.Item>

          {/* 测试输出 */}
          {testOutput && (
            <>
              <Divider orientation="left">测试输出</Divider>
              <Card size="small" style={{ background: '#f5f5f5' }}>
                <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, margin: 0, maxHeight: 400, overflow: 'auto' }}>
                  {testOutput}
                </pre>
              </Card>
            </>
          )}
        </Form>
      </Card>
    </div>
  );
};
