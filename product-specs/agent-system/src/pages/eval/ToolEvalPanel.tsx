/**
 * Tool 评测面板（v2 — 支持工具/方法/分类级执行 + 参数组合生成）
 *
 * 功能：
 * - 用例目录树：按工具 → 方法 → 分类 三级浏览
 * - 按分类执行：如执行 query_schema 下所有用例
 * - 按方法执行：如执行 query_schema/list_entities 下所有用例
 * - 自动生成参数组合用例
 * - 查看评测报告（按工具 + 方法分组）
 * - 历史报告
 */
import React, { useState, useCallback, useEffect } from 'react';
import {
  Card, Button, Space, Tag, Table, Collapse, Tabs, Tree,
  message, Spin, Typography, Alert, Select, Progress,
  Statistic, Row, Col, Tooltip, Badge, Modal, Popconfirm,
} from 'antd';
import {
  PlayCircleOutlined, ReloadOutlined, CheckCircleOutlined,
  CloseCircleOutlined, ExperimentOutlined, HistoryOutlined,
  ThunderboltOutlined, ApartmentOutlined, PlusOutlined,
  RobotOutlined, FolderOutlined, FileOutlined,
} from '@ant-design/icons';

const { Text, Title } = Typography;
const { TabPane } = Tabs;
const { Panel } = Collapse;

// ═══════════════════════════════════════════════════════════
// 类型定义
// ═══════════════════════════════════════════════════════════

interface MethodStats {
  total: number;
  by_category: Record<string, number>;
}

interface ToolCatalog {
  methods: string[];
  stats: Record<string, MethodStats>;
  total: number;
}

interface CatalogData {
  catalog: Record<string, ToolCatalog>;
}

interface AssertionResult {
  passed: boolean;
  type: string;
  description: string;
  expected: any;
  actual: string | null;
  message: string;
}

interface CaseResult {
  case_id: string;
  tool_name: string;
  description: string;
  category: string;
  passed: boolean;
  duration_ms: number;
  assertion_results: AssertionResult[];
  tool_output: string | null;
  is_error: boolean | null;
  error: string;
}

interface ToolStats {
  total: number;
  passed: number;
  failed: number;
}

interface SuiteReport {
  report_id: string;
  suite_name: string;
  total: number;
  passed: number;
  failed: number;
  error: number;
  pass_rate: number;
  total_duration_ms: number;
  by_tool: Record<string, ToolStats>;
  by_method: Record<string, ToolStats>;
  by_category: Record<string, ToolStats>;
  results: CaseResult[];
  failures: any[];
  filters?: { tool_names: string[]; method_names: string[]; categories: string[] };
  created_at: number;
}

interface GenerateSummary {
  summary: Record<string, Record<string, { total: number; positive: number; negative: number; boundary: number }>>;
  total_generated: number;
  saved_to_db: boolean;
}

// ═══════════════════════════════════════════════════════════
// API 调用
// ═══════════════════════════════════════════════════════════

const API_BASE = '/api/eval/tools';

async function fetchCatalog(): Promise<CatalogData> {
  const resp = await fetch(`${API_BASE}/catalog`);
  if (!resp.ok) return { catalog: {} };
  return resp.json();
}

async function runEval(params: {
  tool_names?: string[];
  method_names?: string[];
  categories?: string[];
  use_db?: boolean;
}): Promise<SuiteReport> {
  const resp = await fetch(`${API_BASE}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || '评测执行失败');
  }
  return resp.json();
}

async function generateCases(params: {
  tool_name?: string;
  method_name?: string;
  max_positive?: number;
  save_to_db?: boolean;
  overwrite?: boolean;
}): Promise<GenerateSummary> {
  const resp = await fetch(`${API_BASE}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || '生成失败');
  }
  return resp.json();
}

async function fetchReports(limit = 20): Promise<SuiteReport[]> {
  const resp = await fetch(`${API_BASE}/reports?limit=${limit}`);
  if (!resp.ok) return [];
  const data = await resp.json();
  return data.items || [];
}

async function syncPresets(): Promise<any> {
  const resp = await fetch(`${API_BASE}/sync-presets`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
  return resp.json();
}

// ═══════════════════════════════════════════════════════════
// 子组件
// ═══════════════════════════════════════════════════════════

/** 工具/方法维度统计卡片 */
function StatCard({ label, stats, onClick }: { label: string; stats: ToolStats; onClick?: () => void }) {
  const allPassed = stats.failed === 0;
  return (
    <Card
      size="small"
      hoverable={!!onClick}
      onClick={onClick}
      style={{
        borderLeft: `3px solid ${allPassed ? '#52c41a' : '#ff4d4f'}`,
        marginBottom: 8,
        cursor: onClick ? 'pointer' : 'default',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space>
          {allPassed
            ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
            : <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
          }
          <Text strong style={{ fontSize: 13 }}>{label}</Text>
        </Space>
        <Text style={{ fontSize: 13 }}>
          <Text type={allPassed ? 'success' : 'danger'} strong>
            {stats.passed}/{stats.total}
          </Text>
        </Text>
      </div>
    </Card>
  );
}

/** 单个用例结果行 */
function CaseResultRow({ result }: { result: CaseResult }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      style={{
        background: result.passed ? '#f6ffed' : '#fff2f0',
        borderRadius: 6,
        padding: '10px 14px',
        marginBottom: 6,
        border: `1px solid ${result.passed ? '#b7eb8f' : '#ffccc7'}`,
        cursor: 'pointer',
      }}
      onClick={() => setExpanded(!expanded)}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space>
          {result.passed
            ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
            : <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
          }
          <Text style={{ fontSize: 12 }}>{result.description}</Text>
          <Tag color={
            result.category === 'normal' ? 'blue' :
            result.category === 'error' ? 'orange' :
            result.category === 'boundary' ? 'purple' : 'cyan'
          }>
            {result.category}
          </Tag>
        </Space>
        <Text type="secondary" style={{ fontSize: 11 }}>
          {result.duration_ms.toFixed(0)}ms
        </Text>
      </div>

      {expanded && (
        <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid #e8e8e8' }}>
          {result.tool_output && (
            <div style={{ marginBottom: 8 }}>
              <Text type="secondary" style={{ fontSize: 11 }}>工具输出:</Text>
              <pre style={{
                fontSize: 11, margin: '4px 0', padding: 8,
                background: '#fafafa', borderRadius: 4, maxHeight: 100, overflow: 'auto',
              }}>
                {result.tool_output}
              </pre>
            </div>
          )}
          <div>
            <Text type="secondary" style={{ fontSize: 11 }}>断言结果:</Text>
            {result.assertion_results.map((ar, idx) => (
              <div key={idx} style={{ fontSize: 11, marginTop: 4, paddingLeft: 12 }}>
                {ar.passed
                  ? <Text type="success">✓ {ar.description || ar.type}</Text>
                  : <Text type="danger">✗ {ar.description || ar.type}: {ar.message}</Text>
                }
              </div>
            ))}
          </div>
          {result.error && (
            <Alert type="error" message={result.error} style={{ marginTop: 8 }} showIcon />
          )}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// 主组件
// ═══════════════════════════════════════════════════════════

export default function ToolEvalPanel() {
  const [activeTab, setActiveTab] = useState('catalog');
  const [loading, setLoading] = useState(false);
  const [catalog, setCatalog] = useState<CatalogData>({ catalog: {} });
  const [currentReport, setCurrentReport] = useState<SuiteReport | null>(null);
  const [historyReports, setHistoryReports] = useState<SuiteReport[]>([]);

  // 执行筛选
  const [selectedTool, setSelectedTool] = useState<string | null>(null);
  const [selectedMethod, setSelectedMethod] = useState<string | null>(null);
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);

  // 生成状态
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    fetchCatalog().then(setCatalog);
    fetchReports().then(setHistoryReports);
  }, []);

  const availableCategories = ['normal', 'error', 'boundary', 'side_effect'];

  // ── 构建目录树数据 ──
  const treeData = Object.entries(catalog.catalog).map(([toolName, toolInfo]) => ({
    title: (
      <Space>
        <FolderOutlined />
        <Text strong>{toolName}</Text>
        <Badge count={toolInfo.total} style={{ backgroundColor: '#1890ff' }} overflowCount={999} />
      </Space>
    ),
    key: toolName,
    children: toolInfo.methods.map(method => {
      const methodStats = toolInfo.stats[method];
      const total = methodStats?.total || 0;
      return {
        title: (
          <Space>
            <FileOutlined />
            <Text>{method}</Text>
            <Tag color="blue" style={{ fontSize: 10 }}>{total}</Tag>
            {methodStats?.by_category && Object.entries(methodStats.by_category).map(([cat, count]) => (
              <Tag key={cat} color={cat === 'normal' ? 'green' : cat === 'error' ? 'red' : 'purple'}
                style={{ fontSize: 10 }}>
                {cat}:{count}
              </Tag>
            ))}
          </Space>
        ),
        key: `${toolName}/${method}`,
        isLeaf: true,
      };
    }),
  }));

  // ── 目录树选中 ──
  const handleTreeSelect = (selectedKeys: any[]) => {
    if (selectedKeys.length === 0) {
      setSelectedTool(null);
      setSelectedMethod(null);
      return;
    }
    const key = selectedKeys[0] as string;
    if (key.includes('/')) {
      const [tool, method] = key.split('/');
      setSelectedTool(tool);
      setSelectedMethod(method);
    } else {
      setSelectedTool(key);
      setSelectedMethod(null);
    }
  };

  // ── 执行评测 ──
  const handleRunEval = useCallback(async () => {
    setLoading(true);
    setCurrentReport(null);
    setActiveTab('results');
    try {
      const params: any = { use_db: true };
      if (selectedTool) params.tool_names = [selectedTool];
      if (selectedMethod) params.method_names = [selectedMethod];
      if (selectedCategories.length > 0) params.categories = selectedCategories;

      const report = await runEval(params);
      setCurrentReport(report);
      fetchReports().then(setHistoryReports);

      if (report.failed === 0 && report.error === 0) {
        message.success(`全部通过 ✅ ${report.passed}/${report.total} | ${report.total_duration_ms.toFixed(0)}ms`);
      } else {
        message.warning(`${report.failed} 个用例失败 | ${report.passed}/${report.total} 通过`);
      }
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setLoading(false);
    }
  }, [selectedTool, selectedMethod, selectedCategories]);

  // ── 自动生成用例 ──
  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    try {
      const result = await generateCases({
        tool_name: selectedTool || undefined,
        method_name: selectedMethod || undefined,
        save_to_db: true,
        overwrite: true,
      });
      message.success(`已生成 ${result.total_generated} 条用例并存入数据库`);
      // 刷新目录
      fetchCatalog().then(setCatalog);
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setGenerating(false);
    }
  }, [selectedTool, selectedMethod]);

  // ── 同步预置用例 ──
  const handleSyncPresets = useCallback(async () => {
    try {
      const result = await syncPresets();
      message.success(result.message);
      fetchCatalog().then(setCatalog);
    } catch (e: any) {
      message.error(e.message);
    }
  }, []);

  return (
    <div style={{ padding: 24, maxWidth: 1400 }}>
      {/* 顶部标题 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>
            <ExperimentOutlined /> Tool 评测
          </Title>
          <Text type="secondary">
            直接调用工具函数验证功能正确性 · 支持工具/方法/分类级执行 · 自动参数组合覆盖
          </Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={handleSyncPresets}>
            同步预置用例
          </Button>
          <Popconfirm
            title="自动生成参数组合用例"
            description={`将为 ${selectedTool || '所有工具'}${selectedMethod ? '/' + selectedMethod : ''} 生成覆盖用例，会覆盖已有自动生成的用例。`}
            onConfirm={handleGenerate}
            okText="确认生成"
            cancelText="取消"
          >
            <Button icon={<RobotOutlined />} loading={generating} type="dashed">
              自动生成用例
            </Button>
          </Popconfirm>
        </Space>
      </div>

      <div style={{ display: 'flex', gap: 16 }}>
        {/* 左侧：目录树 */}
        <Card
          size="small"
          title={<><ApartmentOutlined /> 用例目录</>}
          style={{ width: 360, flexShrink: 0 }}
          bodyStyle={{ padding: '8px 0' }}
        >
          {Object.keys(catalog.catalog).length > 0 ? (
            <Tree
              treeData={treeData}
              defaultExpandAll
              onSelect={handleTreeSelect}
              style={{ padding: '0 12px' }}
            />
          ) : (
            <div style={{ textAlign: 'center', padding: 24, color: '#999' }}>
              <Text type="secondary">暂无用例，请先同步预置或自动生成</Text>
            </div>
          )}

          {/* 选中状态 + 执行按钮 */}
          <div style={{ padding: '12px 16px', borderTop: '1px solid #f0f0f0' }}>
            <div style={{ marginBottom: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                执行范围: {selectedTool
                  ? `${selectedTool}${selectedMethod ? '/' + selectedMethod : ' (全部方法)'}`
                  : '全部工具'}
              </Text>
            </div>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Select
                mode="multiple"
                placeholder="筛选分类（不选=全部）"
                style={{ width: '100%' }}
                size="small"
                value={selectedCategories}
                onChange={setSelectedCategories}
                options={availableCategories.map(c => ({ label: c, value: c }))}
                allowClear
              />
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                loading={loading}
                onClick={handleRunEval}
                block
              >
                执行评测
              </Button>
            </Space>
          </div>
        </Card>

        {/* 右侧：结果 + 历史 */}
        <div style={{ flex: 1 }}>
          <Tabs activeKey={activeTab} onChange={setActiveTab}>
            {/* Tab: 执行结果 */}
            <TabPane tab={<span><ThunderboltOutlined /> 执行结果</span>} key="results">
              {currentReport ? (
                <>
                  {/* 筛选条件显示 */}
                  {currentReport.filters && (
                    <Alert
                      type="info"
                      showIcon
                      style={{ marginBottom: 12 }}
                      message={
                        <Space>
                          <Text style={{ fontSize: 12 }}>
                            执行范围:
                            {currentReport.filters.tool_names?.length
                              ? ` 工具=[${currentReport.filters.tool_names.join(',')}]` : ' 全部工具'}
                            {currentReport.filters.method_names?.length
                              ? ` 方法=[${currentReport.filters.method_names.join(',')}]` : ''}
                            {currentReport.filters.categories?.length
                              ? ` 分类=[${currentReport.filters.categories.join(',')}]` : ''}
                          </Text>
                        </Space>
                      }
                    />
                  )}

                  {/* 总览统计 */}
                  <Row gutter={12} style={{ marginBottom: 16 }}>
                    <Col span={5}>
                      <Card size="small">
                        <Statistic
                          title="Pass Rate"
                          value={currentReport.pass_rate * 100}
                          suffix="%"
                          precision={1}
                          valueStyle={{ color: currentReport.pass_rate >= 0.9 ? '#3f8600' : '#cf1322' }}
                        />
                      </Card>
                    </Col>
                    <Col span={4}>
                      <Card size="small">
                        <Statistic title="通过" value={currentReport.passed} valueStyle={{ color: '#3f8600' }} />
                      </Card>
                    </Col>
                    <Col span={4}>
                      <Card size="small">
                        <Statistic title="失败" value={currentReport.failed} valueStyle={{ color: '#cf1322' }} />
                      </Card>
                    </Col>
                    <Col span={4}>
                      <Card size="small">
                        <Statistic title="错误" value={currentReport.error} />
                      </Card>
                    </Col>
                    <Col span={4}>
                      <Card size="small">
                        <Statistic title="总用例" value={currentReport.total} />
                      </Card>
                    </Col>
                    <Col span={3}>
                      <Card size="small">
                        <Statistic title="耗时" value={currentReport.total_duration_ms} suffix="ms" precision={0} />
                      </Card>
                    </Col>
                  </Row>

                  {/* 按工具分组 */}
                  <Card size="small" title="按工具" style={{ marginBottom: 12 }}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 8 }}>
                      {Object.entries(currentReport.by_tool).map(([tool, stats]) => (
                        <StatCard
                          key={tool}
                          label={tool}
                          stats={stats}
                          onClick={() => { setSelectedTool(tool); setSelectedMethod(null); }}
                        />
                      ))}
                    </div>
                  </Card>

                  {/* 按方法分组 */}
                  {currentReport.by_method && Object.keys(currentReport.by_method).length > 0 && (
                    <Card size="small" title="按方法" style={{ marginBottom: 12 }}>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 8 }}>
                        {Object.entries(currentReport.by_method).map(([key, stats]) => (
                          <StatCard key={key} label={key} stats={stats} />
                        ))}
                      </div>
                    </Card>
                  )}

                  {/* 失败详情 */}
                  {currentReport.failures.length > 0 && (
                    <Card
                      size="small"
                      title={<Text type="danger">❌ 失败用例 ({currentReport.failures.length})</Text>}
                      style={{ marginBottom: 12, borderColor: '#ffccc7' }}
                    >
                      {currentReport.results
                        .filter(r => !r.passed)
                        .map(r => <CaseResultRow key={r.case_id} result={r} />)
                      }
                    </Card>
                  )}

                  {/* 全部详情 */}
                  <Collapse ghost>
                    <Panel header={`全部用例详情 (${currentReport.total})`} key="all">
                      {currentReport.results.map(r => (
                        <CaseResultRow key={r.case_id} result={r} />
                      ))}
                    </Panel>
                  </Collapse>
                </>
              ) : (
                <div style={{ textAlign: 'center', padding: 60, color: '#999' }}>
                  {loading ? (
                    <Spin size="large" tip="执行评测中..." />
                  ) : (
                    <>
                      <ExperimentOutlined style={{ fontSize: 48, marginBottom: 16 }} />
                      <div>在左侧目录中选择工具或方法，点击「执行评测」开始</div>
                      <div style={{ marginTop: 8, fontSize: 12 }}>
                        支持按工具分类执行、按方法执行、按场景分类执行
                      </div>
                    </>
                  )}
                </div>
              )}
            </TabPane>

            {/* Tab: 历史报告 */}
            <TabPane tab={<span><HistoryOutlined /> 历史报告</span>} key="history">
              <Table
                size="small"
                dataSource={historyReports}
                rowKey="report_key"
                pagination={{ pageSize: 10 }}
                columns={[
                  {
                    title: '筛选范围', width: 200,
                    render: (_: any, r: any) => {
                      const tools = r.filter_tools?.length ? r.filter_tools.join(',') : '全部';
                      const methods = r.filter_methods?.length ? `/${r.filter_methods.join(',')}` : '';
                      return `${tools}${methods}`;
                    },
                  },
                  {
                    title: 'Pass Rate', dataIndex: 'pass_rate', width: 120,
                    render: (v: number) => (
                      <Progress
                        percent={Math.round(v * 100)}
                        size="small"
                        status={v >= 0.9 ? 'success' : v >= 0.7 ? 'normal' : 'exception'}
                      />
                    ),
                  },
                  {
                    title: '通过/总数', width: 100,
                    render: (_: any, r: any) => `${r.passed}/${r.total}`,
                  },
                  {
                    title: '耗时', dataIndex: 'total_duration_ms', width: 80,
                    render: (v: number) => `${(v || 0).toFixed(0)}ms`,
                  },
                  {
                    title: '时间', dataIndex: 'created_at', width: 160,
                    render: (v: number) => v ? new Date(v).toLocaleString() : '-',
                  },
                ]}
              />
            </TabPane>
          </Tabs>
        </div>
      </div>
    </div>
  );
}
