# Skill 管理体系设计方案

## 1. 设计目标

将 Skill 的定义、管理全流程从"文件导入"模式升级为"数据库定义 + 前端管理"模式：

- **数据库为唯一数据源**：Skill 定义存储在本地 PostgreSQL（paas_ai schema），运行时从 DB 加载
- **前端管理页面**：提供完整的 Skill CRUD、启用/禁用、执行监控
- **简化状态模型**：只有启用/禁用两种状态，无需发布流程
- **废弃 SKILL.md 文件**：不再依赖本地文件作为技能定义来源

## 2. 现状分析

### 当前问题

| 问题 | 说明 |
|------|------|
| 定义分散 | SKILL.md 文件 + SQL 初始化 + LLM 生成，三种来源混杂 |
| 无写入 API | skill_api.py 只有 GET 接口，无法通过 API 创建/编辑 |
| 无前端管理 | 运营人员无法可视化管理技能 |
| 状态模型过重 | draft/published/deprecated 三态流转过于复杂，实际只需启用/禁用 |
| 缺少分类/标签 | 技能数量增长后无法有效组织 |

### 保留的设计

| 组件 | 保留原因 |
|------|----------|
| ai_skill_definition 表结构 | 字段设计合理，简化状态字段即可 |
| ai_skill_exec_log 表 | 执行审计完整 |
| SkillRegistry.load_from_db() | 运行时加载逻辑正确 |
| SkillExecutor 执行链路 | inline/fork 路由无需改动 |

## 3. 数据库设计

### 3.1 表结构调整

在现有 `ai_skill_definition` 基础上简化状态模型，新增分类字段：

```sql
-- 在 ai_skill_definition 表新增字段
ALTER TABLE ai_skill_definition ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT '';
ALTER TABLE ai_skill_definition ADD COLUMN IF NOT EXISTS tags TEXT DEFAULT '[]';
ALTER TABLE ai_skill_definition ADD COLUMN IF NOT EXISTS icon VARCHAR(100) DEFAULT '';
ALTER TABLE ai_skill_definition ADD COLUMN IF NOT EXISTS sort_num INT DEFAULT 0;
ALTER TABLE ai_skill_definition ADD COLUMN IF NOT EXISTS enabled_flg SMALLINT DEFAULT 1;

-- status 字段废弃，统一用 enabled_flg 控制（0=禁用, 1=启用）
-- 兼容期：load_from_db 同时检查 enabled_flg=1 AND delete_flg=0

-- 新增分类索引
CREATE INDEX IF NOT EXISTS idx_skill_def_category
    ON ai_skill_definition(tenant_id, category) WHERE delete_flg = 0;
CREATE INDEX IF NOT EXISTS idx_skill_def_enabled
    ON ai_skill_definition(tenant_id, enabled_flg) WHERE delete_flg = 0;
```

### 3.2 完整表结构（含新增字段）

```sql
-- ai_skill_definition 完整字段清单
CREATE TABLE IF NOT EXISTS ai_skill_definition (
    -- 主键 & 标识
    id                    BIGINT PRIMARY KEY,
    api_key               VARCHAR(100) NOT NULL,        -- 技能唯一标识（租户内唯一）
    tenant_id             BIGINT NOT NULL DEFAULT 0,    -- 0=平台级

    -- 基本信息
    name                  VARCHAR(200) NOT NULL DEFAULT '',
    description           VARCHAR(1000) NOT NULL DEFAULT '',
    when_to_use           VARCHAR(500) DEFAULT '',      -- 触发关键词（|分隔）
    category              VARCHAR(50) DEFAULT '',       -- 分类：crm/metarepo/analysis/automation
    tags                  TEXT DEFAULT '[]',            -- JSON 标签数组
    icon                  VARCHAR(100) DEFAULT '',      -- 图标标识
    owner                 VARCHAR(100) DEFAULT '',      -- 归属团队/人
    sort_num              INT DEFAULT 0,               -- 排序权重

    -- 执行配置
    context               VARCHAR(20) NOT NULL DEFAULT 'inline',  -- inline | fork
    agent                 VARCHAR(100) DEFAULT '',      -- fork 模式子 Agent
    model                 VARCHAR(100) DEFAULT '',      -- 指定模型（空=继承）
    allowed_tools         TEXT NOT NULL DEFAULT '[]',   -- JSON: 允许的工具列表
    arguments             TEXT NOT NULL DEFAULT '[]',   -- JSON: 参数名列表
    prompt                TEXT NOT NULL DEFAULT '',     -- Markdown 提示词

    -- 安全 & 限制
    risk_level            VARCHAR(20) NOT NULL DEFAULT 'read_only',
    requires_confirmation SMALLINT NOT NULL DEFAULT 0,
    max_tool_calls        INT NOT NULL DEFAULT 20,
    timeout_ms            INT NOT NULL DEFAULT 60000,
    idempotent_flg        SMALLINT NOT NULL DEFAULT 1,

    -- 状态（简化：只有启用/禁用）
    enabled_flg           SMALLINT NOT NULL DEFAULT 1,  -- 1=启用, 0=禁用
    version               VARCHAR(20) NOT NULL DEFAULT '1.0.0',

    -- 运行统计
    exec_count            INT NOT NULL DEFAULT 0,
    success_count         INT NOT NULL DEFAULT 0,
    avg_duration_ms       INT NOT NULL DEFAULT 0,

    -- 扩展
    ext_info              TEXT DEFAULT '{}',

    -- BaseEntity
    delete_flg            SMALLINT NOT NULL DEFAULT 0,
    created_at            BIGINT NOT NULL,
    created_by            BIGINT NOT NULL DEFAULT 0,
    updated_at            BIGINT NOT NULL,
    updated_by            BIGINT NOT NULL DEFAULT 0
);
```

### 3.3 Skill 分类体系

| category | 说明 | 示例 |
|----------|------|------|
| crm | CRM 业务技能 | customer_360, pipeline_analysis |
| metarepo | 元数据管理技能 | inspect_metamodel, verify_config |
| analysis | 数据分析技能 | data_analysis, diagnose |
| automation | 自动化操作技能 | batch_cleanup |
| custom | 租户自定义技能 | （用户创建的） |

### 3.4 Skill 状态模型

只有两种状态，通过 `enabled_flg` 控制：

```
  启用 (enabled_flg=1) ←──→ 禁用 (enabled_flg=0)
```

- **启用**：Agent 运行时加载到 SkillRegistry，LLM 可调用
- **禁用**：不加载到内存，LLM 不可见，但数据保留可随时重新启用
- **删除**：软删除（delete_flg=1），前端不可见，数据保留用于审计

## 4. REST API 设计

### 4.1 接口清单

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/skills | 列表（支持分页、筛选、搜索） |
| GET | /api/skills/{api_key} | 详情 |
| POST | /api/skills | 创建 |
| PUT | /api/skills/{api_key} | 编辑 |
| PUT | /api/skills/{api_key}/toggle | 启用/禁用切换 |
| DELETE | /api/skills/{api_key} | 软删除 |
| POST | /api/skills/{api_key}/clone | 克隆 |
| GET | /api/skills/categories | 分类列表 |
| GET | /api/skills/stats | 执行统计概览 |
| POST | /api/skills/{api_key}/test | 测试执行（dry-run） |

### 4.2 请求/响应模型

#### 创建 Skill

```json
POST /api/skills
{
  "api_key": "customer_health_check",
  "name": "客户健康度检查",
  "description": "评估客户的活跃度、商机进展、互动频率，输出健康度评分",
  "when_to_use": "客户健康|健康度|活跃度评估",
  "category": "crm",
  "tags": ["account", "health", "scoring"],
  "context": "fork",
  "agent": "",
  "model": "",
  "allowed_tools": ["query_data", "analyze_data"],
  "arguments": ["account_id"],
  "prompt": "你是客户健康度评估专家...\n\n## 步骤 1: ...",
  "risk_level": "read_only",
  "requires_confirmation": false,
  "max_tool_calls": 15,
  "timeout_ms": 45000
}
```

#### 列表响应

```json
GET /api/skills?category=crm&enabled=true&page=1&page_size=20

{
  "total": 8,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "api_key": "customer_360",
      "name": "客户 360 全景",
      "description": "生成客户 360 度全景视图...",
      "category": "crm",
      "tags": ["account"],
      "context": "inline",
      "risk_level": "read_only",
      "enabled": true,
      "version": "1.0.0",
      "exec_count": 42,
      "success_count": 38,
      "avg_duration_ms": 12500,
      "owner": "CRM-Platform",
      "updated_at": 1746489600000
    }
  ]
}
```

#### 启用/禁用

```json
PUT /api/skills/customer_health_check/toggle
{
  "enabled": false
}
```

响应：

```json
{
  "api_key": "customer_health_check",
  "enabled": false,
  "message": "技能已禁用"
}
```

## 5. 前端管理页面设计

### 5.1 页面结构

```
/admin/skills                    — 技能列表页
/admin/skills/create             — 创建技能页
/admin/skills/:apiKey            — 技能详情/编辑页
/admin/skills/:apiKey/logs       — 执行日志页
```

### 5.2 技能列表页

```
┌─────────────────────────────────────────────────────────────────┐
│ 技能管理                                          [+ 创建技能]   │
├─────────────────────────────────────────────────────────────────┤
│ [全部] [CRM] [元数据] [分析] [自动化] [自定义]    🔍 搜索...    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 📊 customer_360          v1.0.0  [🟢 启用 ▼]               │ │
│ │ 客户 360 全景视图                                           │ │
│ │ inline | read_only | 执行 42 次 | 成功率 90%                │ │
│ │                                         [编辑] [克隆] [删除]│ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ 🔍 diagnose              v1.0.0  [🟢 启用 ▼]               │ │
│ │ 系统化诊断业务数据异常或配置问题                              │ │
│ │ inline | read_only | 执行 15 次 | 成功率 87%                │ │
│ │                                         [编辑] [克隆] [删除]│ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ ⚠️ batch_cleanup          v1.0.0  [⚪ 禁用 ▼]               │ │
│ │ 批量清理过期或无效的业务数据                                  │ │
│ │ fork | destructive | 执行 3 次 | 成功率 100%                │ │
│ │                                         [编辑] [克隆] [删除]│ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│                        [1] [2] [3] ...                          │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 创建/编辑页

```
┌─────────────────────────────────────────────────────────────────┐
│ 创建技能                                    [保存草稿] [发布]    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ ┌─ 基本信息 ──────────────────────────────────────────────────┐ │
│ │ API Key:     [customer_health_check    ]                    │ │
│ │ 名称:        [客户健康度检查            ]                    │ │
│ │ 描述:        [评估客户的活跃度...       ]                    │ │
│ │ 触发关键词:  [客户健康|健康度|活跃度评估]                    │ │
│ │ 分类:        [CRM ▼]                                        │ │
│ │ 标签:        [account] [health] [+ 添加]                    │ │
│ │ 归属:        [CRM-Platform             ]                    │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ ┌─ 执行配置 ──────────────────────────────────────────────────┐ │
│ │ 执行模式:    (●) inline  ( ) fork                           │ │
│ │ 子 Agent:    [                         ] (fork 模式可选)    │ │
│ │ 指定模型:    [                         ] (空=继承主模型)    │ │
│ │ 允许工具:    [query_data] [analyze_data] [+ 添加]           │ │
│ │ 参数列表:    [account_id] [+ 添加]                          │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ ┌─ 安全配置 ──────────────────────────────────────────────────┐ │
│ │ 风险等级:    (●) read_only  ( ) mutating  ( ) destructive   │ │
│ │ 需要确认:    [ ] 是                                         │ │
│ │ 最大工具调用: [15]                                          │ │
│ │ 超时(ms):    [45000]                                        │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ ┌─ 提示词（Prompt） ─────────────────────────────────────────┐ │
│ │ ┌─────────────────────────────────────────────────────────┐ │ │
│ │ │ 你是客户健康度评估专家。请对客户 {account_id} 进行...   │ │ │
│ │ │                                                         │ │ │
│ │ │ ## 步骤 1: 获取客户基本信息                             │ │ │
│ │ │ 调用 query_data(action="get", ...)                      │ │ │
│ │ │                                                         │ │ │
│ │ │ ## 步骤 2: 分析商机活跃度                               │ │ │
│ │ │ ...                                                     │ │ │
│ │ └─────────────────────────────────────────────────────────┘ │ │
│ │ Markdown 编辑器 | 支持 {参数} 占位符高亮                    │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ ┌─ 测试 ─────────────────────────────────────────────────────┐ │
│ │ account_id: [ACC001        ]          [▶ 测试执行]          │ │
│ │                                                             │ │
│ │ 执行结果预览:                                               │ │
│ │ ┌─────────────────────────────────────────────────────────┐ │ │
│ │ │ (测试输出将显示在这里)                                   │ │ │
│ │ └─────────────────────────────────────────────────────────┘ │ │
│ └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 5.4 执行日志页

```
┌─────────────────────────────────────────────────────────────────┐
│ customer_360 — 执行日志                              [← 返回]   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ 2025-05-10 14:32  ✅ 成功  耗时 12.3s  tokens: 2840            │
│ ├── 参数: account_id=ACC001                                     │
│ ├── 工具调用: query_data×3, analyze_data×1                      │
│ └── [查看详情]                                                  │
│                                                                 │
│ 2025-05-10 11:05  ✅ 成功  耗时 15.1s  tokens: 3200            │
│ ├── 参数: account_id=ACC007                                     │
│ ├── 工具调用: query_data×4, analyze_data×2                      │
│ └── [查看详情]                                                  │
│                                                                 │
│ 2025-05-09 16:48  ❌ 失败  耗时 45.0s  tokens: 1200            │
│ ├── 参数: account_id=ACC999                                     │
│ ├── 错误: 超时                                                  │
│ └── [查看详情]                                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 6. 后端实现方案

### 6.1 目录结构

```
src/
├── api/
│   └── skill_api.py          # REST API（扩展写入接口）
├── store/
│   ├── skill_models.py       # DB 行模型（已有）
│   └── skill_dao.py          # DAO 层（扩展写入方法）
├── skills/
│   ├── base.py               # SkillDefinition + SkillRegistry + SkillExecutor
│   ├── service.py            # 【新增】SkillService — 业务逻辑层
│   ├── tracker.py            # 执行追踪（已有）
│   └── optimizer.py          # LLM 优化（已有）
└── ...
```

### 6.2 SkillService 业务逻辑层

```python
class SkillService:
    """Skill 管理业务逻辑层

    职责：
    - 参数校验 + 业务规则
    - 启用/禁用控制
    - 热加载通知（启用/禁用后刷新 SkillRegistry）
    """

    def create(self, req: SkillCreateRequest, tenant_id: int, user_id: int) -> SkillDefinitionRow
    def update(self, api_key: str, req: SkillUpdateRequest, tenant_id: int, user_id: int) -> SkillDefinitionRow
    def toggle(self, api_key: str, enabled: bool, tenant_id: int, user_id: int) -> SkillDefinitionRow
    def clone(self, api_key: str, new_api_key: str, tenant_id: int, user_id: int) -> SkillDefinitionRow
    def delete(self, api_key: str, tenant_id: int, user_id: int) -> None
    def test_execute(self, api_key: str, arguments: dict, tenant_id: int) -> str
    def reload_registry(self, tenant_id: int) -> int  # 热加载
```

### 6.3 业务规则

| 规则 | 说明 |
|------|------|
| api_key 唯一 | 同一 tenant_id 下 api_key 不可重复 |
| 随时可编辑 | 无论启用/禁用状态都可以编辑 |
| 创建校验 | description 必填、prompt 非空、arguments 中的占位符必须在 prompt 中出现 |
| 启用/禁用即时生效 | 切换后自动调用 SkillRegistry.load_from_db() 刷新内存 |
| 删除为软删除 | delete_flg=1，不物理删除 |
| 禁用的 Skill 不加载 | load_from_db 只加载 enabled_flg=1 AND delete_flg=0 的记录 |

## 7. 前端技术方案

### 7.1 技术栈

| 层级 | 技术 |
|------|------|
| 框架 | React 19 |
| UI | Ant Design 6 |
| 构建 | Vite 8 |
| 状态管理 | React Query (TanStack Query) |
| 路由 | React Router v7 |
| Markdown 编辑 | @uiw/react-md-editor 或 Monaco Editor |
| 类型 | TypeScript 5.9 |

### 7.2 组件结构

```
src/pages/skills/
├── index.tsx                  — 列表页
├── SkillCreate.tsx            — 创建页
├── SkillDetail.tsx            — 详情/编辑页
├── SkillLogs.tsx              — 执行日志
├── components/
│   ├── SkillCard.tsx          — 列表卡片
│   ├── SkillForm.tsx          — 表单（创建/编辑共用）
│   ├── PromptEditor.tsx       — Prompt Markdown 编辑器
│   ├── ArgumentsEditor.tsx    — 参数列表编辑
│   ├── ToolSelector.tsx       — 工具选择器
│   ├── SkillTestPanel.tsx     — 测试面板
│   ├── EnableSwitch.tsx       — 启用/禁用开关
│   └── CategoryFilter.tsx     — 分类筛选
├── hooks/
│   ├── useSkills.ts           — 列表查询
│   ├── useSkillDetail.ts      — 详情查询
│   ├── useSkillMutation.ts    — 创建/编辑/启用禁用等 mutation
│   └── useSkillTest.ts        — 测试执行
└── types.ts                   — TypeScript 类型定义
```

### 7.3 核心类型定义

```typescript
// types.ts
export interface Skill {
  api_key: string;
  name: string;
  description: string;
  when_to_use: string;
  category: SkillCategory;
  tags: string[];
  context: 'inline' | 'fork';
  agent: string;
  model: string;
  allowed_tools: string[];
  arguments: string[];
  prompt: string;
  risk_level: 'read_only' | 'mutating' | 'destructive';
  requires_confirmation: boolean;
  max_tool_calls: number;
  timeout_ms: number;
  version: string;
  enabled: boolean;
  owner: string;
  exec_count: number;
  success_count: number;
  avg_duration_ms: number;
  tenant_id: number;
  created_at: number;
  updated_at: number;
}

export type SkillCategory = 'crm' | 'metarepo' | 'analysis' | 'automation' | 'custom';

export interface SkillCreateRequest {
  api_key: string;
  name: string;
  description: string;
  when_to_use?: string;
  category?: SkillCategory;
  tags?: string[];
  context?: 'inline' | 'fork';
  agent?: string;
  model?: string;
  allowed_tools?: string[];
  arguments?: string[];
  prompt: string;
  risk_level?: 'read_only' | 'mutating' | 'destructive';
  requires_confirmation?: boolean;
  max_tool_calls?: number;
  timeout_ms?: number;
}

export interface SkillToggleRequest {
  enabled: boolean;
}
```

## 8. 实施计划

### Phase 1: 后端 API 完善（2天）

1. DDL 迁移脚本 — 新增 category/tags/icon/sort_num/enabled_flg 字段
2. 新增 `src/skills/service.py` — SkillService 业务逻辑层
3. 扩展 `src/api/skill_api.py` — 补全 POST/PUT/DELETE/toggle 接口
4. 扩展 `src/store/skill_dao.py` — 补全写入方法，load_from_db 改为检查 enabled_flg
5. 热加载机制 — 启用/禁用后自动刷新 SkillRegistry

### Phase 2: 前端管理页面（3天）

1. 技能列表页 — 分类筛选 + 搜索 + 分页 + 启用/禁用开关
2. 创建/编辑页 — 表单 + Prompt 编辑器
3. 测试面板 — 填入参数 → 调用测试接口 → 展示结果

### Phase 3: 增强功能（2天）

1. 执行日志页 — 查看 ai_skill_exec_log
2. 统计面板 — 执行次数/成功率/耗时趋势图
3. 批量操作 — 批量启用/禁用
4. 导入/导出 — JSON 格式导入导出

## 9. 废弃项

| 废弃组件 | 替代方案 |
|----------|----------|
| skills/definitions/*.md | 数据库 ai_skill_definition |
| scripts/import_skills_from_definitions.py | 前端管理页面 + REST API |
| sql/init_skill_data.sql | 首次部署通过 API 或迁移脚本初始化 |
| SkillLoader（文件解析） | 保留 parse() 用于导入兼容，不再作为主加载路径 |
| SkillInstaller（文件安装） | 保留 URL 安装能力，主流程走 API |
| ai_skill_version 表 | 简化模型不再需要版本快照，保留表但不再写入 |
| ai_skill_policy 表 | 启用/禁用直接在主表控制，策略表暂不使用 |
| status 字段 | 用 enabled_flg 替代，兼容期保留字段 |
