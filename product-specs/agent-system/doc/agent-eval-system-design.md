# Agent 评测系统整体设计

> 基于 DeepAgent（图状态机编排引擎）现有架构，设计多租户线上评测体系

---

## 〇、评测架构简图

> 先给出最简链路全貌，后续章节再逐层展开。

### 整体评测执行链路

```
┌────────────────────────────────────────────────────────────────────────────┐
│                          评测系统 — 简化架构                                │
└────────────────────────────────────────────────────────────────────────────┘

                         ┌──────────────┐
                         │  评测用例集   │  YAML/DB 存储
                         │  (EvalSuite) │  定义 input + mock 规则 + 断言
                         └──────┬───────┘
                                │ 加载
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     EvalRunner (评测执行引擎)                      │
│                                                                   │
│  1. 构建 Agent（复用 AgentFactory）                               │
│  2. 注入 MockToolGateway（工具拦截中间件，可选）                   │
│  3. 发送测试消息 → Agent 执行推理                                 │
│  4. 采集结构化证据 EvalEvidence                                   │
└───────────────────────────────┬─────────────────────────────────┘
                                │
           ┌────────────────────┼────────────────────┐
           ▼                    ▼                    ▼
┌─────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  Agent 推理链   │  │ MockToolGateway  │  │ TracingMiddleware │
│  (LLM 调用)    │  │ (工具拦截层)      │  │ (链路采集)        │
└────────┬────────┘  └────────┬─────────┘  └────────┬─────────┘
         │                    │                      │
         │           ┌───────┴────────┐              │
         │           │ Mock 数据管理   │              │
         │           │                 │              │
         │           │ • 条件规则匹配  │              │
         │           │ • 状态变更模拟  │              │
         │           │ • 调用日志记录  │              │
         │           └───────┬────────┘              │
         │                   │                       │
         └───────────────────┼───────────────────────┘
                             │ 汇聚为 EvalEvidence
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   AssertionEngine (断言验证引擎)                   │
│                                                                   │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────┐ │
│  │ 规则断言    │ │ 工具调用断言│ │ 状态变更断言│ │ LLM Judge │ │
│  │ contains    │ │ tool_called │ │ state_diff  │ │ 语义评分  │ │
│  │ regex       │ │ call_order  │ │ before/after│ │ 多Judge投票│ │
│  │ json_schema │ │ call_count  │ │             │ │           │ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └───────────┘ │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
                       ┌────────────────┐
                       │  EvalVerdict   │  passed/failed + confidence
                       │  评测报告持久化 │
                       └────────────────┘
```

### Agent 如何接入 Mock Tool

```
正常模式:                           评测模式 (mock/hybrid):
Agent → ToolRegistry → 真实工具     Agent → MockGatewayMiddleware → 拦截判断
                                                    │
                                          ┌─────────┴──────────┐
                                          ▼                    ▼
                                    命中 Mock 规则         未命中 Mock
                                    返回预设数据          放行到真实工具(hybrid)
                                                         或报错(mock)

评测模式 (real):
Agent → ToolRegistry → 真实工具（与正常模式一致，仅增加链路采集）
```

**接入原理：**
- 评测时通过 `config["eval_mode"] = True` 激活 `MockGatewayMiddleware`
- Middleware 在 Agent 的工具调用链路中拦截，**不修改任何现有 Tool 代码**
- 只有在 MockDataset 中声明的工具会被拦截，其余工具按 execution_mode 决定行为
- execution_mode=real 时不注入 MockGatewayMiddleware，走真实调用

---

## 一、用户使用模型

### 1.1 两类用户角色与使用场景

| 维度 | 内部出厂测试 | 租户自行构建 |
|------|------------|-------------|
| 角色 | 平台开发/QA | 租户的 Agent 配置人员 |
| 目标 | Skill/Agent 发版前回归验证 | 优化 prompt/工具编排后验证效果 |
| Mock 偏好 | 大量使用 mock（隔离外部依赖，保证可重复） | 倾向真实调用（验证端到端效果），部分场景用 mock |
| 用例来源 | 手写 + 线上 bad case 沉淀 | Skill 辅助生成 + 手工微调 |
| 断言精度 | 严格（工具调用顺序 + 参数 + 状态变更） | 偏宽松（回复包含关键信息即可） |
| 频率 | CI/CD 自动触发 + 定期批跑 | 改完配置后手动触发 |
| 配置方式 | YAML/API 为主 | 界面配置 + Skill 辅助生成 |

两类用户共享同一套系统，通过**权限 + 用例模板 + 默认配置**区分体验。

---

### 1.2 用例与 Mock 的关系定义

核心模型设计为**三层解耦**：

```
┌─────────────────────────────────────────────────────────┐
│                   EvalSuite（评测集）                     │
│  归属: tenant_id                                         │
│  描述: "订单取消场景回归测试"                              │
│  默认执行模式: mock_mode = full / partial / none         │
└──────────────────────────┬──────────────────────────────┘
                           │ 1:N
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   EvalCase（评测用例）                     │
│  input_message: "帮我取消订单 ORD-001"                   │
│  agent_name / skill_api_key: 指定被测对象                 │
│  mock_dataset_id: → 引用 MockDataset（可选）             │
│  mock_overrides: [ ] → 用例级覆盖（可选）                 │
│  assertions: [ ] → 验证规则                              │
│  execution_mode: mock / real / hybrid                    │
└──────────────────────────┬──────────────────────────────┘
                           │ N:1 (多用例可共享同一 MockDataset)
                           ▼
┌─────────────────────────────────────────────────────────┐
│                 MockDataset（Mock 数据集）                 │
│  归属: tenant_id                                         │
│  名称: "标准订单数据集"                                   │
│  描述: "包含正常订单、已发货订单、不存在订单等场景"         │
│  tools:                                                  │
│    - tool_name: search_order                             │
│      rules: [...]                                        │
│    - tool_name: get_customer_info                        │
│      rules: [...]                                        │
│  version: 3 (可版本化)                                   │
└─────────────────────────────────────────────────────────┘
```

**关系规则：**

| 规则 | 说明 |
|------|------|
| EvalCase 可以不引用 MockDataset | execution_mode=real，走真实工具调用 |
| EvalCase 引用 MockDataset | 该 dataset 中定义的工具被 mock，其余工具按 execution_mode 决定 |
| EvalCase 有 mock_overrides | 覆盖 dataset 中同名工具的规则（用例级特殊数据） |
| 多个 EvalCase 共享同一 MockDataset | 减少重复配置，统一管理 mock 数据 |
| MockDataset 独立版本化 | 改了 mock 数据后可以对比"同用例 + 不同 mock 版本"的结果差异 |

**三种执行模式：**

```
execution_mode = "mock"
  → 所有工具调用都走 MockDataset，未配置的工具调用报错（严格隔离）
  → 适用：内部出厂测试、可重复性要求高的场景

execution_mode = "real"  
  → 所有工具走真实调用，MockDataset 被忽略（端到端验证）
  → 适用：租户验证真实效果、上线前最终确认

execution_mode = "hybrid"（默认）
  → MockDataset 中配置的工具走 mock，未配置的走真实调用
  → 适用：只需隔离部分外部依赖（如第三方 API），其余走真实数据
```

---

### 1.3 Mock 数据配置方式

#### 方式一：手工配置

**入口 A — YAML/API 配置（内部出厂测试为主）**

```yaml
# mock_datasets/order_standard.yaml
name: "标准订单数据集"
description: "覆盖订单查询、取消、修改等场景的 mock 数据"
tools:
  - tool_name: search_order
    rules:
      - when:
          order_id: "ORD-001"
        then:
          data:
            order_id: "ORD-001"
            status: "pending"
            amount: 99.9
            customer_name: "张三"
            items: [{sku: "SKU-A", qty: 2}]
      - when:
          order_id: "ORD-002"
        then:
          data:
            order_id: "ORD-002"
            status: "shipped"
            tracking_no: "SF123456"
      - when:
          order_id:
            op: "regex"
            value: "^ORD-9\\d+"
        then:
          simulate_error: true
          error_message: "订单不存在"
    default_response:
      data: { error: "未找到订单" }

  - tool_name: cancel_order
    rules:
      - when:
          order_id: "ORD-001"
        then:
          data: { success: true, refund_amount: 99.9 }
          side_effects:
            - path: "orders.ORD-001.status"
              value: "cancelled"
      - when:
          order_id: "ORD-002"
        then:
          data: { success: false, reason: "已发货订单不可取消" }
```

**入口 B — 界面配置（租户自行构建为主）**

界面提供表单式配置：
1. 选择工具 → 从 Agent 已绑定的工具列表中选
2. 添加规则 → 可视化配置"当参数为 X 时返回 Y"
3. 预览 → 输入测试参数看 mock 返回什么
4. 保存为 MockDataset → 可命名、可复用

**条件匹配支持的操作符：**

| 操作符 | 说明 | 示例 |
|--------|------|------|
| equals（默认） | 精确匹配 | `order_id: "ORD-001"` |
| contains | 包含子串 | `{op: "contains", value: "VIP"}` |
| regex | 正则匹配 | `{op: "regex", value: "^ORD-\\d+"}` |
| exists | 字段存在即匹配 | `{op: "exists"}` |
| gt / lt / gte / lte | 数值比较 | `{op: "gt", value: 100}` |

#### 方式二：Skill 辅助生成

用户通过对话方式让 Agent 帮助生成评测用例和 mock 数据：

```
用户: 帮我生成"订单取消"场景的评测用例，需要覆盖正常取消、已发货不能取消、订单不存在三种情况

Skill 输出:
├── MockDataset: order_cancel_scenarios
│   ├── search_order: 3条规则（pending / shipped / not_found）
│   └── cancel_order: 2条规则（成功 / 拒绝）
├── EvalCase 1: 正常取消 (input + assertions)
├── EvalCase 2: 已发货拒绝 (input + assertions)
└── EvalCase 3: 订单不存在 (input + assertions)
```

**Skill 生成的工作流：**

```
┌────────────┐     ┌─────────────────┐     ┌──────────────────┐
│ 用户描述   │────→│ 生成 Skill      │────→│ 结构化输出        │
│ 测试场景   │     │ (分析工具链路   │     │ MockDataset       │
│            │     │  推导 mock 数据  │     │ + EvalCase[]      │
│            │     │  生成断言规则)   │     │ + Assertions[]    │
└────────────┘     └─────────────────┘     └────────┬─────────┘
                                                     │
                                                     ▼
                                           ┌──────────────────┐
                                           │ 用户审核/微调     │
                                           │ 确认后保存        │
                                           └──────────────────┘
```

Skill 生成时需要的上下文：
- 被测 Agent / Skill 的名称及其绑定的工具列表
- 场景描述（自然语言）
- 可选：参考真实对话记录 / 线上 bad case

生成结果为"草稿"状态，用户确认后方可执行。

---

### 1.4 最小可用用例定义

用户最少配什么能跑一次评测：

#### 最简配置（真实调用模式）

```yaml
- input: "帮我查一下订单 ORD-001 的状态"
  agent_name: "order_assistant"
  execution_mode: real
  assertions:
    - type: contains_any
      target: final_response
      config:
        expected: ["待支付", "待发货", "已发货", "已完成", "已取消"]
```

用户只需提供：
1. **input**（必填）— 测试输入
2. **agent_name**（必填）— 被测 Agent
3. **至少一条 assertion**（必填）— 怎么算通过

Mock 是可选的。不配 mock 就走真实调用。

#### 配置复杂度阶梯

```
Level 0 — 冒烟测试:
  ✅ input + agent_name + execution_mode=real
  ✅ assertion: response 非空 / 无报错
  用途: 验证 Agent 基本能跑通

Level 1 — 功能验证:
  ✅ input + agent_name + execution_mode=real
  ✅ assertion: contains 关键词 / 调用了指定工具
  用途: 验证 Agent 能正确理解意图并调用工具

Level 2 — 隔离测试:
  ✅ input + agent_name + mock_dataset_id + execution_mode=hybrid
  ✅ assertion: 工具调用参数正确 + 回复内容正确
  用途: 隔离外部依赖，可重复验证

Level 3 — 深度验证:
  ✅ input + mock_dataset_id + execution_mode=mock
  ✅ assertion: 调用顺序 + 参数 + 状态变更 + LLM Judge
  用途: 出厂回归测试，严格验证行为正确性
```

#### 完整用例配置示例

```yaml
# eval_suites/order_cancel_regression.yaml

name: "订单取消场景回归"
description: "覆盖取消订单的正常流程、异常流程、边界情况"
agent_name: "order_assistant"
default_execution_mode: hybrid
mock_dataset_id: "ds_order_standard_v3"

cases:
  - id: "cancel_normal_001"
    description: "正常取消待支付订单"
    input: "我要取消订单 ORD-001"
    execution_mode: mock  # 用例级覆盖
    assertions:
      - type: tool_call_check
        target: tool_calls
        config:
          checks:
            - tool_name: search_order
              called: true
              arguments_match: { order_id: "ORD-001" }
            - tool_name: cancel_order
              called: true
              arguments_match: { order_id: "ORD-001" }
      - type: contains_all
        target: final_response
        config:
          expected: ["已取消", "退款"]
      - type: state_diff
        target: state_snapshots
        config:
          expected:
            "orders.ORD-001.status": "cancelled"

  - id: "cancel_shipped_002"
    description: "已发货订单不可取消"
    input: "取消我的订单 ORD-002"
    assertions:
      - type: tool_call_check
        target: tool_calls
        config:
          checks:
            - tool_name: search_order
              called: true
            - tool_name: cancel_order
              called: false  # 不应该调用取消
      - type: contains_any
        target: final_response
        config:
          expected: ["无法取消", "已发货", "不能取消"]

  - id: "cancel_not_found_003"
    description: "订单不存在"
    input: "帮我取消订单 ORD-99999"
    assertions:
      - type: tool_call_check
        target: tool_calls
        config:
          checks:
            - tool_name: search_order
              called: true
            - tool_name: cancel_order
              called: false
      - type: contains_any
        target: final_response
        config:
          expected: ["不存在", "找不到", "无此订单"]

  - id: "cancel_quality_004"
    description: "取消成功后的回复质量（开放式评测）"
    input: "我不想要了，把 ORD-001 退了吧"
    execution_mode: mock
    assertions:
      - type: llm_judge
        target: final_response
        config:
          criteria:
            - name: correctness
              weight: 2.0
              rubric: "是否准确传达了订单已取消和退款信息"
            - name: helpfulness
              weight: 1.0
              rubric: "是否给出后续操作建议（如退款到账时间）"
            - name: tone
              weight: 0.5
              rubric: "语气是否专业友好"
          pass_threshold: 3.5
          num_judges: 3
```

---

### 1.5 结果判断 — 用户怎么看怎么用

#### 结果状态定义

| 状态 | 含义 | 后续动作 |
|------|------|---------|
| PASSED | 所有断言通过 | 无需操作 |
| FAILED | 至少一条确定性断言未通过 | 查看失败详情，定位原因 |
| UNCERTAIN | LLM Judge 置信度 < 阈值 | 需人工确认判定 |
| ERROR | 执行异常（超时/Agent报错/配置错误） | 检查配置或系统状态 |

#### 结果展示分层

**第一层：Suite 总览**

```
评测集: 订单取消场景回归 v3
执行时间: 2024-03-15 14:23
总用例: 20 | 通过: 16 | 失败: 2 | 待确认: 1 | 错误: 1
通过率: 80% (上次: 85% ↓5%)
平均耗时: 2.1s | 平均 token: 1,240

[查看失败用例]  [待确认用例]  [与上次运行对比]
```

**第二层：用例结果详情**

```
Case-007: cancel_shipped_002 — 已发货订单不可取消
状态: FAILED
输入: "取消我的订单 ORD-002"
Agent 回复: "好的，已为您取消订单 ORD-002"

失败断言:
  ✗ tool_call_check: 期望 cancel_order 未被调用，但实际调用了 1 次
  ✗ contains_any: 期望回复包含 ["无法取消","已发货","不能取消"]，实际未包含
  ✓ tool_call_check: search_order 被调用 ✓

根因提示: Agent 未根据 search_order 返回的 status="shipped" 判断不可取消
建议: 检查 Agent prompt 中是否有"已发货订单不可取消"的规则说明
```

**第三层：执行链路回放**

```
Step 1: [LLM] 理解用户意图 → "用户要取消订单 ORD-002"
        Token: input=320, output=45 | 耗时: 850ms
Step 2: [Tool] search_order({order_id: "ORD-002"})
        ← Mock 返回: {status: "shipped", tracking_no: "SF123456"}
        耗时: 2ms (mock)
Step 3: [LLM] 推理 → 决定执行取消（⚠️ 未检查 status）
        Token: input=580, output=30 | 耗时: 620ms  
Step 4: [Tool] cancel_order({order_id: "ORD-002"})
        ← Mock 返回: {success: false, reason: "已发货订单不可取消"}
        耗时: 1ms (mock)
Step 5: [LLM] 生成回复 → "好的，已为您取消订单 ORD-002"（⚠️ 无视工具返回的失败）
        Token: input=650, output=25 | 耗时: 550ms

总耗时: 2.02s | 总 Token: 1,650
```

#### 失败归因分类

系统自动对失败做初步归因，辅助用户定位：

| 归因类别 | 判断逻辑 | 用户操作建议 |
|---------|---------|-------------|
| Agent 推理错误 | 工具返回了正确信息但 Agent 做了错误决策 | 优化 prompt 或补充推理规则 |
| Agent 遗漏步骤 | 应该调用的工具未调用 | 检查工具描述或 prompt 中的流程说明 |
| Mock 数据问题 | 缺少匹配规则导致返回 default_response | 补充 mock 规则覆盖该场景 |
| 断言过严 | Agent 回复语义正确但措辞不同 | 放宽断言（改用 contains_any）或改用 LLM Judge |
| 工具执行失败 | real 模式下工具真实报错 | 检查工具配置或目标系统状态 |
| 超时 | 执行时间超过用例 timeout | 优化 Agent 链路或调大超时阈值 |

#### 结果后续动作

```
用户看到失败结果后可以:
├── [调整断言] → 修改断言规则，对已有 evidence 重新判定（无需重跑 Agent）
├── [修改 Mock] → 修改 MockDataset 中的规则，重跑该用例
├── [标记误报] → 人工判定 Agent 实际正确，标记为 PASSED 并更新基线
├── [切换模式] → 切换 execution_mode=real 重跑，看真实环境下表现
├── [对比历史] → 对比本次与上次运行结果的 diff
└── [导出报告] → 生成优化建议文档，提交给 Agent 配置人员
```

---

### 1.6 接口返回数据验证方式

评测验证发生在 Agent 执行完毕后，针对 **EvalEvidence（结构化证据）** 进行多维断言：

```
Agent 执行完毕
      │
      ▼
┌─────────────────────────────────────────────────────────┐
│              EvalEvidence（可验证的数据源）                │
│                                                          │
│  ① final_response  — Agent 最终回复文本                  │
│  ② tool_calls[]    — 所有工具调用记录（含参数+返回值）    │
│  ③ state_snapshots — Mock 状态变更快照（before/after）   │
│  ④ trace_spans[]   — 完整推理链路（LLM调用+耗时+token） │
│  ⑤ latency_ms      — 总耗时                             │
│  ⑥ token_usage     — Token 消耗量                       │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼ 断言引擎逐条校验
```

**验证能力总结：**

| 验证层级 | 断言类型 | 验证内容 | 置信度 | 适用场景 |
|---------|---------|---------|--------|---------|
| 回复文本 | contains_all / contains_any / regex / exact_match | Agent 最终输出是否包含期望内容 | 高 | 所有场景 |
| 回复文本 | not_contains | Agent 输出不应包含某些内容 | 高 | 负面验证 |
| 工具调用 | tool_call_check | 是否调用了正确工具、参数是否正确 | 高 | 功能验证 |
| 工具调用 | sequence_check | 工具调用顺序是否正确 | 高 | 流程验证 |
| 返回数据 | json_schema | 工具返回是否符合预期 schema | 高 | 接口验证 |
| 状态变更 | state_diff | Mock 模拟的状态是否被正确修改 | 高 | 写操作验证 |
| 语义质量 | llm_judge | 回复的准确性、有用性、完整性 | 中 | 开放式输出 |
| 性能指标 | numeric_range | 耗时、token 是否在范围内 | 高 | 性能基线 |

**断言规则配置示例：**

```yaml
assertions:
  # 验证最终回复内容
  - type: contains_all
    target: final_response
    config:
      expected: ["已取消", "ORD-001"]

  # 验证工具是否被正确调用
  - type: tool_call_check
    target: tool_calls
    config:
      checks:
        - tool_name: cancel_order
          called: true
          arguments_match: { order_id: "ORD-001" }
          call_count: 1

  # 验证工具调用顺序
  - type: sequence_check
    target: tool_calls
    config:
      expected_order: [search_order, cancel_order]

  # 验证 Mock 状态变更（模拟数据库写入是否正确）
  - type: state_diff
    target: state_snapshots
    config:
      expected:
        "orders.ORD-001.status": "cancelled"

  # 验证工具返回的 JSON 结构
  - type: json_schema
    target: "tool_calls[cancel_order].response"
    config:
      schema:
        type: object
        required: [success, refund_amount]
        properties:
          success: { type: boolean, const: true }
          refund_amount: { type: number, minimum: 0 }

  # 性能基线验证
  - type: numeric_range
    target: latency_ms
    config:
      max: 5000  # 5秒内完成

  # 开放式语义验证
  - type: llm_judge
    target: final_response
    config:
      criteria:
        - name: correctness
          weight: 2.0
          rubric: "回复是否准确反映订单已取消及退款信息"
        - name: helpfulness
          weight: 1.0
          rubric: "是否给出后续操作建议（退款到账时间等）"
      pass_threshold: 3.5
      num_judges: 3
```

---

## 二、与现有系统的关系

### 现有能力盘点

DeepAgent 已有以下可复用的评测基础设施：

| 模块 | 位置 | 可复用能力 |
|-----|------|-----------|
| SkillTestRunner | `src/skills/test_runner.py` | 单 Skill 测试执行、步骤链路采集、Mock 工具、用例验证（关键词/排除词/工具调用/耗时） |
| TracingMiddleware | `src/middleware/tracing.py` | 完整执行链路记录（LLM调用、工具调用、耗时、token） |
| AgentFactory | `src/agents/agent_factory.py` | Agent 构建/缓存/深度控制，支持 test_mode |
| ToolFactory + ToolRegistry | `src/tools/factory.py` | 工具注册/发现/启用控制，支持 mock_tools 注入 |
| RequestContext | `src/core/context.py` | 租户隔离的请求上下文（tenant_id / user_id / thread_id） |
| TraceWriter | `src/store/trace_writer.py` | Trace 持久化（span 链路存储） |
| GraphState | `src/core/state.py` | 完整的 Agent 执行状态（计划/步骤/工具调用/Token计数） |

### 评测系统定位

```
┌──────────────────────────────────────────────────────────────────┐
│                       评测系统 (新增模块)                          │
│  src/eval/                                                        │
│  ┌────────────┐  ┌────────────┐  ┌──────────┐  ┌──────────────┐ │
│  │ EvalRunner │  │ Assertions │  │ Reporter │  │ EvalScheduler│ │
│  │ (执行引擎) │  │ (断言引擎) │  │ (报告)   │  │ (调度)       │ │
│  └─────┬──────┘  └──────┬─────┘  └────┬─────┘  └──────┬───────┘ │
└────────┼────────────────┼─────────────┼────────────────┼─────────┘
         │                │             │                │
─────────┼────────────────┼─────────────┼────────────────┼─────────
         ▼                ▼             ▼                ▼
┌──────────────────────────────────────────────────────────────────┐
│                     现有 DeepAgent 架构                            │
│                                                                    │
│  AgentFactory ──→ LangChain Agent ──→ ToolRegistry + SkillRegistry│
│       │                  │                     │                   │
│       │           TracingMiddleware      MockToolGateway (扩展)    │
│       │                  │                     │                   │
│       └──── GraphState ──┴──── TraceWriter ────┘                  │
│                                                                    │
│  RequestContext (tenant_id 隔离)                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 三、技术架构：评测执行引擎

### 3.1 EvalRunner — 与现有 Agent 运行时的集成

```python
# src/eval/runner.py

class EvalRunner:
    """评测执行引擎 — 复用 AgentFactory 构建 Agent，通过 eval_mode 注入评测基础设施"""

    def __init__(self, agent_factory: AgentFactory, tenant_id: int):
        self._factory = agent_factory
        self._tenant_id = tenant_id

    async def execute(self, eval_case: EvalCase) -> EvalEvidence:
        """执行单条评测用例，返回结构化证据"""

        # 1. 构建评测专用的 RequestContext
        set_context(RequestContext(
            tenant_id=self._tenant_id,
            user_id=f"eval_user_{eval_case.id}",
            thread_id=f"eval_{eval_case.id}_{uuid.uuid4().hex[:8]}",
        ))

        # 2. 准备 Mock Tool Gateway（仅 mock/hybrid 模式）
        mock_gateway = None
        if eval_case.execution_mode in ("mock", "hybrid"):
            mock_configs = self._resolve_mock_configs(eval_case)
            mock_gateway = MockToolGateway(
                mock_configs=mock_configs,
                strict_mode=(eval_case.execution_mode == "mock"),
            )

        # 3. 通过 AgentFactory 构建 Agent（复用现有逻辑）
        agent = await self._factory.build(
            agent_name=eval_case.agent_name or "default",
            current_depth=0,
        )

        # 4. 执行 Agent
        config = {
            "configurable": {
                "thread_id": get_context().thread_id,
                "test_mode": True,
                "skip_memory_extract": True,
                "eval_mode": True,
                "execution_mode": eval_case.execution_mode,
                "mock_gateway": mock_gateway,
                "state_snapshot_enabled": True,
            }
        }

        messages = self._build_messages(eval_case)
        evidence = EvalEvidence(case_id=eval_case.id)
        start_time = time.monotonic()

        try:
            result = await asyncio.wait_for(
                agent.ainvoke({"messages": messages}, config=config),
                timeout=eval_case.timeout_ms / 1000,
            )
            evidence.status = "completed"
            evidence.final_response = self._extract_final_response(result)
        except asyncio.TimeoutError:
            evidence.status = "timeout"
        except Exception as e:
            evidence.status = "error"
            evidence.error_message = str(e)

        # 5. 采集结构化证据
        evidence.latency_ms = (time.monotonic() - start_time) * 1000
        evidence.trace_spans = tracing_middleware.get_spans(get_context().thread_id)
        evidence.token_usage = self._extract_token_usage(evidence.trace_spans)

        if mock_gateway:
            evidence.tool_calls = mock_gateway.get_call_log()
            evidence.state_snapshots = mock_gateway.get_state_snapshots()
        else:
            evidence.tool_calls = self._extract_tool_calls_from_trace(evidence.trace_spans)

        # 6. 清理
        tracing_middleware.clear(get_context().thread_id)
        return evidence

    def _resolve_mock_configs(self, eval_case: EvalCase) -> list[MockToolConfig]:
        """解析 mock 配置：MockDataset + 用例级 overrides"""
        configs = {}

        # 先加载 MockDataset 的规则
        if eval_case.mock_dataset_id:
            dataset = self._load_mock_dataset(eval_case.mock_dataset_id)
            for tool_config in dataset.tools:
                configs[tool_config.tool_name] = tool_config

        # 用例级 overrides 覆盖同名工具
        if eval_case.mock_overrides:
            for override in eval_case.mock_overrides:
                configs[override.tool_name] = override

        return list(configs.values())
```

### 3.2 MockToolGateway — 工具拦截中间件

```python
# src/eval/mock_gateway.py

class MockToolGateway:
    """评测模式下的工具拦截网关

    设计原则：
    1. 不修改现有 Tool 实现，通过 middleware 层拦截
    2. 支持条件匹配（按参数决定返回什么）
    3. 记录所有工具调用作为判断证据
    4. 支持模拟异常（超时/错误）
    5. 支持模拟副作用（状态变更）
    """

    def __init__(self, mock_configs: list[MockToolConfig], strict_mode: bool = False):
        self._mocks: dict[str, MockToolConfig] = {m.tool_name: m for m in mock_configs}
        self._call_log: list[ToolCallRecord] = []
        self._state: dict[str, Any] = {}
        self._strict_mode = strict_mode  # True = 未 mock 的工具报错

    def should_intercept(self, tool_name: str) -> bool:
        """判断是否拦截该工具调用"""
        if tool_name in self._mocks:
            return True
        if self._strict_mode:
            raise MockNotConfiguredError(
                f"严格模式下工具 '{tool_name}' 未配置 mock 数据"
            )
        return False  # hybrid 模式下放行

    def intercept(self, tool_name: str, arguments: dict) -> MockResult:
        """拦截工具调用，返回预设结果"""
        mock_config = self._mocks[tool_name]

        # 记录调用
        record = ToolCallRecord(
            tool_name=tool_name,
            arguments=arguments,
            timestamp=time.time(),
            is_mocked=True,
        )

        # 条件匹配
        response = self._match_response(mock_config, arguments)

        # 模拟副作用
        if response.side_effects:
            for effect in response.side_effects:
                self._apply_side_effect(effect)

        record.response = response.data
        self._call_log.append(record)

        # 模拟错误
        if response.simulate_error:
            record.error = response.error_message
            raise ToolExecutionError(response.error_message)

        return response

    def _match_response(self, config: MockToolConfig, arguments: dict) -> MockResponse:
        """按条件匹配返回值 — 支持多条件规则，顺序匹配"""
        for rule in config.rules:
            if self._arguments_match(arguments, rule.when):
                return rule.then
        return config.default_response

    def _arguments_match(self, actual: dict, expected: dict) -> bool:
        """参数条件匹配"""
        for key, condition in expected.items():
            actual_value = actual.get(key)
            if isinstance(condition, dict):
                op = condition.get("op", "equals")
                expected_val = condition.get("value")
                if op == "equals" and actual_value != expected_val:
                    return False
                elif op == "contains" and expected_val not in str(actual_value):
                    return False
                elif op == "regex" and not re.match(expected_val, str(actual_value)):
                    return False
                elif op == "exists" and actual_value is None:
                    return False
                elif op == "gt" and not (actual_value and actual_value > expected_val):
                    return False
                elif op == "lt" and not (actual_value and actual_value < expected_val):
                    return False
            else:
                if actual_value != condition:
                    return False
        return True

    def _apply_side_effect(self, effect: dict):
        """应用副作用到内部状态"""
        path = effect["path"]
        value = effect["value"]
        self._state[path] = value

    def get_call_log(self) -> list[ToolCallRecord]:
        return self._call_log

    def get_state_snapshots(self) -> dict:
        return self._state
```

### 3.3 集成到现有 Middleware 管道

在 Agent 工具调用链路中条件注入 MockGatewayMiddleware：

```python
# src/eval/mock_gateway_middleware.py

class MockGatewayMiddleware(AgentMiddleware):
    """在 Agent 运行时拦截工具调用，按 execution_mode 决定行为

    工作原理：
    - eval_mode=True 时激活
    - 从 config 获取 mock_gateway 实例
    - 拦截 tool_call：命中 mock → 返回预设结果；未命中 → 放行(hybrid)或报错(mock)
    - real 模式不注入此中间件
    """

    async def __call__(self, state, config, next_fn):
        mock_gateway = config.get("configurable", {}).get("mock_gateway")
        if not mock_gateway:
            return await next_fn(state, config)

        # 检查最近 AI message 中的 tool_calls
        # 对命中 mock 的工具注入 ToolMessage，跳过真实执行
        # 未命中的工具正常执行 next_fn
        ...
        return await next_fn(state, config)
```

**修改点（最小侵入）：**

| 修改文件 | 变更内容 | 影响范围 |
|---------|---------|---------|
| `server.py` | 挂载 `eval_router` | 新增路由，不影响现有 |
| `src/middleware/builder.py` | 条件注入 MockGatewayMiddleware（仅 eval_mode=True） | 不影响正常请求 |
| `src/middleware/tracing.py` | 增加 `get_spans(thread_id)` 公开方法 | 只读接口 |

**设计原则：评测系统作为"旁路观测者"接入，不修改 Agent 核心执行逻辑。**

---

## 四、技术架构：断言引擎

### 4.1 证据数据模型

```python
# src/eval/evidence.py

@dataclass
class EvalEvidence:
    """从 Agent 执行中采集的结构化证据 — 断言引擎的输入"""

    case_id: str = ""
    status: str = ""  # completed / timeout / error

    # 最终输出
    final_response: str = ""

    # 工具调用链路
    tool_calls: list[ToolCallRecord] = field(default_factory=list)

    # 完整 trace spans
    trace_spans: list[dict] = field(default_factory=list)

    # Token 消耗
    token_usage: TokenUsage = field(default_factory=TokenUsage)

    # 延迟
    latency_ms: float = 0.0

    # 状态快照（Mock Gateway 维护的可变状态）
    state_snapshots: dict = field(default_factory=dict)

    # 错误信息
    error_message: str = ""
```

### 4.2 断言引擎

```python
# src/eval/assertions/engine.py

class AssertionEngine:
    """断言执行引擎 — 对 EvalEvidence 执行断言规则"""

    def __init__(self, llm=None):
        self._llm = llm
        self._strategies: dict[str, AssertionStrategy] = {
            "exact_match": ExactMatchStrategy(),
            "contains_all": ContainsAllStrategy(),
            "contains_any": ContainsAnyStrategy(),
            "not_contains": NotContainsStrategy(),
            "regex_match": RegexMatchStrategy(),
            "tool_call_check": ToolCallCheckStrategy(),
            "sequence_check": SequenceCheckStrategy(),
            "json_schema": JsonSchemaStrategy(),
            "state_diff": StateDiffStrategy(),
            "numeric_range": NumericRangeStrategy(),
            "llm_judge": LlmJudgeStrategy(llm),
        }

    async def evaluate(
        self, evidence: EvalEvidence, assertions: list[AssertionRule]
    ) -> EvalVerdict:
        """执行所有断言，返回综合判定"""
        results = []
        for rule in assertions:
            strategy = self._strategies.get(rule.type)
            target_data = self._extract_target(evidence, rule.target)
            result = await strategy.check(target_data, rule.config)
            result.rule = rule
            results.append(result)

        return self._aggregate(results)

    def _extract_target(self, evidence: EvalEvidence, target: str) -> Any:
        """从证据中按路径提取目标数据"""
        if target == "final_response":
            return evidence.final_response
        elif target == "tool_calls":
            return evidence.tool_calls
        elif target == "state_snapshots":
            return evidence.state_snapshots
        elif target == "latency_ms":
            return evidence.latency_ms
        elif target == "token_usage":
            return evidence.token_usage
        elif target.startswith("tool_calls["):
            # 支持 tool_calls[cancel_order].response 格式
            return self._extract_tool_response(evidence.tool_calls, target)
        return None

    def _aggregate(self, results: list[AssertionResult]) -> EvalVerdict:
        """聚合断言结果 — 默认 AND 逻辑"""
        passed = all(r.passed for r in results)
        confidence = min(r.confidence for r in results) if results else 0
        return EvalVerdict(
            passed=passed,
            confidence=confidence,
            assertion_results=results,
            needs_human_review=(confidence < 0.75),
        )
```

### 4.3 LLM Judge 策略

```python
# src/eval/assertions/llm_judge.py

class LlmJudgeStrategy(AssertionStrategy):
    """LLM 语义判断 — 多 Judge 投票保证可靠性"""

    async def check(self, target_data: str, config: dict) -> AssertionResult:
        criteria = config.get("criteria", [])
        pass_threshold = config.get("pass_threshold", 3.5)
        num_judges = config.get("num_judges", 3)

        # 多次调用取中位数
        all_scores = []
        for _ in range(num_judges):
            scores = await self._single_judge(target_data, criteria, config)
            all_scores.append(scores)

        # 对每个维度取中位数
        final_scores = {}
        for criterion in criteria:
            name = criterion["name"]
            values = sorted([s.get(name, 0) for s in all_scores])
            final_scores[name] = values[len(values) // 2]

        # 加权总分
        total_weight = sum(c.get("weight", 1.0) for c in criteria)
        weighted_score = sum(
            final_scores[c["name"]] * c.get("weight", 1.0) for c in criteria
        ) / total_weight

        # 置信度：基于 Judge 间一致性
        max_diff = max(
            max(s.get(c["name"], 0) for s in all_scores) -
            min(s.get(c["name"], 0) for s in all_scores)
            for c in criteria
        ) if criteria else 0
        confidence = max(0.5, 1.0 - (max_diff / 5.0))

        return AssertionResult(
            passed=weighted_score >= pass_threshold,
            score=weighted_score / 5.0,
            reason=f"LLM Judge 评分: {weighted_score:.2f}/5.0 (阈值: {pass_threshold})",
            confidence=confidence,
            detail={"scores": final_scores},
        )
```

---

## 五、技术架构：多租户评测服务

### 5.1 API 路由

```python
# src/api/eval_routes.py

eval_router = APIRouter(prefix="/api/eval", tags=["evaluation"])

# === MockDataset 管理 ===
@eval_router.post("/mock-datasets")
async def create_mock_dataset(req: CreateMockDatasetRequest): ...

@eval_router.get("/mock-datasets")
async def list_mock_datasets(): ...

@eval_router.put("/mock-datasets/{dataset_id}")
async def update_mock_dataset(dataset_id: str, req: UpdateMockDatasetRequest): ...

# === 评测用例管理 ===
@eval_router.post("/suites")
async def create_eval_suite(req: CreateEvalSuiteRequest): ...

@eval_router.post("/suites/{suite_id}/cases")
async def add_eval_case(suite_id: str, req: AddEvalCaseRequest): ...

@eval_router.post("/suites/{suite_id}/cases/generate")
async def generate_cases_by_skill(suite_id: str, req: GenerateCasesRequest):
    """通过 Skill 辅助生成评测用例 + Mock 数据"""
    ...

# === 评测执行 ===
@eval_router.post("/runs")
async def create_eval_run(req: CreateEvalRunRequest):
    """创建评测任务"""
    ...

@eval_router.get("/runs/{run_id}")
async def get_eval_run(run_id: str):
    """查询评测进度"""
    ...

@eval_router.get("/runs/{run_id}/report")
async def get_eval_report(run_id: str):
    """获取评测报告（含失败归因）"""
    ...

@eval_router.post("/runs/{run_id}/rerun-failed")
async def rerun_failed_cases(run_id: str):
    """重跑失败用例"""
    ...

@eval_router.post("/runs/{run_id}/cases/{case_id}/re-evaluate")
async def re_evaluate_case(run_id: str, case_id: str, req: ReEvaluateRequest):
    """修改断言后重新判定（不重跑 Agent）"""
    ...
```

### 5.2 调度引擎

```python
# src/eval/scheduler.py

class EvalScheduler:
    """评测任务调度器 — 并发控制 + 租户隔离"""

    def __init__(self, max_concurrency_per_tenant: int = 5):
        self._semaphores: dict[int, asyncio.Semaphore] = {}

    async def schedule_run(self, run: EvalRun):
        cases = await self._load_cases(run.suite_id)
        sem = self._get_semaphore(run.tenant_id)

        tasks = [
            self._execute_with_semaphore(sem, run, case)
            for case in cases
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        await self._generate_report(run)

    async def _execute_with_semaphore(self, sem, run, case):
        async with sem:
            factory = self._create_eval_factory(run)
            runner = EvalRunner(factory, run.tenant_id)
            evidence = await runner.execute(case)

            engine = AssertionEngine(llm=self._get_judge_llm())
            verdict = await engine.evaluate(evidence, case.assertions)

            await self._save_result(run.id, case.id, evidence, verdict)
```

### 5.3 数据库表设计

```sql
-- 评测相关表（所有表带 tenant_id 实现多租户隔离）

-- Mock 数据集
CREATE TABLE ai_eval_mock_dataset (
    id          BIGINT PRIMARY KEY,
    tenant_id   BIGINT NOT NULL,
    name        VARCHAR(200) NOT NULL,
    description TEXT,
    tools_config JSONB NOT NULL,  -- MockToolConfig 数组
    version     INT DEFAULT 1,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

-- 评测集
CREATE TABLE ai_eval_suite (
    id              BIGINT PRIMARY KEY,
    tenant_id       BIGINT NOT NULL,
    name            VARCHAR(200) NOT NULL,
    description     TEXT,
    agent_name      VARCHAR(100),
    default_execution_mode VARCHAR(20) DEFAULT 'hybrid',
    mock_dataset_id BIGINT REFERENCES ai_eval_mock_dataset(id),
    created_at      TIMESTAMP DEFAULT NOW()
);

-- 评测用例
CREATE TABLE ai_eval_case (
    id              BIGINT PRIMARY KEY,
    tenant_id       BIGINT NOT NULL,
    suite_id        BIGINT NOT NULL REFERENCES ai_eval_suite(id),
    case_key        VARCHAR(100) NOT NULL,  -- 用例标识 如 cancel_normal_001
    description     TEXT,
    input_message   TEXT NOT NULL,
    agent_name      VARCHAR(100),
    execution_mode  VARCHAR(20),  -- 用例级覆盖，NULL 则用 suite 默认
    mock_dataset_id BIGINT,       -- 用例级覆盖
    mock_overrides  JSONB,        -- 用例级 mock 覆盖
    assertions      JSONB NOT NULL,  -- AssertionRule 数组
    timeout_ms      INT DEFAULT 30000,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- 评测运行
CREATE TABLE ai_eval_run (
    id          BIGINT PRIMARY KEY,
    tenant_id   BIGINT NOT NULL,
    suite_id    BIGINT NOT NULL REFERENCES ai_eval_suite(id),
    status      VARCHAR(20) DEFAULT 'queued',  -- queued/running/completed/failed
    total_cases INT DEFAULT 0,
    passed      INT DEFAULT 0,
    failed      INT DEFAULT 0,
    uncertain   INT DEFAULT 0,
    errors      INT DEFAULT 0,
    started_at  TIMESTAMP,
    completed_at TIMESTAMP,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- 评测结果（每条用例的执行结果）
CREATE TABLE ai_eval_result (
    id          BIGINT PRIMARY KEY,
    tenant_id   BIGINT NOT NULL,
    run_id      BIGINT NOT NULL REFERENCES ai_eval_run(id),
    case_id     BIGINT NOT NULL REFERENCES ai_eval_case(id),
    status      VARCHAR(20) NOT NULL,  -- passed/failed/uncertain/error
    evidence    JSONB NOT NULL,   -- EvalEvidence 完整数据
    verdict     JSONB NOT NULL,   -- EvalVerdict 判定详情
    failure_reason VARCHAR(50),   -- 归因分类
    human_override VARCHAR(20),   -- 人工覆盖判定
    created_at  TIMESTAMP DEFAULT NOW()
);
```

---

## 六、完整数据流

```
┌─────────────┐       ┌─────────────┐       ┌──────────────────┐
│ 前端/API    │──────→│ EvalService  │──────→│ EvalScheduler    │
│ 创建评测任务 │       │ 参数校验     │       │ 并发控制+租户隔离 │
└─────────────┘       └─────────────┘       └────────┬─────────┘
                                                      │
                                    ┌─────────────────┴───────────────────┐
                                    ▼                                      ▼
                          ┌──────────────────┐                 ┌──────────────────┐
                          │ EvalRunner (用例1)│                 │ EvalRunner (用例N)│
                          └────────┬─────────┘                 └────────┬─────────┘
                                   │                                     │
                    ┌──────────────┴─────────────────┐                   │
                    ▼                                 ▼                   ▼
           ┌────────────────┐              ┌──────────────────┐
           │ AgentFactory   │              │ MockToolGateway  │
           │ (复用现有逻辑) │              │ (按 mode 决定)   │
           └───────┬────────┘              └────────┬─────────┘
                   │                                 │
                   ▼                                 │
           ┌────────────────┐                        │
           │ LangChain Agent│◄───────────────────────┘
           │ + Middleware   │  mock/hybrid: 拦截部分工具
           │ + Tracing      │  real: 不拦截，全部走真实调用
           └───────┬────────┘
                   │
                   ▼
           ┌────────────────┐
           │ EvalEvidence   │ ← 结构化证据
           └───────┬────────┘
                   │
                   ▼
           ┌────────────────┐
           │AssertionEngine │ ← 多策略断言
           └───────┬────────┘
                   │
                   ▼
           ┌────────────────┐
           │ EvalVerdict    │ ← passed/failed + confidence + 归因
           └───────┬────────┘
                   │
                   ▼
           ┌────────────────┐
           │ 持久化 + 报告  │
           └────────────────┘
```

---

## 七、新增模块目录结构

```
src/eval/
├── __init__.py
├── runner.py                  # EvalRunner — 单用例执行引擎
├── scheduler.py               # EvalScheduler — 批量调度 + 并发控制
├── service.py                 # EvalService — 业务逻辑层
├── evidence.py                # 数据模型（EvalEvidence / EvalCase / EvalRun / MockDataset）
├── mock_gateway.py            # MockToolGateway — 工具拦截 + 状态模拟
├── mock_gateway_middleware.py # LangChain Middleware 适配层
├── adapter.py                 # 兼容旧 TestCase 格式
├── assertions/
│   ├── __init__.py
│   ├── engine.py              # AssertionEngine — 断言调度
│   ├── base.py                # AssertionStrategy 基类
│   ├── rule_strategies.py     # 规则断言（exact_match/contains/regex/schema/numeric）
│   ├── tool_strategies.py     # 工具调用断言（tool_call_check/sequence_check）
│   ├── state_strategies.py    # 状态变更断言（state_diff）
│   └── llm_judge.py           # LLM Judge（多投票 + 校准）
└── report/
    ├── __init__.py
    ├── generator.py           # 报告生成（含失败归因）
    └── templates.py           # 报告模板

src/api/
├── eval_routes.py             # 评测 API 路由

src/store/
├── eval_dao.py                # 评测相关 DAO

sql/
├── eval_tables.sql            # 表 DDL
```

---

## 八、评测可靠性保障

### 8.1 确定性分级

```yaml
determinism_levels:
  high:      # 结果可枚举
    strategies: [exact_match, json_schema, tool_call_check]
    confidence_floor: 0.95
    example: "查询订单状态 → 必须返回 status=pending"

  medium:    # 结果有约束但不唯一
    strategies: [contains_all, tool_call_check, sequence_check]
    confidence_floor: 0.85
    example: "取消订单 → 必须调用 cancel_order + 回复包含'已取消'"

  low:       # 开放式输出
    strategies: [llm_judge]
    confidence_floor: 0.70
    human_review_rate: 0.3
    example: "给出销售建议 → LLM Judge 按 rubric 评分"
```

### 8.2 LLM Judge 校准闭环

```
自动评测 → 低置信结果 → 人工标注队列 → 标注结果回流
                                           │
                ┌──────────────────────────┘
                ▼
    Judge Prompt 优化（agreement < 0.80 时触发）
    Judge 模型切换（成本/质量不达标时）
    断言规则补充（能用规则覆盖则优先规则）
```

### 8.3 评测结果可追溯

每条评测结果保存完整的：
- Agent 输入（用户消息 + 上下文）
- Agent 输出（最终回复）
- 完整 trace（所有 LLM 调用 + 工具调用 + 参数 + 返回值）
- Mock 状态快照（before/after）
- 断言执行详情（每条断言的判定理由）
- LLM Judge 原始响应（可审计）

---

## 九、实施路径

### Phase 1: 基础评测能力（2-3 周）
- [ ] `src/eval/` 模块骨架 + 数据模型
- [ ] MockDataset CRUD（API + 存储）
- [ ] EvalRunner 接入 AgentFactory（支持 real/mock/hybrid 三种模式）
- [ ] MockToolGateway 实现（条件匹配 + 状态模拟）
- [ ] 规则断言策略（contains / tool_call_check / json_schema / numeric_range）
- [ ] 基础 API（创建用例 + 执行 + 查看结果）
- [ ] 兼容现有 SkillTestRunner.TestCase 格式

### Phase 2: 智能评分 + 批量调度（2-3 周）
- [ ] LLM Judge 断言 + 多 Judge 投票
- [ ] EvalScheduler 并发控制 + 租户隔离
- [ ] 评测报告生成（含失败归因）
- [ ] 结果对比能力（跨 run 对比）
- [ ] Skill 辅助生成用例 + Mock 数据

### Phase 3: 产品化 + 运营（2-3 周）
- [ ] 界面化配置（MockDataset / EvalCase / 断言规则）
- [ ] 执行链路回放界面
- [ ] 人工标注队列 + Judge 校准
- [ ] CI/CD webhook 触发支持
- [ ] 平台预置 MockDataset 模板（租户可继承）

---

## 十、待确认设计细节

1. **Real 模式下的数据安全** — 真实工具会读写租户数据，评测调用是否需要加标记（如 `is_eval=true`），让工具层面可选择只读/干跑（dry-run）？
2. **Skill 生成的审批流** — 生成结果是"草稿"需人工确认后才能执行，还是允许直接执行？
3. **Mock 数据集的共享** — 是否支持"平台预置 MockDataset"，租户可以继承/覆盖？
4. **评测触发方式** — 除手动触发外，是否需要支持 CI/CD webhook + 发版阻断？
5. **结果保留策略** — EvalEvidence 数据量较大（含完整 trace），保留多久？是否按 run 归档？
