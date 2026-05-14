# 对话式创建 Skill 设计方案

## 1. 设计目标

通过主 Agent 对话，用户用自然语言描述需求，Agent 自动完成 Skill 的创建。无需打开管理页面手动填写表单。

**核心体验：**
```
用户: 帮我创建一个技能，分析某个客户的商机健康度
Agent: 好的，我来帮你创建。请确认以下信息：
       - 技能名称：客户商机健康度分析
       - 参数：account_id（客户ID）
       - 使用工具：query_data、analyze_data
       - 执行逻辑：查询客户商机 → 按阶段统计 → 计算加权金额 → 输出健康度评分
       确认创建吗？
用户: 确认
Agent: ✅ 技能「客户商机健康度分析」已创建（api_key: opportunity_health_check）
```

## 2. 方案选型：内置 Skill（方案 B）

将"创建 Skill"本身作为主 Agent 的一个内置 Skill，通过 `skills_tool` 调用。

**优势：**
- 复用现有 Skill 执行链路，无需新增基础设施
- 用户在正常对话中即可触发，无需切换界面
- Agent 可以利用上下文理解用户意图（比如用户刚问了一个复杂问题，Agent 可以建议"要不要把这个分析流程保存为技能？"）

**约束：**
- 创建 Skill 是写操作，需要用户确认
- 生成的 Prompt 质量依赖 LLM 能力，需要结构化引导

## 3. Skill 定义

```yaml
api_key: create_skill
name: 创建技能
description: 通过对话方式创建新的 Agent 技能，根据用户描述自动生成技能定义并保存
when_to_use: 创建技能|新建技能|保存为技能|生成技能|定义技能
category: automation
context: inline
allowed_tools:
  - query_data        # 查询现有技能作为参考
  - modify_data       # 调用创建 API
arguments:
  - requirement       # 用户的技能需求描述
risk_level: mutating
requires_confirmation: true
max_tool_calls: 5
timeout_ms: 30000
```

## 4. 执行流程

```
用户输入 "帮我创建一个分析客户商机的技能"
    │
    ▼
主 Agent 意图识别 → 匹配 create_skill（关键词: 创建技能）
    │
    ▼
SkillExecutor.execute("create_skill", {requirement: "分析客户商机"})
    │
    ▼
create_skill Prompt 执行（inline 模式，共享上下文）：
    │
    ├── Step 1: 分析用户需求，提取关键信息
    │     - 技能目标：分析客户的商机健康度
    │     - 输入参数：account_id
    │     - 需要的数据：商机列表、金额、阶段
    │     - 输出格式：健康度评分 + 建议
    │
    ├── Step 2: 确定使用的工具
    │     - query_data（查商机数据）
    │     - analyze_data（聚合统计）
    │
    ├── Step 3: 生成 Skill 定义
    │     - api_key: opportunity_health_check
    │     - name: 客户商机健康度分析
    │     - prompt: 结构化的执行步骤
    │     - arguments: ["account_id"]
    │     - allowed_tools: ["query_data", "analyze_data"]
    │
    ├── Step 4: 展示给用户确认
    │     "我将创建以下技能：..."
    │     "确认创建吗？"
    │
    └── Step 5: 用户确认后，调用 POST /api/skills 创建
          → 返回创建结果
```

## 5. Prompt 设计

```markdown
你是技能创建助手。根据用户的需求描述，生成一个完整的 Agent 技能定义。

## 用户需求
{requirement}

## 可用工具清单
以下是系统中可用的工具，你创建的技能只能使用这些工具：
- query_data: 查询业务数据（客户、商机、联系人、活动、线索）
- modify_data: 修改业务数据（创建、更新、删除）
- analyze_data: 数据聚合分析（求和、计数、平均值 + 分组）
- web_search: 网络搜索获取实时信息

## 创建步骤

### Step 1: 分析需求
分析用户需求，确定：
- 技能要解决什么问题
- 需要什么输入参数（参数名用 camelCase，如 accountId）
- 需要查询/操作哪些数据
- 输出什么结果

### Step 2: 生成技能定义
按以下 JSON 格式生成完整的技能定义：

```json
{
  "api_key": "snake_case 格式的唯一标识",
  "name": "简短的中文名称",
  "description": "一句话描述技能用途",
  "when_to_use": "触发关键词，用|分隔",
  "category": "crm 或 analysis 或 automation",
  "arguments": ["参数名列表"],
  "argument_descriptions": {"参数名": "参数描述"},
  "allowed_tools": ["使用的工具列表"],
  "risk_level": "read_only 或 mutating",
  "max_tool_calls": 15,
  "timeout_ms": 45000,
  "prompt": "技能执行的详细 Prompt（Markdown 格式，用 {参数名} 作占位符）"
}
```

### Step 3: Prompt 编写规范
生成的 prompt 必须遵循以下规范：
- 开头说明角色和任务目标
- 用 ## 步骤 N: 标题 组织执行步骤
- 每个步骤明确指出调用哪个工具、传什么参数
- 用 {参数名} 引用输入参数
- 最后说明输出格式要求

### Step 4: 输出
将生成的技能定义以 JSON 格式输出，并附上简要说明。
等待用户确认后，调用 modify_data 创建技能。
```

## 6. 后端支持

### 6.1 创建 Skill 的 Tool 适配

`create_skill` 的 Prompt 中指示 LLM 生成 JSON 定义后调用 `modify_data` 创建。但 `modify_data` 当前只支持 CRM 实体的 CRUD，不支持创建 Skill。

**方案：新增一个专用工具 `manage_skill`**

```python
class ManageSkillTool(Tool):
    """管理技能定义 — 创建/更新/删除技能"""

    @property
    def name(self): return "manage_skill"

    def input_schema(self):
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "update", "delete", "list"],
                    "description": "操作类型"
                },
                "skill_definition": {
                    "type": "object",
                    "description": "技能定义（create/update 时必填）",
                    "properties": {
                        "api_key": {"type": "string"},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "when_to_use": {"type": "string"},
                        "category": {"type": "string"},
                        "arguments": {"type": "array", "items": {"type": "string"}},
                        "argument_descriptions": {"type": "object"},
                        "allowed_tools": {"type": "array", "items": {"type": "string"}},
                        "risk_level": {"type": "string"},
                        "max_tool_calls": {"type": "integer"},
                        "timeout_ms": {"type": "integer"},
                        "prompt": {"type": "string"},
                    }
                },
                "api_key": {
                    "type": "string",
                    "description": "技能 api_key（update/delete 时必填）"
                },
            },
            "required": ["action"],
        }

    async def call(self, input_data, context, on_progress=None):
        action = input_data["action"]

        if action == "create":
            definition = input_data.get("skill_definition", {})
            # 调用 SkillService.create()
            ...

        if action == "list":
            # 列出现有技能供参考
            ...
```

### 6.2 工具注册

在 `ai_tool_definition` 表中新增 `manage_skill` 工具：

| 字段 | 值 |
|---|---|
| api_key | manage_skill |
| name | 管理技能 |
| description | 创建、更新、删除 Agent 技能定义 |
| category | automation |
| read_only_flg | 0 |
| destructive_flg | 0 |

### 6.3 Skill 定义中的 allowed_tools

```json
{
  "api_key": "create_skill",
  "allowed_tools": ["manage_skill"]
}
```

## 7. 交互流程详细设计

### 7.1 简单场景（用户描述清晰）

```
用户: 创建一个技能，查询指定客户的所有联系人并按职位分类

Agent（create_skill 执行）:
  → 分析需求：查联系人 + 按职位分组
  → 生成定义：
    api_key: list_contacts_by_title
    name: 客户联系人分类
    arguments: [account_id]
    allowed_tools: [query_data]
    prompt: "查询客户 {account_id} 的联系人，按职位分类展示..."

Agent 回复:
  我为你生成了以下技能定义：
  
  **客户联系人分类** (list_contacts_by_title)
  - 参数：account_id（客户ID）
  - 工具：query_data
  - 逻辑：查询联系人 → 按职位分组 → 输出分类列表
  
  确认创建吗？

用户: 确认

Agent（调用 manage_skill）:
  ✅ 技能「客户联系人分类」已创建，api_key: list_contacts_by_title
  你可以通过说"帮我看看华为的联系人分类"来使用它。
```

### 7.2 复杂场景（需要追问）

```
用户: 帮我创建一个分析技能

Agent:
  好的，我需要了解更多信息：
  1. 这个技能要分析什么数据？（客户/商机/联系人/活动/线索）
  2. 需要什么输入参数？
  3. 期望输出什么格式的结果？

用户: 分析某个销售的商机 pipeline，看哪些阶段有瓶颈

Agent:
  明白了，我来创建一个"销售 Pipeline 瓶颈分析"技能：
  
  **销售 Pipeline 瓶颈分析** (sales_pipeline_bottleneck)
  - 参数：owner_id（销售人员ID）
  - 工具：query_data、analyze_data
  - 逻辑：
    1. 按阶段统计该销售的商机数量和金额
    2. 计算各阶段转化率
    3. 识别停留时间过长的商机
    4. 输出瓶颈分析报告
  
  确认创建吗？
```

### 7.3 从对话上下文自动建议

```
用户: 帮我看看华为的商机情况，按阶段统计金额，再看看哪些商机超过30天没活动

Agent:（执行查询后输出结果）
  ... 分析结果 ...
  
  💡 这个分析流程比较常用，要不要保存为技能？
  这样下次你可以直接说"分析华为的商机"就能得到同样的结果。

用户: 好的，保存

Agent:（调用 create_skill）
  ✅ 已保存为技能「客户商机全景分析」(account_opportunity_analysis)
  参数：account_id
  下次使用：说"分析XX客户的商机"即可触发
```

## 8. 实施计划

### Phase 1: 基础能力（2天）

1. **新增 `manage_skill` 工具**
   - 实现 ManageSkillTool 类（create/update/delete/list）
   - 注册到 ai_tool_definition 表
   - 注册到 ToolRegistry

2. **创建 `create_skill` Skill 定义**
   - 编写 Prompt（引导 LLM 生成结构化技能定义）
   - 写入 ai_skill_definition 表
   - allowed_tools: ["manage_skill"]

3. **测试验证**
   - 通过对话创建简单技能
   - 验证创建的技能能正常执行

### Phase 2: 体验优化（1天）

1. **上下文感知建议**
   - 当用户执行了复杂的多步查询后，Agent 主动建议保存为技能

2. **Prompt 质量优化**
   - 生成的 Prompt 参考现有高质量技能的格式
   - 自动校验 arguments 与 prompt 中占位符的一致性

3. **错误处理**
   - api_key 冲突时自动建议新名称
   - 参数校验失败时引导用户修正

### Phase 3: 高级能力（规划中）

1. **技能编辑** — "帮我修改 customer_360 技能，加上活动分析"
2. **技能组合** — "把客户分析和商机分析合并成一个技能"
3. **技能测试** — 创建后自动用测试数据验证一次

## 9. 与现有系统的关系

```
┌─────────────────────────────────────────────────────┐
│                    用户对话                           │
│  "帮我创建一个分析客户商机的技能"                      │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              主 Agent 意图识别                        │
│  匹配 create_skill（when_to_use: 创建技能|...）      │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│           SkillExecutor (inline 模式)                │
│  执行 create_skill 的 Prompt                         │
│  LLM 生成技能定义 JSON                               │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│           manage_skill Tool                          │
│  action: "create"                                    │
│  skill_definition: {...}                             │
│           │                                          │
│           ▼                                          │
│  SkillService.create() → ai_skill_definition 表     │
│  SkillRegistry.reload() → 热加载到内存               │
└─────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              新技能立即可用                           │
│  用户下次对话即可触发新创建的技能                      │
└─────────────────────────────────────────────────────┘
```

## 10. 风险与约束

| 风险 | 应对 |
|---|---|
| LLM 生成的 Prompt 质量不稳定 | 提供模板和示例，限制格式 |
| api_key 命名不规范 | 自动转换为 snake_case，校验格式 |
| allowed_tools 引用不存在的工具 | 校验时从 ai_tool_definition 表验证 |
| 用户创建了有害技能 | requires_confirmation=true，创建前展示完整定义 |
| 技能 Prompt 中占位符与 arguments 不匹配 | 创建前自动校验 |
