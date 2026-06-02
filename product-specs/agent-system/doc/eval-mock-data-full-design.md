# MockData 存储与使用全链路 + 工具 Mock 可行性分析

> 基于 agent-system 现有工具体系（ToolFactory 注册的 25 个工具），完整设计 Mock 数据的存储、配置、加载、匹配、以及每个工具的 Mock 可行性判定。

---

## 一、数据库存储结构

### 1.1 三表结构

```
┌────────────────────────────────────────────────────────────────────────┐
│                        ai_eval_mock_dataset (Mock 数据集)                │
├────────────────────────────────────────────────────────────────────────┤
│ id            │ BIGINT PK                                              │
│ tenant_id     │ BIGINT        — 租户隔离                               │
│ name          │ VARCHAR(200)  — "订单场景-外部依赖Mock"                 │
│ description   │ TEXT          — 用途描述                               │
│ version       │ INT           — 版本号，每次修改 +1                     │
│ status        │ VARCHAR(20)   — draft / active / archived              │
│ created_by    │ BIGINT        — 创建人                                 │
│ created_at    │ TIMESTAMP                                              │
│ updated_at    │ TIMESTAMP                                              │
└────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ 1:N
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   ai_eval_mock_tool (单个工具的 Mock 配置)               │
├────────────────────────────────────────────────────────────────────────┤
│ id            │ BIGINT PK                                              │
│ dataset_id    │ BIGINT FK → ai_eval_mock_dataset                       │
│ tenant_id     │ BIGINT                                                 │
│ tool_name     │ VARCHAR(100)  — "call_payment_api"                     │
│ mock_reason   │ VARCHAR(500)  — "第三方支付，不能真实调用"               │
│ default_response │ JSONB      — 无规则匹配时的默认返回                   │
│ sort_order    │ INT           — 排序（展示用）                          │
└────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ 1:N
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   ai_eval_mock_rule (匹配规则)                           │
├────────────────────────────────────────────────────────────────────────┤
│ id            │ BIGINT PK                                              │
│ mock_tool_id  │ BIGINT FK → ai_eval_mock_tool                          │
│ tenant_id     │ BIGINT                                                 │
│ rule_name     │ VARCHAR(200)  — "正常退款" / "余额不足"                 │
│ priority      │ INT           — 匹配优先级（从高到低）                   │
│ conditions    │ JSONB         — 匹配条件                               │
│ response_data │ JSONB         — 匹配成功时返回的数据                    │
│ side_effects  │ JSONB         — 副作用定义（状态变更）                   │
│ simulate_error│ BOOLEAN       — 是否模拟异常                            │
│ error_message │ VARCHAR(500)  — 异常信息                               │
│ delay_ms      │ INT           — 模拟延迟（可选）                        │
└────────────────────────────────────────────────────────────────────────┘
```

### 1.2 示例数据

```
ai_eval_mock_dataset:
  id=1001, tenant_id=100, name="订单取消-外部依赖Mock", version=3

ai_eval_mock_tool:
  id=2001, dataset_id=1001, tool_name="call_payment_api", mock_reason="第三方支付"
  id=2002, dataset_id=1001, tool_name="send_notification", mock_reason="短信通知"

ai_eval_mock_rule:
  id=3001, mock_tool_id=2001, rule_name="正常退款",    priority=10
    conditions={"order_id": "ORD-001", "action": "refund"}
    response_data={"success": true, "refund_id": "RF-001", "amount": 99.9}

  id=3002, mock_tool_id=2001, rule_name="余额不足",    priority=20
    conditions={"order_id": "ORD-002", "action": "refund"}
    response_data={"success": false, "error": "余额不足"}
    simulate_error=false

  id=3003, mock_tool_id=2001, rule_name="支付超时",    priority=30
    conditions={"action": {"op": "exists"}}
    simulate_error=true, error_message="Payment gateway timeout"
    delay_ms=5000
```

---

## 二、用户配置入口

### 入口一：界面配置（租户用户为主）

```
┌─────────────────────────────────────────────────────────────────┐
│  Mock 数据集管理                                     [+ 新建数据集]│
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  📦 订单取消-外部依赖Mock  v3  (active)                           │
│  └── 包含 2 个工具 Mock，5 条规则                                 │
│                                                                   │
│  📦 客服咨询-知识库Mock    v1  (draft)                            │
│  └── 包含 1 个工具 Mock，3 条规则                                 │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

点击进入数据集详情：

```
┌─────────────────────────────────────────────────────────────────┐
│  📦 订单取消-外部依赖Mock                                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─ 工具列表 ──────────────────────────────────────────────────┐ │
│  │                                                              │ │
│  │  🔧 call_payment_api         [编辑] [删除]                   │ │
│  │     原因: 第三方支付接口                                      │ │
│  │     规则: 3 条                                               │ │
│  │     默认返回: {"success": true, "refund_id": "RF-DEFAULT"}   │ │
│  │                                                              │ │
│  │  🔧 send_notification        [编辑] [删除]                   │ │
│  │     原因: 短信/邮件通知                                       │ │
│  │     规则: 2 条                                               │ │
│  │     默认返回: {"sent": true}                                 │ │
│  │                                                              │ │
│  │  [+ 添加工具]  ← 弹出选择器，列出该 Agent 绑定的所有工具      │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

点击编辑某个工具的规则配置：

```
┌─────────────────────────────────────────────────────────────────┐
│  🔧 call_payment_api 规则配置                                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  默认返回（无规则匹配时）:                                         │
│  ┌──────────────────────────────────────────────────────┐        │
│  │ {"success": true, "refund_id": "RF-DEFAULT"}         │        │
│  └──────────────────────────────────────────────────────┘        │
│                                                                   │
│  匹配规则（按优先级从高到低）:                                     │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │ 规则1: 正常退款                              优先级: 10  [编辑]││
│  │ 当: order_id = "ORD-001" 且 action = "refund"                ││
│  │ 返回: {"success": true, "refund_id": "RF-001", amount: 99.9}││
│  ├──────────────────────────────────────────────────────────────┤│
│  │ 规则2: 余额不足                              优先级: 20  [编辑]││
│  │ 当: order_id = "ORD-002" 且 action = "refund"                ││
│  │ 返回: {"success": false, "error": "余额不足"}                ││
│  ├──────────────────────────────────────────────────────────────┤│
│  │ 规则3: 支付超时                              优先级: 30  [编辑]││
│  │ 当: action 存在（兜底）                                       ││
│  │ 行为: 模拟异常 "Payment gateway timeout"  延迟: 5000ms       ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                   │
│  [+ 添加规则]                                                     │
│                                                                   │
│  ── 测试区 ──────────────────────────────────────────────────── │
│  输入参数: {"order_id": "ORD-001", "action": "refund"}  [测试]   │
│  命中规则: "正常退款"                                             │
│  返回结果: {"success": true, "refund_id": "RF-001", amount: 99.9}│
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 入口二：API 批量配置（内部出厂测试为主）

```json
POST /api/eval/mock-datasets
{
  "name": "订单取消-外部依赖Mock",
  "tools": [
    {
      "tool_name": "call_payment_api",
      "mock_reason": "第三方支付接口",
      "default_response": {"success": true, "refund_id": "RF-DEFAULT"},
      "rules": [
        {
          "rule_name": "正常退款",
          "priority": 10,
          "conditions": {"order_id": "ORD-001", "action": "refund"},
          "response_data": {"success": true, "refund_id": "RF-001"}
        }
      ]
    }
  ]
}
```

### 入口三：Skill 辅助生成

```
用户: "帮我为订单取消场景生成 Mock 数据，call_payment_api 和 send_notification 需要 mock"

Skill 分析:
1. 查看 call_payment_api 工具的参数 schema 和返回 schema
2. 推导合理的测试数据（正常/异常/边界）
3. 生成 MockDataset 草稿 → 写入 DB（status=draft）
4. 返回给用户确认

用户确认后: status → active
```

---

## 三、Agent 评测时如何使用这些数据

### 完整链路

```
┌────────────┐
│ 评测触发    │  用户点击"运行评测" / API 调用 / CI 触发
└─────┬──────┘
      │
      ▼
┌────────────────────────────────────────────────────────────────┐
│ Step 1: 加载用例及关联的 MockDataset                             │
│                                                                  │
│  EvalCase:                                                       │
│    mock_dataset_id = 1001                                        │
│    mock_overrides = [...]  (可选的用例级覆盖)                     │
│                                                                  │
│  → 查询 DB:                                                      │
│    SELECT * FROM ai_eval_mock_tool WHERE dataset_id = 1001       │
│    SELECT * FROM ai_eval_mock_rule WHERE mock_tool_id IN (...)   │
│                                                                  │
│  → 组装为内存结构:                                                │
│    MockDataset {                                                  │
│      tools: {                                                    │
│        "call_payment_api": MockToolConfig { rules: [...] }       │
│        "send_notification": MockToolConfig { rules: [...] }      │
│      }                                                           │
│    }                                                             │
└────────────────────────────────┬───────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Step 2: 构建 MockToolGateway 实例                                │
│                                                                  │
│  gateway = MockToolGateway(                                      │
│      mock_configs = dataset.tools,     ← 从 DB 加载的配置        │
│      overrides = eval_case.mock_overrides,  ← 用例级覆盖         │
│      strict_mode = (execution_mode == "isolated"),               │
│  )                                                               │
│                                                                  │
│  gateway 内部构建索引:                                            │
│    _mocks = {                                                    │
│      "call_payment_api": MockToolConfig(rules=[...], default=...)│
│      "send_notification": MockToolConfig(rules=[...], default=...)│
│    }                                                             │
└────────────────────────────────┬───────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Step 3: Agent 执行中的工具调用拦截                                │
│                                                                  │
│  Agent 推理 → 决定调用 call_payment_api(order_id="ORD-001",      │
│                                          action="refund")        │
│       │                                                          │
│       ▼                                                          │
│  MockToolGateway.intercept():                                    │
│                                                                  │
│    1. 查找: "call_payment_api" 在 _mocks 中？ → ✅ 是            │
│                                                                  │
│    2. 规则匹配（按 priority 排序遍历）:                            │
│       规则1 conditions: {order_id: "ORD-001", action: "refund"}  │
│       实际参数:          {order_id: "ORD-001", action: "refund"}  │
│       → 匹配成功 ✓                                               │
│                                                                  │
│    3. 返回 response_data:                                        │
│       {"success": true, "refund_id": "RF-001", "amount": 99.9}  │
│                                                                  │
│    4. 执行 side_effects（如有）:                                  │
│       gateway._state["orders.ORD-001.status"] = "cancelled"      │
│                                                                  │
│    5. 记录调用日志:                                               │
│       call_log.append({                                          │
│         tool_name: "call_payment_api",                           │
│         arguments: {order_id: "ORD-001", action: "refund"},      │
│         response: {success: true, ...},                          │
│         is_mocked: true,                                         │
│         matched_rule: "正常退款",                                 │
│         timestamp: 1710000000                                    │
│       })                                                         │
│                                                                  │
│    6. 返回给 Agent → Agent 继续推理                               │
└────────────────────────────────┬───────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Step 4: 非 Mock 工具的处理                                       │
│                                                                  │
│  Agent 推理 → 决定调用 search_order(order_id="ORD-001")          │
│       │                                                          │
│       ▼                                                          │
│  MockToolGateway.should_intercept():                             │
│                                                                  │
│    "search_order" 在 _mocks 中？ → ❌ 否                         │
│                                                                  │
│    execution_mode = "integrated":                                │
│      → 放行，调用真实工具                                         │
│      → 真实工具返回: {status: "pending", amount: 99.9}           │
│      → 记录日志: {tool_name: "search_order", is_mocked: false}   │
│                                                                  │
│    execution_mode = "isolated" (如果是这个模式):                   │
│      → 报错: "search_order 未配置 mock 数据"                      │
│      → 评测中止或标记为配置错误                                    │
└────────────────────────────────┬───────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Step 5: 执行完毕，Gateway 数据汇入 Evidence                      │
│                                                                  │
│  evidence.tool_calls = gateway.get_call_log()                    │
│  → [                                                             │
│      {tool: "search_order",     is_mocked: false, response: ...} │
│      {tool: "call_payment_api", is_mocked: true,  matched: "正常退款"}│
│      {tool: "send_notification",is_mocked: true,  matched: "默认"}│
│    ]                                                             │
│                                                                  │
│  evidence.state_snapshots = gateway.get_state()                  │
│  → {"orders.ORD-001.status": "cancelled"}                       │
│                                                                  │
│  → 断言引擎可以验证:                                              │
│    • 某工具是否被 mock 了（is_mocked 字段）                       │
│    • mock 命中了哪条规则（matched_rule 字段）                     │
│    • 真实工具返回了什么（response 字段）                           │
│    • 状态变更是否正确（state_snapshots）                           │
└────────────────────────────────────────────────────────────────┘
```

---

## 四、规则匹配的详细逻辑

```
工具调用进入 Gateway
      │
      ▼
从 _mocks 取出该工具的规则列表（已按 priority 排序）
      │
      ▼
┌─── 遍历规则 ─────────────────────────────────────────────┐
│                                                            │
│  规则 conditions: {"order_id": "ORD-001",                 │
│                    "amount": {"op": "gt", "value": 50}}   │
│  实际 arguments:  {"order_id": "ORD-001",                 │
│                    "amount": 99.9, "action": "refund"}    │
│                                                            │
│  匹配逻辑:                                                 │
│    对 conditions 中每个 key 逐一检查:                       │
│                                                            │
│    order_id: "ORD-001"                                     │
│      → actual["order_id"] == "ORD-001" ? ✓                │
│                                                            │
│    amount: {"op": "gt", "value": 50}                       │
│      → actual["amount"] > 50 ? → 99.9 > 50 ✓             │
│                                                            │
│    所有条件都满足 → 该规则命中                              │
│    返回该规则的 response_data                               │
│                                                            │
│  注意:                                                     │
│    • conditions 中未出现的 key（如 action）不做检查          │
│    • 只要 conditions 列的字段全部满足就算命中               │
│    • 第一条命中就返回（priority 高的先匹配）               │
│                                                            │
└──── 全部规则都不命中 → 返回 default_response ─────────────┘
```

**条件匹配支持的操作符：**

| 操作符 | 说明 | 示例 |
|--------|------|------|
| equals（默认） | 精确匹配 | `order_id: "ORD-001"` |
| contains | 包含子串 | `{op: "contains", value: "VIP"}` |
| regex | 正则匹配 | `{op: "regex", value: "^ORD-\\d+"}` |
| exists | 字段存在即匹配 | `{op: "exists"}` |
| gt / lt / gte / lte | 数值比较 | `{op: "gt", value: 100}` |

---

## 五、数据加载的性能考虑

评测批跑时同一个 MockDataset 可能被 20-100 条用例引用：

```
┌─────────────────────────────────────────────────────────┐
│ EvalScheduler                                            │
│                                                          │
│  开始批跑 Suite (20 条用例，都引用 dataset_id=1001)       │
│                                                          │
│  Step 1: 预加载 — 一次性查 DB                            │
│    dataset_cache[1001] = load_from_db(1001)              │
│    → 1 次 DB 查询，加载到内存                            │
│                                                          │
│  Step 2: 每条用例执行时                                  │
│    gateway = MockToolGateway(                            │
│      mock_configs = dataset_cache[1001].tools,  ← 内存   │
│      overrides = case.mock_overrides,                    │
│    )                                                     │
│    → 不再查 DB，直接用缓存                               │
│                                                          │
│  Step 3: 用例级 overrides 合并                           │
│    如果 case 有 mock_overrides:                          │
│      覆盖 dataset 中同名工具的规则                        │
│      不影响其他用例（每个 gateway 是独立实例）            │
└─────────────────────────────────────────────────────────┘
```

---

## 六、工具 Mock 可行性全景分析

> 基于 `src/tools/factory.py` 中 `ToolFactory._register_builtin_classes()` 注册的所有工具。

### 分类标准

| Mock 类别 | 含义 | 评测策略 |
|---|---|---|
| 🟢 **推荐 Mock** | 有外部依赖/副作用/不确定性，Mock 后评测可重复 | 默认 mock，hybrid/isolated 都应 mock |
| 🟡 **可选 Mock** | 内部数据源，可 mock 也可真实调用 | hybrid 可放行；isolated 必须 mock |
| � **不用 Mock** | 评测场景中不涉及/不需要 mock 的工具 | 任何模式都真实调用或不使用 |
| �🔴 **不应 Mock** | 交互类/编排类工具，mock 会破坏 Agent 推理链路 | 任何模式都不 mock |
| ⛔ **评测禁用** | 评测场景中禁止调用的工具 | MockGateway 直接拦截并报错 |

---

### 6.1 CRM 业务工具（6 个）

| # | tool_name | 代码位置 | Mock 判定 | 理由 | Mock 时 conditions 建议 |
|---|---|---|---|---|---|
| 1 | `query_schema` | `src/tools/crm_tools.py` → QuerySchemaTool | 🟡 可选 Mock | 后端是 `CrmSimulatedBackend`（内存模拟），无外部依赖；但评测中 schema 返回需稳定 | `{query_type, entity_api_key}` |
| 2 | `query_data` | `src/tools/crm_tools.py` → QueryDataTool | 🟡 可选 Mock | 后端是 `CrmSimulatedBackend`，数据确定性高；但测试特定场景时 mock 更精确 | `{action, entity_api_key, record_id, filters.*}` |
| 3 | `modify_data` | `src/tools/crm_tools.py` → ModifyDataTool | 🟢 **推荐 Mock** | 有副作用（create/update/delete 会改变内部状态），Mock 保证评测幂等 | `{action, entity_api_key, record_id}` |
| 4 | `analyze_data` | `src/tools/crm_tools.py` → AnalyzeDataTool | 🟡 可选 Mock | 后端模拟，计算确定；但特定聚合场景 mock 可控制精确返回 | `{entity_api_key, metrics[0].function, group_by}` |
| 5 | `ask_user` | `src/tools/crm_tools.py` → AskUserTool | 🔴 **不应 Mock** | 评测中需模拟用户回复，应由 EvalRunner 预设 turns 注入，不走 MockGateway | — |
| 6 | `ask_clarification` | `src/tools/crm_tools.py` → AskClarificationTool | 🔴 **不应 Mock** | 同上，Agent 追问行为本身是评测验证目标 | — |

> **注意**: `modify_data` 在评测中需 mock 是因为写操作会改变 CrmSimulatedBackend 内部状态，导致后续用例数据不一致。

---

### 6.2 记忆工具（2 个）

| # | tool_name | 代码位置 | Mock 判定 | 理由 | Mock 时 conditions 建议 |
|---|---|---|---|---|---|
| 7 | `manage_memory` | `src/tools/crm_tools.py` → ManageMemoryTool | 🟢 **推荐 Mock** | 依赖 VikingMemoryEngine（腾讯云向量 DB），外部 infra；且 list/delete 有副作用 | `{action, keyword, dimension}` |
| 8 | `memory_read` | `src/tools/crm_tools.py` → MemoryReadTool | 🟢 **推荐 Mock** | 依赖 VikingMemoryEngine，且返回值随记忆积累变化，不可重复 | `{memory_id, level}` |

---

### 6.3 Metarepo 元数据工具（2 个）

| # | tool_name | 代码位置 | Mock 判定 | 理由 | Mock 时 conditions 建议 |
|---|---|---|---|---|---|
| 9 | `browse_metamodel` | `src/tools/metarepo_tools.py` → BrowseMetamodelTool | 🟡 可选 Mock | 后端可能是 `MetarepoHttpBackend`（真实 HTTP）或 Simulated；HTTP 模式有外部依赖 | `{query_type, metamodel_api_key}` |
| 10 | `query_metadata` | `src/tools/metarepo_tools.py` → QueryMetadataTool | 🟡 可选 Mock | 同上，HTTP 模式依赖 paas-platform-service；Simulated 模式无外部依赖 | `{metamodel_api_key, entity_api_key, api_key}` |

> **判定规则**: 如果部署环境配置了 `PAAS_BASE_URL`（走 HTTP backend），则推荐 Mock；如果走 SimulatedBackend，可不 Mock。

---

### 6.4 知识库工具（3 个）

| # | tool_name | 代码位置 | Mock 判定 | 理由 | Mock 时 conditions 建议 |
|---|---|---|---|---|---|
| 11 | `knowledge_search` | `src/tools/knowledge_tools.py` → KnowledgeSearchAdapterTool | � **不用 Mock** | 知识库检索是 Agent 核心能力之一，评测应验证真实检索效果；配合 Skill 资源预加载 | — |
| 12 | `list_knowledge_bases` | `src/tools/knowledge_tools.py` → ListKnowledgeBasesTool | � **不用 Mock** | 列出知识库是轻量只读操作，返回值应反映真实环境配置 | — |
| 13 | `knowledge_doc_detail` | `src/tools/knowledge_tools.py` → KnowledgeDocDetailAdapterTool | � **不用 Mock** | 文档详情读取是 knowledge_search 的延伸，应验证完整检索→详情链路 | — |c

---

### 6.5 技能管理工具（2 个）

| # | tool_name | 代码位置 | Mock 判定 | 理由 | Mock 时 conditions 建议 |
|---|---|---|---|---|---|
| 14 | `manage_skill` | `src/tools/manage_skill_tool.py` → ManageSkillTool | ⛔ **评测禁用** | 写 DB（ai_skill / ai_skill_definition），有强副作用；评测场景中禁止调用此工具，防止污染技能数据 | — |
| 15 | `read_skill_resource` | `src/tools/skill_resource_tool.py` → ReadSkillResourceTool | 🔵 **不用 Mock** | 读 DB（ai_skill_resource），无副作用；技能资源是 Agent 执行的基础配置，应验证真实读取链路 | — |

---

### 6.6 文件上传工具（1 个）

| # | tool_name | 代码位置 | Mock 判定 | 理由 | Mock 时 conditions 建议 |
|---|---|---|---|---|---|
| 16 | `file_upload` | `src/tools/file_upload_tool.py` → FileUploadTool | � **不用 Mock** | 文件上传是 Agent 输出能力的一部分，评测中如触发则真实执行以验证完整链路 | — |p

---

### 6.7 Web 搜索工具（1 个）

| # | tool_name | 代码位置 | Mock 判定 | 理由 | Mock 时 conditions 建议 |
|---|---|---|---|---|---|
| 17 | `web_search` | `src/tools/web_search.py` → WebSearchTool | � **不用 Mock** | Web 搜索是 Agent 获取实时信息的能力，评测中真实调用以验证搜索结果整合能力 | — |e

---

### 6.8 沙盒工具（5 个）

| # | tool_name | 代码位置 | Mock 判定 | 理由 | Mock 时 conditions 建议 |
|---|---|---|---|---|---|
| 18 | `terminal` | `src/tools/sandbox/` → TerminalTool | 🟢 **推荐 Mock** | 依赖远程 SSH 沙盒（外部 infra）；有副作用（执行命令改变环境）；安全风险 | `{command}` |
| 19 | `execute_code` | `src/tools/sandbox/` → CodeExecutionTool | 🟢 **推荐 Mock** | 同上，沙盒执行代码；结果可能不确定（网络/时间依赖） | `{language, code}` |
| 20 | `read_file` | `src/tools/sandbox/` → ReadFileTool | � **不用 Mock** | 沙盒文件读取是 Skill 执行链路的一部分，评测中真实读取以验证脚本产出 | — |
| 21 | `write_file` | `src/tools/sandbox/` → WriteFileTool | 🟢 **推荐 Mock** | 有副作用（创建/修改远程文件）；依赖沙盒 infra | `{file_path}` |
| 22 | `search_files` | `src/tools/sandbox/` → SearchFilesTool | � **不用 Mock** | 沙盒文件搜索是只读操作，评测中真实搜索以验证文件定位能力 | — |y

---

### 6.9 AgentFactory 动态注册工具（3 个）

| # | tool_name | 代码位置 | Mock 判定 | 理由 | Mock 时 conditions 建议 |
|---|---|---|---|---|---|
| 23 | `skills_tool` | `src/tools/skills_tool.py` → SkillsTool | 🔴 **不应 Mock** | 编排层工具，Mock 会阻断 Skill 执行链路；应 Mock 的是 Skill 内部调用的业务工具 | — |
| 24 | `agent_tool` | `src/tools/agent_tool.py` → AgentTool | 🔴 **不应 Mock** | 同上，编排层工具，Mock 会破坏多 Agent 协作链路 | — |
| 25 | `ask_user` (builtin) | `src/tools/builtins/ask_user_tool.py` → AskUserTool | 🔴 **不应 Mock** | 用户交互由 EvalRunner 的 turns 机制接管 | — |

---

### 6.10 汇总统计

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Mock 分类汇总                                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  🟢 推荐 Mock（6 个）— 外部依赖/副作用/不确定性                      │
│  ─────────────────────────────────────────────                      │
│  modify_data         写 CRM（副作用，改变内部状态）                  │
│  manage_memory       写向量 DB + 外部 infra                          │
│  memory_read         读向量 DB（外部 infra + 不确定性）               │
│  terminal            远程沙盒命令（外部 infra + 副作用 + 安全）       │
│  execute_code        远程沙盒代码（外部 infra + 副作用）              │
│  write_file          远程沙盒文件（外部 infra + 副作用）              │
│                                                                     │
│  🟡 可选 Mock（5 个）— 内部数据源，可 mock 也可真实                  │
│  ─────────────────────────────────────────────                      │
│  query_schema        CRM SimulatedBackend / 线上 HTTP                │
│  query_data          CRM SimulatedBackend / 线上 HTTP                │
│  analyze_data        CRM SimulatedBackend / 线上 HTTP                │
│  browse_metamodel    MetarepoSimulated / 线上 HTTP                   │
│  query_metadata      MetarepoSimulated / 线上 HTTP                   │
│                                                                     │
│  � 不用 Mock（8 个）— 真实调用以验证完整能力                        │
│  ─────────────────────────────────────────────                      │
│  file_upload         COS 文件上传（验证输出链路）                     │
│  web_search          百度 AI 搜索（验证信息整合能力）                 │
│  knowledge_search    知识库检索（验证检索效果）                       │
│  list_knowledge_bases 知识库列表（轻量只读）                          │
│  knowledge_doc_detail 文档详情（验证检索→详情链路）                   │
│  read_file           沙盒文件读取（验证脚本产出）                     │
│  search_files        沙盒文件搜索（只读，验证定位能力）               │
│  read_skill_resource 技能资源读取（DB 只读，验证真实配置）            │
│                                                                     │
│  🔴 不应 Mock（4 个）— 交互/编排类，mock 破坏链路                    │
│  ─────────────────────────────────────────────                      │
│  ask_user            用户交互（由 turns 机制替代）                    │
│  ask_clarification   用户追问（Agent 行为本身是验证目标）             │
│  skills_tool         技能编排入口（应 mock 的是子工具）               │
│  agent_tool          子 Agent 编排入口                                │
│                                                                     │
│  ⛔ 评测禁用（1 个）— 禁止调用，防止数据污染                         │
│  ─────────────────────────────────────────────                      │
│  manage_skill        技能管理（禁止在评测中创建/修改/删除技能）       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 七、三种 execution_mode 下的工具处理策略

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                execution_mode 与工具 mock 策略矩阵                            │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  execution_mode = "isolated" (全隔离，出厂回归测试)                            │
│  ────────────────────────────────────────────────────                        │
│  🟢 推荐Mock 工具  → 必须在 MockDataset 中配置，否则报错                      │
│  🟡 可选Mock 工具  → 必须在 MockDataset 中配置，否则报错                      │
│  � 不用Mock 工具  → 真实调用（评测环境需保障这些服务可用）                   │
│  �🔴 不Mock 工具    → 按特殊规则处理:                                          │
│     • ask_user/ask_clarification → EvalRunner 用 turns 预设回复自动注入       │
│     • skills_tool → 正常执行（其内部工具走 MockGateway 拦截）                 │
│     • agent_tool → 正常执行（子 Agent 内部工具同样走 MockGateway）            │
│  ⛔ 评测禁用工具   → MockGateway 直接拦截返回错误，不允许调用                  │
│                                                                              │
│  execution_mode = "integrated" (混合，租户验证)                               │
│  ────────────────────────────────────────────────────                        │
│  🟢 推荐Mock 工具  → 在 MockDataset 中配置则 mock，未配置则放行真实调用       │
│  🟡 可选Mock 工具  → 通常放行真实调用；如果 MockDataset 中声明了则 mock        │
│  🔵 不用Mock 工具  → 真实调用                                                 │
│  🔴 不Mock 工具    → 正常执行（ask_user 由 turns 接管，skills_tool 正常编排）  │
│  ⛔ 评测禁用工具   → MockGateway 直接拦截返回错误，不允许调用                  │
│                                                                              │
│  execution_mode = "real" (全真实，端到端验证)                                  │
│  ────────────────────────────────────────────────────                        │
│  所有工具          → 真实调用，不注入 MockGatewayMiddleware                    │
│  🔴 不Mock 工具    → 正常执行（ask_user 由 turns 接管）                       │
│  ⛔ 评测禁用工具   → 仍然拦截（通过 ToolRegistry 层面禁用）                   │
│  注意: real 模式下仍需处理 ask_user（评测中无真实用户交互）                    │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 八、ask_user / ask_clarification 在评测中的特殊处理

这两个工具不走 MockGateway，而是由 EvalRunner 层面处理：

```
┌────────────────────────────────────────────────────────────────────────┐
│  EvalCase.turns 机制处理用户交互                                        │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  EvalCase 定义:                                                        │
│    turns:                                                              │
│      - input: "帮我取消订单 ORD-001"                                   │
│      - input: "确认，请继续"        ← Agent 调 ask_user 后自动注入     │
│      - input: "张三-华为那个"       ← Agent 调 ask_clarification 后注入│
│                                                                        │
│  EvalRunner 处理逻辑:                                                  │
│    Agent 调用 ask_user → ClarificationMiddleware 产生中断               │
│    EvalRunner 检测到中断 → 从 turns 队列取下一条 input 注入              │
│    Agent 继续执行                                                      │
│                                                                        │
│  如果 turns 耗尽但 Agent 还在追问:                                     │
│    → evidence.status = "blocked_on_user_input"                         │
│    → 断言引擎视为用例配置不完整                                         │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 九、MockGateway 嵌入 Middleware 管道的位置

### 现有中间件管道（`src/middleware/builder.py`）

所有 Middleware 不需要 mock，评测模式下完整复用生产管道。MockGateway 作为额外的 Middleware 条件注入：

```
TracingMiddleware          ─┐
TitleMiddleware             │  入口层
AgentLoggingMiddleware      │
DanglingToolCallMiddleware ─┘
InputTransformMiddleware   ─┐
  ├ ContentReviewTransformer│  预处理层
  ├ PIIRedactTransformer    │
  └ MultimodalTransformer  ─┘
ContextWindowMiddleware    ─── 上下文管控
MemoryMiddleware           ─── 记忆检索/提取
SubagentLimitMiddleware    ─┐
GuardrailMiddleware         │  安全层
SkillToolScopeMiddleware   ─┘
                                ▼▼▼ 评测模式插入点 ▼▼▼
MockGatewayMiddleware      ─── 仅 eval_mode=True 时注入
                               位置: SkillToolScopeMiddleware 之后
                               原因: 需要在工具实际执行前拦截,
                                     但在权限/作用域校验之后
LoopDetectionMiddleware    ─┐
ToolErrorHandlingMiddleware │  执行保护层
ClarificationMiddleware     │
OutputValidationMiddleware  │
OutputRenderMiddleware     ─┘
```

### 代码修改方案

```python
# src/middleware/builder.py 中条件注入
def build_middleware(..., eval_mode: bool = False, mock_gateway=None):
    ...
    middleware.append(SkillToolScopeMiddleware())
    
    # ═══ 评测模式注入 MockGatewayMiddleware ═══
    if eval_mode and mock_gateway:
        from src.eval.mock_gateway_middleware import MockGatewayMiddleware
        middleware.append(MockGatewayMiddleware(gateway=mock_gateway))
    
    middleware += [
        LoopDetectionMiddleware(),
        ToolErrorHandlingMiddleware(),
        ...
    ]
```

---

## 十、MockDataset 配置界面的工具选择器

用户配置 MockDataset 时，UI 应从 `ToolRegistry.all_tools` 获取工具列表并标注 mock 建议：

```
┌─────────────────────────────────────────────────────────────────────────┐
│  添加工具 Mock                                                    [搜索]│
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ⚠️ 推荐 Mock（外部依赖/副作用）                                        │
│  ─────────────────────────                                              │
│  ☑ modify_data         CRM 数据修改（写入，改变内部状态）               │
│  ☑ manage_memory       记忆管理（向量 DB，副作用）                       │
│  ☑ memory_read         记忆读取（向量 DB，不确定性）                     │
│  ☑ terminal            沙盒终端命令（远程执行，副作用）                  │
│  ☑ execute_code        沙盒代码执行（远程执行，副作用）                  │
│  ☑ write_file          沙盒文件写入（远程文件系统，副作用）              │
│                                                                         │
│  💡 可选 Mock（内部数据源）                                              │
│  ─────────────────────────                                              │
│  ☐ query_data          CRM 数据查询（内部模拟）                          │
│  ☐ query_schema        CRM 元数据查询（内部模拟）                        │
│  ☐ analyze_data        数据聚合分析（内部模拟）                          │
│  ☐ browse_metamodel    元模型浏览（内部/HTTP）                           │
│  ☐ query_metadata      元数据实例查询（内部/HTTP）                       │
│                                                                         │
│  ✅ 不用 Mock（真实调用）                                                │
│  ─────────────────────────                                              │
│  ─ file_upload         COS 文件上传（验证输出链路）                      │
│  ─ web_search          百度 AI 搜索（验证信息整合能力）                  │
│  ─ knowledge_search    知识库检索（验证检索效果）                        │
│  ─ list_knowledge_bases 知识库列表（轻量只读）                           │
│  ─ knowledge_doc_detail 文档详情（验证检索→详情链路）                    │
│  ─ read_file           沙盒文件读取（验证脚本产出）                      │
│  ─ search_files        沙盒文件搜索（只读定位）                          │
│  ─ read_skill_resource 技能资源读取（DB 只读，验证真实配置）             │
│                                                                         │
│  🚫 不可 Mock（交互/编排类）                                             │
│  ─────────────────────────                                              │
│  ─ ask_user            （由 turns 机制替代）                             │
│  ─ ask_clarification   （由 turns 机制替代）                             │
│  ─ skills_tool         （编排入口，不应拦截）                            │
│  ─ agent_tool          （编排入口，不应拦截）                            │
│                                                                         │
│  ⛔ 评测禁用（不可使用）                                                 │
│  ─────────────────────────                                              │
│  ─ manage_skill        （禁止调用，防止技能数据污染）                    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 十一、MockToolGateway 初始化校验

确保 MockDataset 中声明的 tool_name 在 ToolRegistry 中存在：

```python
# src/eval/mock_gateway.py

class MockToolGateway:
    def __init__(self, mock_configs, strict_mode, tool_registry: ToolRegistry):
        ...
        # 校验: MockDataset 中声明的 tool_name 必须在 ToolRegistry 中存在
        for config in mock_configs:
            if tool_registry.find_by_name(config.tool_name) is None:
                raise MockConfigError(
                    f"MockDataset 中声明的工具 '{config.tool_name}' "
                    f"不存在于当前 Agent 的 ToolRegistry 中。"
                    f"可用工具: {[t.name for t in tool_registry.all_tools]}"
                )
        
        # 校验: 不允许 mock 编排类工具
        NON_MOCKABLE = {"ask_user", "ask_clarification", "skills_tool", "agent_tool"}
        for config in mock_configs:
            if config.tool_name in NON_MOCKABLE:
                raise MockConfigError(
                    f"工具 '{config.tool_name}' 是交互/编排类工具，不允许 mock。"
                    f"ask_user/ask_clarification 由 EvalCase.turns 机制处理；"
                    f"skills_tool/agent_tool 应正常执行，mock 其内部调用的业务工具。"
                )
        
        # 校验: 评测禁用工具不允许出现在 MockDataset 中（直接在 Gateway 层拦截）
        EVAL_FORBIDDEN = {"manage_skill"}
        for config in mock_configs:
            if config.tool_name in EVAL_FORBIDDEN:
                raise MockConfigError(
                    f"工具 '{config.tool_name}' 在评测场景中被禁用，"
                    f"不允许出现在 MockDataset 配置中。"
                    f"原因: manage_skill 会写入 ai_skill 表，可能污染技能数据。"
                )
    
    # 评测禁用工具列表 — Agent 运行时若调用这些工具，直接返回错误
    EVAL_FORBIDDEN_TOOLS = {"manage_skill"}
    
    def should_intercept(self, tool_name: str) -> bool:
        """判断是否拦截该工具调用"""
        # 评测禁用工具 → 直接拦截并报错
        if tool_name in self.EVAL_FORBIDDEN_TOOLS:
            raise EvalForbiddenToolError(
                f"工具 '{tool_name}' 在评测场景中被禁用，不允许调用。"
            )
        # 已配置 mock 的工具 → 拦截
        if tool_name in self._mocks:
            return True
        # 未配置 mock 的工具 → 按 strict_mode 决定
        if self._strict_mode:
            raise MockNotConfiguredError(
                f"严格模式下工具 '{tool_name}' 未配置 mock 数据"
            )
        return False  # hybrid 模式下放行
```

---

## 十二、总结

| 问题 | 答案 |
|------|------|
| 存哪里 | 三张表：dataset（集）→ mock_tool（工具）→ mock_rule（规则） |
| 用户怎么配 | 界面表单 / API 批量 / Skill 生成，三种入口 |
| 怎么加载 | 评测开始时一次性从 DB 加载到内存，构建 MockToolGateway |
| 怎么匹配 | 工具调用时按 priority 遍历规则，conditions 全满足则命中 |
| 没命中怎么办 | 返回 default_response；如果连 default 都没有，按 execution_mode 决定 |
| 如何隔离 | 每条用例独立的 gateway 实例，overrides 不互相影响 |
| Middleware 要 mock 吗 | **不需要**，所有 Middleware 完整复用生产管道 |
| 哪些工具推荐 mock | 6 个（外部依赖 + 副作用 + 不确定性） |
| 哪些工具可选 mock | 5 个（内部数据源，取决于 execution_mode） |
| 哪些工具不用 mock | 8 个（真实调用以验证完整能力） |
| 哪些工具不能 mock | 4 个（交互/编排类，由 turns 或正常执行替代） |
| 哪些工具评测禁用 | 1 个（manage_skill，防止数据污染） |
