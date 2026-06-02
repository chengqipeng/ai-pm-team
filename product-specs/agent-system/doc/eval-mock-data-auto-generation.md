# Mock 数据自动生成策略

> 解决核心问题：用户不了解工具内部参数结构和返回格式，无法手动编写 Mock 数据。  
> 设计原则：**系统生成 Mock 数据，用户只做场景选择和确认**。

---

## 一、问题分析

### 用户手动编写 Mock 数据的困难

| 困难点 | 具体表现 |
|--------|----------|
| 不了解工具参数 schema | modify_data 的 action 有哪些取值？filters 支持什么格式？ |
| 不了解返回值结构 | manage_memory 返回什么字段？error 格式是什么？ |
| 不了解内部数据 | CrmSimulatedBackend 里有哪些 entity？哪些 record_id 有效？ |
| 不了解状态依赖 | memory_read 依赖 manage_memory 先写入；modify_data 依赖 query_data 先查到 |
| 不了解合理边界 | 什么算"正常"返回？什么算"异常"？延迟设多少合理？ |

### 核心思路转变

```
❌ 旧方案: 用户理解工具 → 手动写 JSON → 逐条配置规则
✅ 新方案: 系统录制/推导 → 自动生成 MockDataset → 用户选场景确认
```

---

## 二、Mock 数据的三种生成方式

### 方式一：录制回放（Recording & Replay）— 主力方式

**原理**：在真实运行（或 integrated 模式评测）中录制工具调用的完整输入/输出，作为 Mock 数据的来源。

```
┌─────────────────────────────────────────────────────────────────────┐
│  录制模式（Recording Mode）                                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Step 1: 用户正常使用 Agent 完成一次真实对话                         │
│    用户: "帮我取消订单 ORD-001 并退款"                               │
│    Agent 执行: query_data → modify_data → manage_memory → ...       │
│                                                                     │
│  Step 2: RecordingMiddleware 记录每次工具调用                        │
│    ┌─────────────────────────────────────────┐                      │
│    │ call_records:                            │                      │
│    │ - tool: query_data                       │                      │
│    │   input: {entity: "order", id: "ORD-001"}│                      │
│    │   output: {status: "paid", amount: 99.9} │                      │
│    │   latency_ms: 45                         │                      │
│    │                                          │                      │
│    │ - tool: modify_data                      │                      │
│    │   input: {action: "update", entity: "order", id: "ORD-001",│   │
│    │           data: {status: "cancelled"}}   │                      │
│    │   output: {success: true, affected: 1}   │                      │
│    │   latency_ms: 120                        │                      │
│    │                                          │                      │
│    │ - tool: manage_memory                    │                      │
│    │   input: {action: "add", content: "..."}│                      │
│    │   output: {memory_id: "mem-xxx"}         │                      │
│    │   latency_ms: 200                        │                      │
│    └─────────────────────────────────────────┘                      │
│                                                                     │
│  Step 3: 系统自动生成 MockDataset 草稿                               │
│    对录制到的 🟢推荐Mock 工具自动提取:                                │
│    • input → conditions（精确匹配或泛化匹配）                        │
│    • output → response_data                                         │
│    • latency → delay_ms（可选模拟）                                  │
│                                                                     │
│  Step 4: 用户确认（一键操作）                                        │
│    "基于这次对话生成了 3 条 Mock 规则，确认使用？"                     │
│    [确认] [编辑] [丢弃]                                              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**录制来源优先级**：

| 来源 | 适用场景 | 数据质量 |
|------|----------|----------|
| 用户真实对话录制 | 租户验证场景 | ★★★★★ 最真实 |
| 出厂测试人工执行 | 出厂回归场景 | ★★★★ 可控 |
| integrated 评测录制 | 已有评测升级为 isolated | ★★★★ 已验证 |

---

### 方式二：Schema 推导 + 系统预置（System Preset）— 出厂内置

**原理**：系统内部已知每个工具的参数 schema 和返回 schema，针对"推荐 Mock"工具预置一套标准 Mock 数据模板。

```
┌─────────────────────────────────────────────────────────────────────┐
│  系统预置 Mock 模板（按工具分类）                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ═══ modify_data 预置模板 ═══                                       │
│  系统已知: action ∈ {create, update, delete}                        │
│  系统已知: 返回格式 {success, affected_rows, record_id?}            │
│                                                                     │
│  自动生成:                                                          │
│    规则1: "写入成功"                                                 │
│      conditions: {action: {op: "exists"}}                           │
│      response: {success: true, affected_rows: 1}                    │
│    规则2: "记录不存在"                                               │
│      conditions: {action: "update", record_id: "__NOT_FOUND__"}     │
│      response: {success: false, error: "记录不存在"}                 │
│    规则3: "权限不足"                                                 │
│      conditions: {action: "delete"}                                  │
│      response: {success: false, error: "无删除权限"}                 │
│                                                                     │
│  ═══ manage_memory 预置模板 ═══                                     │
│  系统已知: action ∈ {add, list, delete, search}                     │
│  系统已知: 返回格式 {memory_id?, memories[]?, success}               │
│                                                                     │
│  自动生成:                                                          │
│    规则1: "写入记忆成功"                                             │
│      conditions: {action: "add"}                                     │
│      response: {success: true, memory_id: "mem-mock-001"}           │
│    规则2: "搜索记忆"                                                 │
│      conditions: {action: "search"}                                  │
│      response: {success: true, memories: [...预置数据...]}           │
│    规则3: "列出记忆"                                                 │
│      conditions: {action: "list"}                                    │
│      response: {success: true, memories: [], total: 0}              │
│                                                                     │
│  ═══ terminal / execute_code 预置模板 ═══                           │
│  系统已知: 返回格式 {exit_code, stdout, stderr}                      │
│                                                                     │
│  自动生成:                                                          │
│    规则1: "命令执行成功"                                             │
│      conditions: {command: {op: "exists"}}                           │
│      response: {exit_code: 0, stdout: "ok", stderr: ""}             │
│    规则2: "命令执行失败"                                             │
│      simulate_error: true                                            │
│      error_message: "Command not found"                              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**预置模板的管理**：

- 存储在代码中（`src/eval/mock_presets/`），跟随系统版本升级
- 每个工具一个 preset 文件，定义正常/异常/边界三类模板
- 用户创建 EvalCase 时，系统自动填充对应工具的预置 Mock（一键引用）

---

### 方式三：AI 辅助生成（场景描述 → Mock 数据）— 辅助增强

**原理**：用户用自然语言描述评测场景，系统（通过 LLM）根据工具 schema + 场景描述自动推导合理的 Mock 数据。

```
┌─────────────────────────────────────────────────────────────────────┐
│  AI 辅助生成                                                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  用户输入（自然语言）:                                               │
│    "测试订单取消场景：用户取消一个已付款订单，退款成功，                │
│     记录操作记忆。另外测一下退款失败（余额不足）的情况。"              │
│                                                                     │
│  系统分析:                                                           │
│    1. 识别涉及工具: modify_data（改订单状态）,                        │
│       manage_memory（记录记忆）                                      │
│    2. 读取工具 schema:                                               │
│       - modify_data.input_schema → {action, entity_api_key, ...}    │
│       - modify_data.output_schema → {success, affected_rows, ...}   │
│       - manage_memory.input_schema → {action, content, ...}         │
│    3. 结合场景描述推导:                                               │
│       - 退款成功: modify_data → {success: true}                      │
│       - 退款失败: modify_data → {success: false, error: "余额不足"}  │
│       - 记忆写入: manage_memory → {success: true, memory_id: "..."}  │
│                                                                     │
│  生成结果（用户确认）:                                               │
│    MockDataset: "订单取消-退款场景"                                   │
│    ├── modify_data:                                                  │
│    │   ├─ 规则1: 退款成功 → {success: true, affected_rows: 1}       │
│    │   └─ 规则2: 余额不足 → {success: false, error: "余额不足"}     │
│    └── manage_memory:                                                │
│        └─ 规则1: 记忆写入成功 → {success: true, memory_id: "..."}   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 三、各工具的 Mock 数据生成策略

### 3.1 推荐 Mock 工具（6 个）— 系统必须提供现成方案

| 工具 | 主力生成方式 | 系统预置内容 | 用户需要做的 |
|------|-------------|-------------|-------------|
| `modify_data` | 预置模板 + 录制 | 正常写入/记录不存在/权限不足/并发冲突 4 类模板 | 选择需要的场景组合 |
| `manage_memory` | 预置模板 | add/search/list/delete 各场景模板 | 几乎不需要修改 |
| `memory_read` | 预置模板 | 返回空记忆/返回历史记忆/指定 level 记忆 | 如需特定记忆内容可微调 |
| `terminal` | 录制回放 | 通用成功/失败模板；特定命令需录制 | 录制一次真实执行即可 |
| `execute_code` | 录制回放 | 通用成功/失败/超时模板 | 录制一次真实执行即可 |
| `write_file` | 预置模板 | 写入成功/磁盘满/路径不存在 | 几乎不需要修改 |

### 3.2 可选 Mock 工具（5 个）— 系统提供"快照"机制

| 工具 | 主力生成方式 | 系统做什么 | 用户需要做的 |
|------|-------------|-----------|-------------|
| `query_schema` | 环境快照 | 从当前环境的 CRM Schema 导出快照作为 Mock 数据 | 无需操作（自动） |
| `query_data` | 环境快照 + 录制 | 从 SimulatedBackend 导出测试数据快照 | 无需操作（自动） |
| `analyze_data` | 录制回放 | 录制真实聚合结果 | 无需操作 |
| `browse_metamodel` | 环境快照 | 从 MetarepoBackend 导出元模型结构快照 | 无需操作 |
| `query_metadata` | 环境快照 | 从 MetarepoBackend 导出元数据实例快照 | 无需操作 |

---

## 四、"环境快照"机制详细设计

对于可选 Mock 工具（都是内部数据源），最合理的方式不是让用户写数据，而是**系统自动对当前环境做快照，快照即 Mock 数据**。

```
┌─────────────────────────────────────────────────────────────────────┐
│  环境快照（Environment Snapshot）                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  触发时机:                                                           │
│    1. 用户创建 EvalCase 时，系统自动对当前环境打快照                   │
│    2. 用户手动"刷新快照"                                             │
│    3. 评测 Suite 绑定"固定快照版本"（保证回归稳定性）                 │
│                                                                     │
│  快照内容:                                                           │
│    ┌─────────────────────────────────────────────────┐              │
│    │ snapshot_id: "snap-20240315-001"                 │              │
│    │ created_at: "2024-03-15T10:00:00Z"              │              │
│    │                                                  │              │
│    │ crm_schema:    # query_schema 的快照              │              │
│    │   entities:                                      │              │
│    │     - api_key: "order"                           │              │
│    │       fields: [{name: "status", type: "enum"},...]│             │
│    │     - api_key: "customer"                        │              │
│    │       fields: [...]                              │              │
│    │                                                  │              │
│    │ crm_data:      # query_data 的快照               │              │
│    │   order:                                         │              │
│    │     - {id: "ORD-001", status: "paid", amount: 99.9}│           │
│    │     - {id: "ORD-002", status: "shipped", amount: 50}│          │
│    │   customer:                                      │              │
│    │     - {id: "CUS-001", name: "张三", level: "VIP"}│             │
│    │                                                  │              │
│    │ metamodel_schema:  # browse_metamodel 的快照     │              │
│    │   metamodels:                                    │              │
│    │     - {api_key: "entity", items: [...]}          │              │
│    │     - {api_key: "entityItem", items: [...]}      │              │
│    │                                                  │              │
│    │ metadata_instances:  # query_metadata 的快照     │              │
│    │   entity:                                        │              │
│    │     - {api_key: "order", label: "订单", ...}     │              │
│    │     - {api_key: "customer", label: "客户", ...}  │              │
│    │                                                  │              │
│    └─────────────────────────────────────────────────┘              │
│                                                                     │
│  使用方式:                                                           │
│    MockGateway 拦截 query_data(entity="order", id="ORD-001") 时:    │
│    → 从快照的 crm_data.order 中查找 id="ORD-001" 的记录              │
│    → 直接返回快照数据，不再查真实 Backend                             │
│                                                                     │
│  隔离性:                                                             │
│    每个 EvalSuite 绑定一个快照版本 → 不受环境数据变化影响             │
│    不同 EvalSuite 可绑定不同快照 → 测试不同数据状态                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 五、用户视角的完整操作流程

### 场景 A：出厂测试（内部 QA）

```
操作步骤（最简化）:

1. 运行一次真实对话（或 integrated 评测）
   → 系统自动录制所有工具调用

2. 点击"从录制生成 Mock"
   → 系统自动:
     • 识别哪些工具是 🟢推荐Mock → 提取录制数据生成规则
     • 对 🟡可选Mock 工具打环境快照
     • 对 🔵不用Mock 工具标记"直通"

3. 系统展示生成结果:
   "已为本次对话生成 MockDataset，包含:
    • modify_data: 2 条规则（正常更新 + 正常写入）
    • manage_memory: 1 条规则（添加记忆）
    • 环境快照: crm_data/metamodel 各 1 份
    [确认] [查看详情] [丢弃]"

4. 用户点击 [确认] → MockDataset 激活
   后续评测直接使用，无需手动编写任何 JSON
```

### 场景 B：租户自建评测（简单场景）

```
操作步骤（最简化）:

1. 用户在"评测管理"页面新建评测用例
   → 填写: 用例名称 + 输入对话

2. 系统提示: "检测到该 Skill 使用了以下需 Mock 的工具:
   • modify_data（有写操作副作用）
   • manage_memory（依赖外部向量库）
   推荐方案: 使用系统预置模板 [一键应用]"

3. 用户点击 [一键应用]
   → 系统自动填充预置模板到 MockDataset
   → 用户无需理解 JSON 格式

4. 如果用户需要特殊场景（如"退款失败"）:
   → 从预置模板列表中选择"异常场景-余额不足"
   → 系统自动添加对应规则（用户不需要写条件和返回值）
```

### 场景 C：租户复杂场景

```
操作步骤:

1. 用户描述场景（自然语言）:
   "测试客户投诉处理: 客户要求退款，金额超过 500 需主管审批，
    审批通过后执行退款并发送通知。"

2. AI 辅助分析 + 系统预置模板组合:
   → 识别工具链: query_data → modify_data → manage_memory
   → 从预置模板中组合:
     • query_data: 使用环境快照（订单数据已存在）
     • modify_data: 选择"正常更新"模板
     • manage_memory: 选择"写入成功"模板
   → 针对"金额超过 500 需审批"补充特殊规则

3. 系统展示可视化结果:
   ┌──────────────────────────────────────────┐
   │ 📦 客户投诉-退款审批场景                   │
   │                                          │
   │ modify_data:                             │
   │   ✅ 正常更新订单状态   [系统预置]        │
   │   ✅ 退款成功           [系统预置]        │
   │   ⚡ 金额>500需审批     [AI生成]          │
   │                                          │
   │ manage_memory:                           │
   │   ✅ 记忆写入成功       [系统预置]        │
   │                                          │
   │ [确认] [微调]                             │
   └──────────────────────────────────────────┘

4. 用户确认即可，不需要手动编写任何 Mock 数据
```

---

## 六、系统预置模板的维护策略

### 6.1 模板层级

```
┌─────────────────────────────────────────────────────────────────────┐
│  预置模板三层结构                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  第一层: 通用模板（Universal）— 跟随 agent-system 版本发布           │
│  ────────────────────────────────────                               │
│  位置: src/eval/mock_presets/universal/                              │
│  内容: 每个 🟢推荐Mock 工具的标准正常/异常/边界返回                  │
│  维护: 研发团队，随工具 schema 变更同步更新                          │
│  举例:                                                              │
│    modify_data_preset.yaml:                                         │
│      - name: "写入成功"                                              │
│        category: "normal"                                            │
│        conditions: {action: {op: "exists"}}                         │
│        response: {success: true, affected_rows: 1}                  │
│      - name: "记录不存在"                                            │
│        category: "error"                                             │
│        conditions: {action: "update"}                                │
│        response: {success: false, error_code: "NOT_FOUND"}          │
│      - name: "并发冲突"                                              │
│        category: "boundary"                                          │
│        response: {success: false, error_code: "CONFLICT"}           │
│                                                                     │
│  第二层: 场景模板（Scenario）— 按业务场景组合                        │
│  ────────────────────────────────────                               │
│  位置: src/eval/mock_presets/scenarios/                              │
│  内容: 多个工具的 Mock 组合，对应完整业务流程                        │
│  维护: 研发/QA 团队                                                  │
│  举例:                                                              │
│    order_cancel_scenario.yaml:                                       │
│      description: "订单取消退款场景"                                 │
│      tools:                                                          │
│        modify_data: [写入成功]                                       │
│        manage_memory: [记忆写入成功]                                 │
│      variants:                                                       │
│        - name: "正常退款"                                            │
│          overrides: {modify_data: "写入成功"}                        │
│        - name: "退款失败"                                            │
│          overrides: {modify_data: "余额不足"}                        │
│                                                                     │
│  第三层: 租户模板（Tenant）— 租户自定义/录制生成                     │
│  ────────────────────────────────────                               │
│  位置: DB（ai_eval_mock_dataset）                                    │
│  内容: 租户环境快照 + 录制回放数据                                   │
│  维护: 系统自动生成，租户可微调                                      │
│                                                                     │
│  优先级: Tenant > Scenario > Universal                               │
│  合并规则: 高优先级覆盖低优先级的同名工具规则                         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.2 预置模板与工具 Schema 的绑定

```python
# src/eval/mock_presets/registry.py

class MockPresetRegistry:
    """
    预置模板注册表 — 绑定到 ToolFactory 的工具注册流程
    每个工具注册时同时注册其 Mock 预置模板
    """
    
    @classmethod
    def get_presets_for_tool(cls, tool_name: str) -> list[MockPreset]:
        """获取工具的预置模板列表"""
        ...
    
    @classmethod
    def get_scenario_presets(cls) -> list[ScenarioPreset]:
        """获取所有场景模板"""
        ...
    
    @classmethod
    def auto_generate_dataset(
        cls, 
        skill_id: str,
        scenario: str = None,
    ) -> MockDataset:
        """
        根据 Skill 绑定的工具列表，自动生成完整 MockDataset
        
        逻辑:
        1. 获取 Skill 绑定的所有工具
        2. 筛选出 🟢推荐Mock + 🟡可选Mock 的工具
        3. 对 🟢推荐Mock: 填充 Universal 预置模板
        4. 对 🟡可选Mock: 打环境快照
        5. 如果指定了 scenario: 用场景模板覆盖
        6. 返回完整 MockDataset（status=draft）
        """
        ...
```

---

## 七、录制回放的技术实现

### 7.1 RecordingMiddleware

```python
# src/eval/recording_middleware.py

class RecordingMiddleware(BaseMiddleware):
    """
    工具调用录制中间件
    在任意模式下可开启，记录所有工具调用的完整输入/输出
    """
    
    def __init__(self, record_store: RecordStore):
        self._store = record_store
    
    async def process_tool_call(self, tool_name, arguments, context):
        # 调用真实工具
        result = await self.next(tool_name, arguments, context)
        
        # 记录调用
        self._store.record(ToolCallRecord(
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            timestamp=time.time(),
            session_id=context.session_id,
            latency_ms=elapsed,
        ))
        
        return result
```

### 7.2 从录制生成 MockDataset

```python
# src/eval/mock_generator.py

class MockDatasetGenerator:
    """从录制数据生成 MockDataset"""
    
    # 工具分类常量
    MUST_MOCK = {"modify_data", "manage_memory", "memory_read", 
                 "terminal", "execute_code", "write_file"}
    OPTIONAL_MOCK = {"query_schema", "query_data", "analyze_data",
                     "browse_metamodel", "query_metadata"}
    
    def generate_from_recording(
        self, 
        session_id: str,
        strategy: str = "auto",  # auto / all / must_only
    ) -> MockDataset:
        """
        strategy:
          - "auto": 只 mock 推荐Mock的工具，可选Mock用快照
          - "all": 推荐Mock + 可选Mock 都从录制生成
          - "must_only": 只 mock 推荐Mock的工具
        """
        records = self._store.get_records(session_id)
        
        dataset = MockDataset(name=f"录制-{session_id[:8]}")
        
        for record in records:
            if record.tool_name in self.MUST_MOCK:
                # 推荐 Mock 工具 → 从录制数据生成规则
                rule = self._record_to_rule(record)
                dataset.add_rule(record.tool_name, rule)
                
            elif record.tool_name in self.OPTIONAL_MOCK and strategy == "all":
                # 可选 Mock 工具（strategy=all 时才录制）
                rule = self._record_to_rule(record)
                dataset.add_rule(record.tool_name, rule)
        
        # 可选 Mock 工具如果未从录制生成，自动打环境快照
        if strategy == "auto":
            snapshot = self._take_environment_snapshot()
            dataset.attach_snapshot(snapshot)
        
        return dataset
    
    def _record_to_rule(self, record: ToolCallRecord) -> MockRule:
        """将单次录制转为 Mock 规则"""
        return MockRule(
            rule_name=f"{record.tool_name}-录制",
            priority=10,
            conditions=self._extract_conditions(record.arguments),
            response_data=record.result,
            delay_ms=record.latency_ms if record.latency_ms > 100 else None,
        )
    
    def _extract_conditions(self, arguments: dict) -> dict:
        """
        从工具参数提取匹配条件
        策略: 保留关键识别字段，忽略大文本字段
        """
        # 例: modify_data 的 conditions 只保留 action + entity_api_key + record_id
        # 忽略 data 字段（内容太长，不适合做匹配条件）
        ...
```

---

## 八、UI 设计（用户视角简化）

### 评测用例创建时的 Mock 配置

```
┌─────────────────────────────────────────────────────────────────────┐
│  新建评测用例                                                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  用例名称: [订单取消-正常退款                    ]                   │
│  输入对话: [帮我取消订单 ORD-001 并退款           ]                   │
│  期望结果: [订单状态变为 cancelled，退款成功       ]                   │
│                                                                     │
│  ── Mock 数据配置 ─────────────────────────────────────────────────│
│                                                                     │
│  💡 系统检测到该 Skill 使用了需 Mock 的工具:                         │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ 🟢 modify_data（写操作，必须 Mock）                             │ │
│  │                                                                │ │
│  │   Mock 方案:                                                   │ │
│  │   ○ 从录制生成   ← 需要先执行一次真实对话                      │ │
│  │   ● 使用预置模板 ← 推荐                                       │ │
│  │   ○ 自定义                                                     │ │
│  │                                                                │ │
│  │   已选模板:                                                    │ │
│  │   ☑ 写入成功（默认）                                           │ │
│  │   ☐ 记录不存在                                                 │ │
│  │   ☐ 权限不足                                                   │ │
│  │   ☐ 并发冲突                                                   │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ 🟢 manage_memory（外部依赖，必须 Mock）                         │ │
│  │                                                                │ │
│  │   Mock 方案: ● 使用预置模板                                    │ │
│  │   已选模板:                                                    │ │
│  │   ☑ 记忆写入成功（默认）                                       │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ 🟡 query_data（内部数据源，可选 Mock）                          │ │
│  │                                                                │ │
│  │   Mock 方案: ● 使用环境快照（自动）                            │ │
│  │   快照版本: snap-20240315-001 (最新)  [刷新]                   │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  [保存草稿]  [保存并运行]                                           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 快捷操作

```
┌─────────────────────────────────────────────────────────────────────┐
│  快捷 Mock 配置                                                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  [🎯 一键应用推荐配置]                                               │
│    系统自动: 推荐Mock工具用预置模板 + 可选Mock工具用环境快照          │
│    用户零操作，适合大多数场景                                        │
│                                                                     │
│  [🎬 从对话录制生成]                                                 │
│    选择一段历史对话 → 自动提取 Mock 数据                             │
│    适合需要精确复现某次对话的场景                                    │
│                                                                     │
│  [📋 选择场景模板]                                                   │
│    从预定义的业务场景列表中选择                                       │
│    如: 订单取消/客户查询/数据分析/审批流程...                        │
│                                                                     │
│  [✍️ 高级自定义]                                                     │
│    展开完整规则编辑器（面向高级用户/研发）                            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 九、与 eval-mock-data-full-design.md 的关系

本文档补充了 Mock 数据"从哪来"的问题：

| 维度 | eval-mock-data-full-design.md | 本文档 |
|------|-------------------------------|--------|
| 关注点 | Mock 数据存哪里、怎么加载、怎么匹配 | Mock 数据怎么生成、用户怎么操作 |
| 数据结构 | 三表设计 + 规则匹配引擎 | 预置模板 + 录制回放 + 环境快照 |
| 用户操作 | 界面配置 / API 批量（假设用户理解数据） | 一键应用 / 录制生成 / 场景选择 |
| 维护方 | 用户手动维护 | 系统自动维护 + 用户微调 |

### 数据流向

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  生成层（本文档） │    │ 存储层（full-design）│   │  运行层（full-design）│
│                  │───▶│                  │───▶│                  │
│ • 预置模板       │    │ • ai_eval_mock_* │    │ • MockGateway    │
│ • 录制回放       │    │ • 三表结构       │    │ • 规则匹配       │
│ • 环境快照       │    │                  │    │ • Middleware 拦截 │
│ • AI 辅助        │    │                  │    │                  │
└──────────────────┘    └──────────────────┘    └──────────────────┘
```

---

## 十、总结

| 问题 | 解决方案 |
|------|----------|
| 用户不了解工具参数 | 系统预置模板已填好参数，用户只选场景 |
| 用户不了解返回格式 | 预置模板/录制回放已包含完整返回结构 |
| 内部数据用户看不到 | 环境快照自动导出，用户无需关心数据来源 |
| 状态依赖关系复杂 | 场景模板已处理好工具间的数据依赖 |
| 边界值难以确定 | 预置模板内置正常/异常/边界三类覆盖 |
| 维护成本高 | 预置模板跟工具 schema 版本绑定，自动升级 |

**用户最少操作路径**: 创建评测用例 → 点击"一键应用推荐配置" → 完成。零 JSON 编写。
