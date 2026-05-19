/**
 * Skill 测试调试面板
 *
 * 功能：
 * - 完整执行：一次性执行 Skill，展示逐步执行链路
 * - Mock 配置：对指定工具设置模拟返回值
 * - 测试用例：保存/加载/批量执行测试用例
 *
 * 入口：Skill 编辑页顶部的"▶ 测试"按钮
 */
import React, { useState, useCallback } from 'react';
import {
  Modal, Button, Input, Space, Tag, Steps, Card, Collapse,
  Form, Switch, Table, message, Spin, Typography, Alert, Tabs,
} from 'antd';
import {
  PlayCircleOutlined, ReloadOutlined, CheckCircleOutlined,
  CloseCircleOutlined, ExclamationCircleOutlined, CodeOutlined,
  PlusOutlined, DeleteOutlined, ThunderboltOutlined,
} from '@ant-design/icons';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;
const { TabPane } = Tabs;

// ═══════════════════════════════════════════════════════════
// 类型定义
// ═══════════════════════════════════════════════════════════

interface TestStep {
  step_num: number;
  step_type: 'llm_reasoning' | 'tool_call' | 'tool_result' | 'final_output' | 'error';
  status: 'completed' | 'running' | 'waiting' | 'skipped' | 'failed';
  tool_name: string;
  tool_input: Record<string, any>;
  tool_output: string;
  llm_thinking: string;
  duration_ms: number;
  tokens: number;
  risk_type: 'safe' | 'sensitive' | 'high_risk' | '';
  error_message: string;
}

interface TestResult {
  test_id: string;
  skill_api_key: string;
  status: 'success' | 'failed' | 'timeout' | 'cancelled';
  steps: TestStep[];
  final_output: string;
  total_duration_ms: number;
  total_tokens: number;
  total_tool_calls: number;
  total_llm_rounds: number;
  error_message: string;
  started_at: number;
  completed_at: number;
}

interface MockConfig {
  tool_name: string;
  mock_response: string;
  enabled: boolean;
}

interface TestCase {
  id: string;
  skill_api_key: string;
  name: string;
  arguments: Record<string, string>;
  expected_keywords: string[];
  excluded_keywords: string[];
  expected_tools: string[];
  max_duration_ms: number;
  mocks: MockConfig[];
  last_result: 'pass' | 'fail' | 'not_run';
  last_run_at: number;
  created_at: number;
}

interface SkillTestPanelProps {
  visible: boolean;
  onClose: () => void;
  skillApiKey: string;
  skillName: string;
  arguments: string[];  // Skill 定义的参数列表
  allowedTools: string[];  // Skill 允许的工具列表
}

// ═══════════════════════════════════════════════════════════
// API 调用
// ═══════════════════════════════════════════════════════════

const API_BASE = '/api/skills';

async function executeTest(
  apiKey: string,
  args: Record<string, string>,
  mocks: MockConfig[],
): Promise<TestResult> {
  const resp = await fetch(`${API_BASE}/${apiKey}/test/execute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ arguments: args, mocks }),
  });
  if (!resp.ok) throw new Error(`测试执行失败: ${resp.statusText}`);
  return resp.json();
}

async function fetchTestCases(apiKey: string): Promise<TestCase[]> {
  const resp = await fetch(`${API_BASE}/${apiKey}/test/cases`);
  if (!resp.ok) return [];
  const data = await resp.json();
  return data.items || [];
}

async function saveTestCase(apiKey: string, testCase: Partial<TestCase>): Promise<TestCase> {
  const resp = await fetch(`${API_BASE}/${apiKey}/test/cases`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(testCase),
  });
  if (!resp.ok) throw new Error('保存测试用例失败');
  return resp.json();
}

async function batchTest(apiKey: string, caseIds?: string[]): Promise<any> {
  const resp = await fetch(`${API_BASE}/${apiKey}/test/batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ case_ids: caseIds || [] }),
  });
  if (!resp.ok) throw new Error('批量测试失败');
  return resp.json();
}

// ═══════════════════════════════════════════════════════════
// 步骤渲染组件
// ═══════════════════════════════════════════════════════════

function StepItem({ step }: { step: TestStep }) {
  const getStepIcon = () => {
    if (step.status === 'failed') return <CloseCircleOutlined style={{ color: '#ef4444' }} />;
    if (step.step_type === 'llm_reasoning') return <ThunderboltOutlined style={{ color: '#10b981' }} />;
    if (step.step_type === 'tool_call') return <CodeOutlined style={{ color: '#2563eb' }} />;
    if (step.step_type === 'final_output') return <CheckCircleOutlined style={{ color: '#7c3aed' }} />;
    if (step.step_type === 'error') return <CloseCircleOutlined style={{ color: '#ef4444' }} />;
    return <PlayCircleOutlined />;
  };

  const getRiskTag = () => {
    if (!step.risk_type) return null;
    const config: Record<string, { color: string; label: string }> = {
      safe: { color: 'green', label: '安全' },
      sensitive: { color: 'orange', label: '敏感' },
      high_risk: { color: 'red', label: '高风险' },
    };
    const c = config[step.risk_type];
    return c ? <Tag color={c.color}>{c.label}</Tag> : null;
  };

  const getBgColor = () => {
    switch (step.step_type) {
      case 'llm_reasoning': return '#f0fdf4';
      case 'tool_call': return '#eff6ff';
      case 'final_output': return '#f5f3ff';
      case 'error': return '#fef2f2';
      default: return '#f9fafb';
    }
  };

  return (
    <div style={{
      background: getBgColor(),
      borderRadius: 8,
      padding: '12px 16px',
      marginBottom: 8,
      border: '1px solid #e2e8f0',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space>
          {getStepIcon()}
          <Text strong style={{ fontSize: 13 }}>
            {step.step_type === 'llm_reasoning' && 'LLM 推理'}
            {step.step_type === 'tool_call' && `工具调用: ${step.tool_name}`}
            {step.step_type === 'final_output' && '最终输出'}
            {step.step_type === 'error' && '错误'}
          </Text>
          {getRiskTag()}
        </Space>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {step.duration_ms > 0 && `${step.duration_ms.toFixed(1)}ms`}
          {step.tokens > 0 && ` · ${step.tokens} tokens`}
        </Text>
      </div>

      {step.llm_thinking && (
        <Paragraph
          style={{ margin: '8px 0 0', fontSize: 12, color: '#475569' }}
          ellipsis={{ rows: 3, expandable: true }}
        >
          {step.llm_thinking}
        </Paragraph>
      )}

      {step.step_type === 'tool_call' && (
        <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <div style={{ background: '#fff', borderRadius: 6, padding: 8, border: '1px solid #d1d5db' }}>
            <Text type="secondary" style={{ fontSize: 11 }}>输入参数:</Text>
            <pre style={{ fontSize: 11, margin: '4px 0 0', overflow: 'auto', maxHeight: 80 }}>
              {JSON.stringify(step.tool_input, null, 2)}
            </pre>
          </div>
          <div style={{ background: '#fff', borderRadius: 6, padding: 8, border: '1px solid #d1d5db' }}>
            <Text type="secondary" style={{ fontSize: 11 }}>返回结果:</Text>
            <pre style={{ fontSize: 11, margin: '4px 0 0', overflow: 'auto', maxHeight: 80 }}>
              {step.tool_output || '(空)'}
            </pre>
          </div>
        </div>
      )}

      {step.step_type === 'final_output' && step.tool_output && (
        <Paragraph
          style={{ margin: '8px 0 0', fontSize: 12, background: '#fff', padding: 12, borderRadius: 6, border: '1px solid #d1d5db' }}
          ellipsis={{ rows: 5, expandable: true }}
        >
          {step.tool_output}
        </Paragraph>
      )}

      {step.error_message && (
        <Alert type="error" message={step.error_message} style={{ marginTop: 8 }} showIcon />
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// 主组件
// ═══════════════════════════════════════════════════════════

export default function SkillTestPanel({
  visible, onClose, skillApiKey, skillName, arguments: skillArgs, allowedTools,
}: SkillTestPanelProps) {
  const [activeTab, setActiveTab] = useState('execute');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);

  // 参数输入
  const [argValues, setArgValues] = useState<Record<string, string>>({});

  // Mock 配置
  const [mocks, setMocks] = useState<MockConfig[]>([]);

  // 测试用例
  const [testCases, setTestCases] = useState<TestCase[]>([]);

  // ── 执行测试 ──
  const handleExecute = useCallback(async () => {
    setLoading(true);
    setResult(null);
    try {
      const res = await executeTest(skillApiKey, argValues, mocks.filter(m => m.enabled));
      setResult(res);
      if (res.status === 'success') {
        message.success(`测试完成 · ${res.total_duration_ms.toFixed(0)}ms · ${res.total_tool_calls} 次工具调用`);
      } else {
        message.error(`测试${res.status === 'timeout' ? '超时' : '失败'}: ${res.error_message}`);
      }
    } catch (e: any) {
      message.error(e.message || '测试执行异常');
    } finally {
      setLoading(false);
    }
  }, [skillApiKey, argValues, mocks]);

  // ── 保存为测试用例 ──
  const handleSaveCase = useCallback(async () => {
    const name = window.prompt('请输入测试用例名称:');
    if (!name) return;
    try {
      const newCase = await saveTestCase(skillApiKey, {
        name,
        arguments: argValues,
        expected_keywords: [],
        mocks,
      });
      setTestCases(prev => [...prev, newCase]);
      message.success('测试用例已保存');
    } catch (e: any) {
      message.error(e.message);
    }
  }, [skillApiKey, argValues, mocks]);

  // ── 批量执行 ──
  const handleBatchTest = useCallback(async () => {
    setLoading(true);
    try {
      const res = await batchTest(skillApiKey);
      message.info(`批量测试完成: ${res.passed}/${res.total} 通过`);
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setLoading(false);
    }
  }, [skillApiKey]);

  return (
    <Modal
      title={`测试调试 — ${skillName}（${skillApiKey}）`}
      open={visible}
      onCancel={onClose}
      width={900}
      footer={null}
      destroyOnClose
    >
      <Tabs activeKey={activeTab} onChange={setActiveTab}>
        {/* ── Tab 1: 执行测试 ── */}
        <TabPane tab="执行测试" key="execute">
          {/* 参数输入 */}
          <Card size="small" title="输入参数" style={{ marginBottom: 16 }}>
            {skillArgs.length === 0 ? (
              <Text type="secondary">该技能无需输入参数</Text>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                {skillArgs.map(arg => (
                  <div key={arg}>
                    <Text style={{ fontSize: 12, color: '#64748b' }}>{arg}</Text>
                    <Input
                      size="small"
                      placeholder={`输入 ${arg}`}
                      value={argValues[arg] || ''}
                      onChange={e => setArgValues(prev => ({ ...prev, [arg]: e.target.value }))}
                    />
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* Mock 配置 */}
          <Card
            size="small"
            title="Mock 配置"
            style={{ marginBottom: 16 }}
            extra={
              <Button
                size="small"
                icon={<PlusOutlined />}
                onClick={() => setMocks(prev => [...prev, { tool_name: '', mock_response: '{}', enabled: true }])}
              >
                添加 Mock
              </Button>
            }
          >
            {mocks.length === 0 ? (
              <Text type="secondary" style={{ fontSize: 12 }}>未配置 Mock，所有工具将真实执行</Text>
            ) : (
              mocks.map((mock, idx) => (
                <div key={idx} style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center' }}>
                  <Input
                    size="small"
                    placeholder="工具名称"
                    value={mock.tool_name}
                    style={{ width: 150 }}
                    onChange={e => {
                      const newMocks = [...mocks];
                      newMocks[idx].tool_name = e.target.value;
                      setMocks(newMocks);
                    }}
                  />
                  <Input
                    size="small"
                    placeholder="Mock 返回值 (JSON)"
                    value={mock.mock_response}
                    style={{ flex: 1 }}
                    onChange={e => {
                      const newMocks = [...mocks];
                      newMocks[idx].mock_response = e.target.value;
                      setMocks(newMocks);
                    }}
                  />
                  <Switch
                    size="small"
                    checked={mock.enabled}
                    onChange={checked => {
                      const newMocks = [...mocks];
                      newMocks[idx].enabled = checked;
                      setMocks(newMocks);
                    }}
                  />
                  <Button
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => setMocks(prev => prev.filter((_, i) => i !== idx))}
                  />
                </div>
              ))
            )}
          </Card>

          {/* 操作按钮 */}
          <Space style={{ marginBottom: 16 }}>
            <Button type="primary" icon={<PlayCircleOutlined />} loading={loading} onClick={handleExecute}>
              执行测试
            </Button>
            <Button icon={<ReloadOutlined />} onClick={() => { setResult(null); setArgValues({}); }}>
              重置
            </Button>
            <Button onClick={handleSaveCase}>保存为测试用例</Button>
          </Space>

          {/* 执行结果 */}
          {result && (
            <>
              {/* 统计摘要 */}
              <div style={{
                display: 'flex', gap: 24, padding: 12, background: '#f9fafb',
                borderRadius: 8, marginBottom: 16, fontSize: 13,
              }}>
                <span>⏱ 总耗时: <strong>{result.total_duration_ms.toFixed(0)}ms</strong></span>
                <span>🔤 Tokens: <strong>{result.total_tokens}</strong></span>
                <span>🔧 工具调用: <strong>{result.total_tool_calls} 次</strong></span>
                <span>🔄 LLM 轮次: <strong>{result.total_llm_rounds} 轮</strong></span>
                <span>
                  状态: {result.status === 'success'
                    ? <Tag color="green">成功</Tag>
                    : <Tag color="red">{result.status}</Tag>
                  }
                </span>
              </div>

              {/* 步骤链路 */}
              <div style={{ maxHeight: 400, overflowY: 'auto' }}>
                {result.steps.map(step => (
                  <StepItem key={step.step_num} step={step} />
                ))}
              </div>
            </>
          )}
        </TabPane>

        {/* ── Tab 2: 测试用例 ── */}
        <TabPane tab="测试用例" key="cases">
          <Space style={{ marginBottom: 16 }}>
            <Button type="primary" icon={<PlayCircleOutlined />} loading={loading} onClick={handleBatchTest}>
              批量执行全部用例
            </Button>
            <Button icon={<PlusOutlined />} onClick={handleSaveCase}>
              新增用例
            </Button>
          </Space>

          <Table
            size="small"
            dataSource={testCases}
            rowKey="id"
            pagination={false}
            columns={[
              { title: '用例名称', dataIndex: 'name', width: 150 },
              {
                title: '输入参数', dataIndex: 'arguments', width: 200,
                render: (args: Record<string, string>) =>
                  Object.entries(args).map(([k, v]) => `${k}=${v}`).join(', '),
              },
              {
                title: '期望关键词', dataIndex: 'expected_keywords', width: 150,
                render: (kws: string[]) => kws.join(', ') || '-',
              },
              {
                title: '上次结果', dataIndex: 'last_result', width: 80,
                render: (v: string) => {
                  if (v === 'pass') return <Tag color="green">通过</Tag>;
                  if (v === 'fail') return <Tag color="red">失败</Tag>;
                  return <Tag>未执行</Tag>;
                },
              },
              {
                title: '操作', width: 100,
                render: (_: any, record: TestCase) => (
                  <Space>
                    <Button size="small" type="link">执行</Button>
                    <Button size="small" type="link" danger>删除</Button>
                  </Space>
                ),
              },
            ]}
          />
        </TabPane>
      </Tabs>
    </Modal>
  );
}
