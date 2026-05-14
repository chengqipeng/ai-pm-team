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
    context               VARCHAR(20) NOT NULL DEFAULT 'inline',  -- 系统默认，前端不暴露（inline | fork）
    agent                 VARCHAR(100) DEFAULT '',      -- 系统默认，前端不暴露（fork 模式子 Agent）
    model                 VARCHAR(100) DEFAULT '',      -- 系统默认，前端不暴露（指定模型，空=继承）
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

### 3.3 Skill 分类表（ai_skill_category）

分类不再硬编码为枚举值，而是独立存储在 `ai_skill_category` 表中，支持动态维护（增删改排序）。

```sql
CREATE TABLE IF NOT EXISTS ai_skill_category (
    -- 主键 & 标识
    id              BIGINT PRIMARY KEY,
    api_key         VARCHAR(50) NOT NULL,            -- 分类唯一标识（如 crm / metarepo / analysis）
    tenant_id       BIGINT NOT NULL DEFAULT 0,       -- 0=平台级预置分类，>0=租户自定义分类

    -- 基本信息
    name            VARCHAR(100) NOT NULL DEFAULT '', -- 分类展示名（如 "CRM 业务"）
    name_key        VARCHAR(100) NOT NULL DEFAULT '', -- 国际化 key
    description     VARCHAR(500) DEFAULT '',          -- 分类说明
    icon            VARCHAR(100) DEFAULT '',          -- 图标标识（如 antd icon name 或 emoji）
    color           VARCHAR(20) DEFAULT '',           -- 标签颜色（如 #1890ff）

    -- 控制
    sort_num        INT NOT NULL DEFAULT 0,          -- 排序权重（越小越靠前）
    enabled_flg     SMALLINT NOT NULL DEFAULT 1,     -- 1=启用, 0=禁用（禁用后前端筛选栏不展示）
    system_flg      SMALLINT NOT NULL DEFAULT 0,     -- 1=系统预置（不可删除），0=用户创建

    -- BaseEntity
    delete_flg      SMALLINT NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL,
    created_by      BIGINT NOT NULL DEFAULT 0,
    updated_at      BIGINT NOT NULL,
    updated_by      BIGINT NOT NULL DEFAULT 0
);

-- 同一租户下 api_key 唯一
CREATE UNIQUE INDEX IF NOT EXISTS uk_skill_category_key
    ON ai_skill_category(tenant_id, api_key) WHERE delete_flg = 0;

-- 排序查询
CREATE INDEX IF NOT EXISTS idx_skill_category_sort
    ON ai_skill_category(tenant_id, enabled_flg, sort_num) WHERE delete_flg = 0;
```

#### 字段说明

| 字段 | 说明 |
|------|------|
| api_key | 分类唯一标识，与 ai_skill_definition.category 关联（外键语义，不建物理外键） |
| tenant_id | 0=平台预置分类（所有租户可见），>0=该租户私有分类 |
| name | 前端展示名，如 "CRM 业务"、"元数据管理" |
| icon | 前端图标，支持 Ant Design Icon name 或 emoji |
| color | 分类标签颜色，用于列表页 Tag 展示 |
| sort_num | 控制前端筛选 Tab 的排列顺序 |
| enabled_flg | 禁用后该分类不出现在筛选栏和下拉选项中，但已关联该分类的 Skill 不受影响 |
| system_flg | 系统预置分类不允许删除，只能编辑名称/图标/排序 |

#### 与 ai_skill_definition 的关系

`ai_skill_definition.category` 存储的是 `ai_skill_category.api_key`，为字符串软关联：
- 查询 Skill 列表时，前端先调用分类列表接口获取可用分类，再按 category 筛选
- Skill 创建/编辑时，分类下拉框的选项来自分类列表接口
- 如果某个分类被删除，已关联该分类的 Skill 的 category 字段不会自动清空（展示为"未分类"）

#### 预置分类初始数据

| api_key | name | icon | sort_num | system_flg |
|---------|------|------|----------|------------|
| crm | CRM 业务 | 📊 | 10 | 1 |
| metarepo | 元数据管理 | 🗂️ | 20 | 1 |
| analysis | 数据分析 | 📈 | 30 | 1 |
| automation | 自动化操作 | ⚙️ | 40 | 1 |
| custom | 自定义 | 🔧 | 100 | 1 |

#### 分类 REST API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/skill-categories | 分类列表（含排序，前端筛选栏 + 下拉选项共用） |
| POST | /api/skill-categories | 创建分类 |
| PUT | /api/skill-categories/{api_key} | 编辑分类（名称/图标/颜色/排序） |
| DELETE | /api/skill-categories/{api_key} | 删除分类（system_flg=1 不可删） |
| PUT | /api/skill-categories/sort | 批量更新排序 |

#### 列表响应示例

```json
GET /api/skill-categories

{
  "items": [
    {
      "api_key": "crm",
      "name": "CRM 业务",
      "icon": "📊",
      "color": "#1890ff",
      "sort_num": 10,
      "enabled": true,
      "system": true,
      "skill_count": 5
    },
    {
      "api_key": "metarepo",
      "name": "元数据管理",
      "icon": "🗂️",
      "color": "#52c41a",
      "sort_num": 20,
      "enabled": true,
      "system": true,
      "skill_count": 3
    }
  ]
}
```

#### 创建分类请求示例

```json
POST /api/skill-categories
{
  "api_key": "reporting",
  "name": "报表生成",
  "icon": "📋",
  "color": "#722ed1",
  "sort_num": 50
}
```

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
| GET | /api/skill-categories | 分类列表（独立分类管理，见 3.3 节） |
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

整体采用左侧菜单 + 右侧内容区的布局，左侧菜单区分"技能列表"和"分类管理"两个功能入口。

```
/admin/skills                    — 技能管理（左侧菜单 + 右侧内容区）
/admin/skills/list               — 技能列表（默认）
/admin/skills/list/:apiKey       — 技能详情/编辑
/admin/skills/list/:apiKey/logs  — 执行日志
/admin/skills/categories         — 分类管理
```

### 5.2 整体布局

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 技能管理                                                                │
├────────────┬────────────────────────────────────────────────────────────┤
│            │                                                            │
│  左侧菜单  │                    右侧内容区                               │
│            │                                                            │
│ ┌────────┐ │  （根据左侧菜单选中项切换内容）                              │
│ │📋 技能  │ │                                                            │
│ │  列表   │ │                                                            │
│ └────────┘ │                                                            │
│            │                                                            │
│ ┌────────┐ │                                                            │
│ │🏷️ 分类 │ │                                                            │
│ │  管理   │ │                                                            │
│ └────────┘ │                                                            │
│            │                                                            │
├────────────┴────────────────────────────────────────────────────────────┤
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.3 技能列表页（左侧选中"技能列表"）

```
┌────────────┬────────────────────────────────────────────────────────────┐
│            │ 技能列表                                    [+ 创建技能]    │
│ ┌────────┐ ├────────────────────────────────────────────────────────────┤
│ │▶ 技能  │ │ [全部] [CRM] [元数据] [分析] [自动化] [自定义] 🔍 搜索... │
│ │  列表  │ ├────────────────────────────────────────────────────────────┤
│ └────────┘ │                                                            │
│            │ ┌────────────────────────────────────────────────────────┐ │
│ ┌────────┐ │ │ 📊 customer_360          v1.0.0  [🟢 启用 ▼]         │ │
│ │  分类  │ │ │ 客户 360 全景视图                                     │ │
│ │  管理  │ │ │ CRM | read_only | 执行 42 次 | 成功率 90%             │ │
│ └────────┘ │ │                                     [编辑] [克隆] [删除]│ │
│            │ └────────────────────────────────────────────────────────┘ │
│            │                                                            │
│            │ ┌────────────────────────────────────────────────────────┐ │
│            │ │ 🔍 diagnose              v1.0.0  [🟢 启用 ▼]         │ │
│            │ │ 系统化诊断业务数据异常或配置问题                        │ │
│            │ │ CRM | read_only | 执行 15 次 | 成功率 87%             │ │
│            │ │                                     [编辑] [克隆] [删除]│ │
│            │ └────────────────────────────────────────────────────────┘ │
│            │                                                            │
│            │ ┌────────────────────────────────────────────────────────┐ │
│            │ │ ⚠️ batch_cleanup          v1.0.0  [⚪ 禁用 ▼]         │ │
│            │ │ 批量清理过期或无效的业务数据                            │ │
│            │ │ 自动化 | destructive | 执行 3 次 | 成功率 100%         │ │
│            │ │                                     [编辑] [克隆] [删除]│ │
│            │ └────────────────────────────────────────────────────────┘ │
│            │                                                            │
│            │                      [1] [2] [3] ...                       │
└────────────┴────────────────────────────────────────────────────────────┘
```

### 5.4 分类管理页（左侧选中"分类管理"）

```
┌────────────┬────────────────────────────────────────────────────────────┐
│            │ 分类管理                                    [+ 新增分类]    │
│ ┌────────┐ ├────────────────────────────────────────────────────────────┤
│ │  技能  │ │                                                            │
│ │  列表  │ │  排序  │ 图标 │ 分类名称     │ 技能数 │ 状态 │ 操作       │
│ └────────┘ │ ──────┼──────┼──────────────┼────────┼──────┼─────────── │
│            │  ⠿ 1  │  📊  │ CRM 业务     │   5    │ 启用 │ 编辑       │
│ ┌────────┐ │  ⠿ 2  │  🗂️  │ 元数据管理   │   3    │ 启用 │ 编辑       │
│ │▶ 分类  │ │  ⠿ 3  │  📈  │ 数据分析     │   2    │ 启用 │ 编辑       │
│ │  管理  │ │  ⠿ 4  │  ⚙️  │ 自动化操作   │   1    │ 启用 │ 编辑       │
│ └────────┘ │  ⠿ 5  │  🔧  │ 自定义       │   0    │ 启用 │ 编辑       │
│            │  ⠿ 6  │  📋  │ 报表生成     │   0    │ 禁用 │ 编辑 删除  │
│            │                                                            │
│            │ ────────────────────────────────────────────────────────── │
│            │ 💡 拖拽 ⠿ 图标可调整分类排序                               │
│            │ 💡 系统预置分类（🔒）不可删除，仅可编辑名称/图标/颜色       │
│            │                                                            │
└────────────┴────────────────────────────────────────────────────────────┘
```

### 5.5 分类编辑弹框

```
┌─────────────────────────────────────────────┐
│ 编辑分类                              [✕]   │
├─────────────────────────────────────────────┤
│                                             │
│  API Key:    [crm              ] 🔒不可改   │
│  分类名称:   [CRM 业务          ]           │
│  图标:       [📊 ▼]  (emoji 选择器)        │
│  颜色:       [■ #1890ff ▼]  (色板选择)     │
│  描述:       [CRM 业务相关技能   ]          │
│  状态:       (●) 启用  ( ) 禁用             │
│                                             │
├─────────────────────────────────────────────┤
│                        [取消]  [保存]        │
└─────────────────────────────────────────────┘
```

### 5.6 创建/编辑技能页

```
┌────────────┬────────────────────────────────────────────────────────────┐
│            │ 创建技能                              [取消]  [保存]        │
│ ┌────────┐ ├────────────────────────────────────────────────────────────┤
│ │▶ 技能  │ │                                                            │
│ │  列表  │ │ ┌─ 基本信息 ────────────────────────────────────────────┐ │
│ └────────┘ │ │ API Key:     [customer_health_check    ]              │ │
│            │ │ 名称:        [客户健康度检查            ]              │ │
│ ┌────────┐ │ │ 描述:        [评估客户的活跃度...       ]              │ │
│ │  分类  │ │ │ 触发关键词:  [客户健康|健康度|活跃度评估]              │ │
│ │  管理  │ │ │ 分类:        [CRM ▼]                                  │ │
│ └────────┘ │ │ 标签:        [account] [health] [+ 添加]              │ │
│            │ │ 归属:        [CRM-Platform             ]              │ │
│            │ └────────────────────────────────────────────────────────┘ │
│            │                                                            │
│            │ ┌─ 执行配置 ────────────────────────────────────────────┐ │
│            │ │ 允许工具:    [query_data] [analyze_data] [+ 添加]     │ │
│            │ │ 参数列表:    [account_id] [+ 添加]                    │ │
│            │ └────────────────────────────────────────────────────────┘ │
│            │                                                            │
│            │ ┌─ 安全配置 ────────────────────────────────────────────┐ │
│            │ │ 风险等级:    (●) read_only  ( ) mutating  ( ) destru. │ │
│            │ │ 需要确认:    [ ] 是                                    │ │
│            │ │ 最大工具调用: [15]                                     │ │
│            │ │ 超时(ms):    [45000]                                   │ │
│            │ └────────────────────────────────────────────────────────┘ │
│            │                                                            │
│            │ ┌─ 提示词（Prompt） ────────────────────────────────────┐ │
│            │ │ ┌──────────────────────────────────────────────────┐  │ │
│            │ │ │ 你是客户健康度评估专家。请对客户 {account_id}... │  │ │
│            │ │ │                                                  │  │ │
│            │ │ │ ## 步骤 1: 获取客户基本信息                      │  │ │
│            │ │ │ 调用 query_data(action="get", ...)               │  │ │
│            │ │ └──────────────────────────────────────────────────┘  │ │
│            │ │ Markdown 编辑器 | 支持 {参数} 占位符高亮              │ │
│            │ └────────────────────────────────────────────────────────┘ │
│            │                                                            │
│            │ ┌─ 测试 ────────────────────────────────────────────────┐ │
│            │ │ account_id: [ACC001        ]        [▶ 测试执行]      │ │
│            │ │ 执行结果预览:                                          │ │
│            │ │ ┌──────────────────────────────────────────────────┐  │ │
│            │ │ │ (测试输出将显示在这里)                            │  │ │
│            │ │ └──────────────────────────────────────────────────┘  │ │
│            │ └────────────────────────────────────────────────────────┘ │
└────────────┴────────────────────────────────────────────────────────────┘
```

### 5.7 执行日志页

```
┌────────────┬────────────────────────────────────────────────────────────┐
│            │ customer_360 — 执行日志                        [← 返回]    │
│ ┌────────┐ ├────────────────────────────────────────────────────────────┤
│ │▶ 技能  │ │                                                            │
│ │  列表  │ │ 2025-05-10 14:32  ✅ 成功  耗时 12.3s  tokens: 2840      │
│ └────────┘ │ ├── 参数: account_id=ACC001                                │
│            │ ├── 工具调用: query_data×3, analyze_data×1                  │
│ ┌────────┐ │ └── [查看详情]                                             │
│ │  分类  │ │                                                            │
│ │  管理  │ │ 2025-05-10 11:05  ✅ 成功  耗时 15.1s  tokens: 3200      │
│ └────────┘ │ ├── 参数: account_id=ACC007                                │
│            │ ├── 工具调用: query_data×4, analyze_data×2                  │
│            │ └── [查看详情]                                             │
│            │                                                            │
│            │ 2025-05-09 16:48  ❌ 失败  耗时 45.0s  tokens: 1200      │
│            │ ├── 参数: account_id=ACC999                                │
│            │ ├── 错误: 超时                                             │
│            │ └── [查看详情]                                             │
│            │                                                            │
└────────────┴────────────────────────────────────────────────────────────┘
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
├── layout.tsx                 — 整体布局（左侧菜单 + 右侧内容区）
├── SkillList.tsx              — 技能列表页
├── SkillCreate.tsx            — 创建技能页
├── SkillDetail.tsx            — 技能详情/编辑页
├── SkillLogs.tsx              — 执行日志页
├── categories/
│   ├── CategoryList.tsx       — 分类管理页（表格 + 拖拽排序）
│   ├── CategoryFormModal.tsx  — 分类新增/编辑弹框
│   └── hooks/
│       ├── useCategories.ts   — 分类列表查询
│       └── useCategoryMutation.ts — 分类 CRUD mutation
├── components/
│   ├── SideMenu.tsx           — 左侧菜单组件（技能列表 / 分类管理）
│   ├── SkillCard.tsx          — 技能列表卡片
│   ├── SkillForm.tsx          — 技能表单（创建/编辑共用）
│   ├── PromptEditor.tsx       — Prompt Markdown 编辑器
│   ├── ArgumentsEditor.tsx    — 参数列表编辑
│   ├── ToolSelector.tsx       — 工具选择器
│   ├── SkillTestPanel.tsx     — 测试面板
│   ├── EnableSwitch.tsx       — 启用/禁用开关
│   ├── CategoryFilter.tsx     — 分类筛选 Tab（数据来自 useCategories）
│   └── CategorySelect.tsx     — 分类下拉选择器（Skill 表单中使用）
├── hooks/
│   ├── useSkills.ts           — 技能列表查询
│   ├── useSkillDetail.ts      — 技能详情查询
│   ├── useSkillMutation.ts    — 技能 CRUD mutation
│   └── useSkillTest.ts        — 测试执行
└── types.ts                   — TypeScript 类型定义
```

### 7.3 核心类型定义

```typescript
// types.ts

// ── Skill 分类（动态，来自 ai_skill_category 表）──
export interface SkillCategory {
  api_key: string;
  name: string;
  name_key: string;
  description: string;
  icon: string;
  color: string;
  sort_num: number;
  enabled: boolean;
  system: boolean;        // system_flg=1 的分类不可删除
  skill_count?: number;   // 列表接口返回时附带该分类下的技能数量
  tenant_id: number;
  created_at: number;
  updated_at: number;
}

export interface SkillCategoryCreateRequest {
  api_key: string;
  name: string;
  description?: string;
  icon?: string;
  color?: string;
  sort_num?: number;
}

export interface SkillCategoryUpdateRequest {
  name?: string;
  description?: string;
  icon?: string;
  color?: string;
  sort_num?: number;
  enabled?: boolean;
}

// ── Skill 定义 ──
export interface Skill {
  api_key: string;
  name: string;
  description: string;
  when_to_use: string;
  category: string;       // 关联 SkillCategory.api_key（动态值，非硬编码枚举）
  tags: string[];
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

export interface SkillCreateRequest {
  api_key: string;
  name: string;
  description: string;
  when_to_use?: string;
  category?: string;      // 关联 SkillCategory.api_key
  tags?: string[];
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

1. DDL 迁移脚本 — 新增 ai_skill_category 表 + ai_skill_definition 新增 category/tags/icon/sort_num/enabled_flg 字段
2. 分类初始化数据 — 插入 5 个系统预置分类（crm/metarepo/analysis/automation/custom）
3. 新增 `src/skills/category_service.py` — 分类 CRUD 业务逻辑层
4. 新增 `src/api/skill_category_api.py` — 分类 REST API（GET/POST/PUT/DELETE/排序）
5. 新增 `src/skills/service.py` — SkillService 业务逻辑层
6. 扩展 `src/api/skill_api.py` — 补全 POST/PUT/DELETE/toggle 接口
7. 扩展 `src/store/skill_dao.py` — 补全写入方法，load_from_db 改为检查 enabled_flg
8. 热加载机制 — 启用/禁用后自动刷新 SkillRegistry

### Phase 2: 前端管理页面（3天）

1. 分类管理页 — 分类列表 + 新增/编辑弹框 + 拖拽排序 + 删除（系统预置不可删）
2. 技能列表页 — 分类筛选（数据来自分类接口）+ 搜索 + 分页 + 启用/禁用开关
3. 创建/编辑页 — 表单 + 分类下拉选择器（数据来自分类接口）+ Prompt 编辑器
4. 测试面板 — 填入参数 → 调用测试接口 → 展示结果

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
