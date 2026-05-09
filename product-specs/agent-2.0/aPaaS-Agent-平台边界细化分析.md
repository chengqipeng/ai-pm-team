# aPaaS 平台与 Agent 平台 — 细化边界分析

> 基于 NeoAgent + NeoPlatform 架构整合文档 v3、DeepAgent 整体设计方案、aPaaS 元数据驱动平台产品上下文，综合 Salesforce Agentforce + Data 360 最新架构对标。

---

## 一、边界划分的核心原则

| 原则 | 说明 | 判断标准 |
|:---|:---|:---|
| **运行时归属** | 谁的运行时在执行这段逻辑 | Agent Python 运行时 vs aPaaS Java 运行时 |
| **数据主权** | 数据的权威存储在哪一侧 | Agent 侧 PostgreSQL vs aPaaS 侧 MySQL/PG |
| **变更频率** | 配置变更的节奏 | Agent 侧秒级热更新 vs aPaaS 侧发布周期 |
| **用户角色** | 谁在操作 | AI 配置师 vs 低代码开发者 vs 业务管理员 |
| **安全边界** | 信任域的划分 | Agent 以用户身份代理执行 vs aPaaS 直接用户操作 |

---

## 二、分层边界总览（8 层架构）

```
+-----------------------------------------------------------------------+
| 第 1 层：应用层                                                         |
|   AI Agent 应用（6 种预置）          aPaaS 定制应用（5 维度）            |
|   边界：Agent 应用 = 对话式交互入口    aPaaS 应用 = 表单/流程/仪表盘     |
+-----------------------------------------------------------------------+
| 第 2 层：业务组件层（aPaaS 专属）                                       |
|   CRM 标准业务组件 + 定制组件                                           |
|   边界：Agent 不拥有业务组件，通过 Tool 调用 aPaaS 组件暴露的 API        |
+-----------------------------------------------------------------------+
| 第 3 层：工具与开发层                                                   |
|   AI 配置工具（10 项）               aPaaS 核心开发能力（9 项）          |
|   边界：AI 侧配置 Agent 行为         aPaaS 侧配置业务模型/UI/流程       |
+-----------------------------------------------------------------------+
| 第 4 层：核心引擎层                                                     |
|   AI 核心能力（12 项）               aPaaS 数据与流程引擎（10 项）       |
|   边界：AI 侧 = 推理+编排+记忆       aPaaS 侧 = 建模+流程+规则         |
+-----------------------------------------------------------------------+
| 第 5 层：AI 专属能力层                                                  |
|   AI 模型+原子能力（16 项）          企业级集成能力（6 项，aPaaS 侧）    |
+-----------------------------------------------------------------------+
| 第 6 层：AI Trust Layer（v3 新增，AI 专属）                             |
|   PII 掩码 / Prompt 注入防护 / 输出验证 / 零保留 / HITL / Plan Mode    |
+-----------------------------------------------------------------------+
| 第 7 层：统一平台服务（AI + aPaaS 共享）                                |
|   身份认证 / 权限控制 / 数据管理 / 审计合规 / 应用治理 / 多端适配       |
|   / 零信任与 API 治理                                                   |
+-----------------------------------------------------------------------+
| 第 8 层：共同底座                                                       |
|   多租户 / 元数据体系 / 微服务 / 中间件 / K8S / DevSecOps               |
+-----------------------------------------------------------------------+
```

---

## 三、逐层细化边界

### 3.1 应用层边界

| 维度 | Agent 平台（NeoAgent） | aPaaS 平台（NeoPlatform） | 交互方式 |
|:---|:---|:---|:---|
| **交互形态** | 对话式（Chat UI / 工作台 / 嵌入式助手） | 表单式（列表 / 详情 / 仪表盘 / 审批） | Agent 通过 A2UI 协议在对话中渲染 aPaaS 组件 |
| **应用实例** | 营销 Agent、销售助理 Agent、销售经理 Agent、渠道经理 Agent、客服 Agent、分析师 Agent | 客户管理应用、商机管理应用、合同管理应用、项目管理应用 | Agent 操作 aPaaS 应用的数据 |
| **用户入口** | 对话窗口、语音入口、嵌入式浮窗 | 菜单导航、工作台、移动端 App | 可在 aPaaS 页面内嵌入 Agent 入口 |
| **生命周期** | Agent 会话（创建-对话-暂停-恢复-结束） | 应用实例（安装-配置-发布-升级-下架） | Agent 应用也纳入统一应用治理 |

**边界判定规则**：
- 用户通过自然语言发起 → Agent 平台处理
- 用户通过表单/按钮/菜单操作 → aPaaS 平台处理
- Agent 需要展示结构化业务数据 → 通过 A2UI 协议调用 aPaaS 前端组件

---

### 3.2 业务组件层边界（aPaaS 专属）

| 组件类别 | 归属 | Agent 如何使用 | 边界说明 |
|:---|:---|:---|:---|
| 营销管理组件 | aPaaS 专属 | Agent 通过 `query_data` / `modify_data` Tool 调用组件 API | Agent 不拥有组件逻辑，只是调用者 |
| 销售管理组件 | aPaaS 专属 | 同上 | 组件内的业务规则（校验/审批/工作流）由 aPaaS 引擎执行 |
| 伙伴管理组件 | aPaaS 专属 | 同上 | Agent 无法绕过组件的业务规则 |
| 服务管理组件 | aPaaS 专属 | 同上 | 工单路由、SLA 计算等逻辑在 aPaaS 侧 |
| 智能分析组件 | **交叉** | Agent 的 `analyze_data` Tool 可调用分析组件 | 分析引擎在 aPaaS 侧，AI 侧提供自然语言转分析意图 |
| 定制组件 | aPaaS 专属 | Agent 通过元数据感知定制组件的 Schema | 定制组件的 CRUD 逻辑完全在 aPaaS 侧 |

**核心原则**：Agent 是业务组件的"智能调用者"，不是"替代者"。业务规则的执行权始终在 aPaaS 侧。

---

### 3.3 工具与开发层边界

#### AI 配置工具（10 项）— Agent 平台专属

| 工具 | 职责 | 产出物 | 存储位置 |
|:---|:---|:---|:---|
| Agent 设计器 | 配置 Agent 角色、能力、行为约束 | Agent 配置（JSON/YAML） | Agent 侧 PostgreSQL |
| Prompt 设计器 | 编写/调试 System Prompt | Prompt 模板 | Agent 侧 |
| Action 设计器 | 定义 Agent 可执行的动作 | Action 定义 | Agent 侧 |
| 智能流程设计器 | 编排多步 Agent 工作流 | Skill 定义（SKILL.md） | Agent 侧 |
| 可视化调试工具 | 调试 Agent 推理过程 | 调试日志 | Agent 侧 |
| UI 设计器(AI 组件) | 配置 A2UI 动态组件 | 组件映射配置 | Agent 侧 |
| 知识库管理 | 管理 RAG 知识源 | 向量索引 + 文档 | Agent 侧向量数据库 |
| MCP 集成配置器 | 配置外部 MCP Server 接入 | MCP 连接配置 | Agent 侧 |
| 测试评估工具 | 评估 Agent 效果 | 评估报告 | Agent 侧 |
| 元数据描述工具 | 为 Agent 描述 aPaaS 元数据语义 | 元数据描述文件 | **交叉**（读 aPaaS 元数据，写 Agent 侧描述） |

#### aPaaS 核心开发能力（9 项）— aPaaS 平台专属

| 能力 | 职责 | 产出物 | 存储位置 |
|:---|:---|:---|:---|
| 布局设计器 | 配置页面布局 | 布局元数据 | aPaaS 侧 p_tenant_metadata |
| UI 样式库 | 提供标准样式 | CSS/Token | aPaaS 前端 |
| UI 组件库 | 提供标准组件 | React 组件 | aPaaS 前端 |
| 自定义页面 | 低代码页面搭建 | 页面配置 | aPaaS 侧 |
| 脚本代码 | 自定义业务逻辑 | 脚本定义 | aPaaS 侧 |
| 开发 SDK | 提供开发接口 | SDK 包 | aPaaS 侧 |
| IDE 插件 | 开发辅助 | 插件包 | 开发者本地 |
| CI/CD | 持续集成部署 | 流水线配置 | DevOps 平台 |
| NEX 扩展开发 | 第三方扩展 | 扩展包 | aPaaS 应用市场 |

**边界判定规则**：
- 配置"Agent 怎么思考和行动" → AI 配置工具
- 配置"业务数据怎么存储和展示" → aPaaS 开发能力
- 元数据描述工具是唯一的交叉点：它读取 aPaaS 的元数据 Schema，生成 Agent 可理解的语义描述

---

### 3.4 核心引擎层边界（最关键的分界线）

#### AI 核心能力（12 项）— Agent 平台专属

| 能力 | 职责 | 运行时 | 数据存储 | 与 aPaaS 的接口 |
|:---|:---|:---|:---|:---|
| 意图推理 | 理解用户自然语言意图 | Python Agent 运行时 | 无持久化 | 推理结果决定调用哪个 aPaaS API |
| 记忆系统 | 长期记忆存储与检索 | Python + 向量数据库 | Agent 侧 PG + 向量库 | 记忆中可包含 aPaaS 业务实体引用 |
| 智能流程编排 | 多步任务规划与执行 | Python 状态机 | Redis 检查点 | 编排中调用 aPaaS 服务 API |
| MCP 接入层 | 外部工具/数据源接入 | Python MCP Client | Agent 侧配置 | 可接入 aPaaS 暴露的 MCP Server |
| 上下文工程 | 管理 LLM 上下文窗口 | Python 中间件栈 | Redis 缓存 | 压缩时保留 aPaaS 数据的关键信息 |
| Agentic RAG | 智能检索增强生成 | Python + 向量检索 | 向量数据库 | 可检索 aPaaS 知识库内容 |
| 元数据描述管理 | 管理 Agent 对业务对象的理解 | Python | Agent 侧 PG | **读取** aPaaS 元数据，生成语义描述 |
| 安全信任系统 | AI 输入输出安全 | Python 中间件 | Agent 侧审计日志 | 安全事件同步到统一审计 |
| 可观测系统 | Agent 运行监控 | Python Tracing | Agent 侧 PG (ai_trace_span) | 指标可汇入统一观测中心 |
| 测试评估系统 | Agent 效果评估 | Python 评估框架 | Agent 侧 | 评估数据来自 aPaaS 业务数据 |
| Multi-Agent 架构 | 多 Agent 协作 | Python 子 Agent 编排 | Redis + PG | 子 Agent 共享 aPaaS 数据访问权限 |
| 配置迁移 | Agent 配置跨环境迁移 | Python 脚本 | Agent 侧 | 需与 aPaaS 元数据版本对齐 |

#### aPaaS 数据与流程引擎（10 项）— aPaaS 平台专属

| 能力 | 职责 | 运行时 | 数据存储 | 与 Agent 的接口 |
|:---|:---|:---|:---|:---|
| 业务对象建模 | 定义实体/字段/关联 | Java Spring Boot | paas_metarepo_common / paas_metarepo | Agent 通过 `query_schema` Tool 读取 |
| 字段映射 | 元模型字段到存储列的映射 | Java | p_meta_item.db_column | Agent 无需感知，透明 |
| 校验规则 | 数据写入校验 | Java 规则引擎 | p_tenant_metadata (checkRule) | Agent 的 `modify_data` 必须通过校验 |
| 工作流 | 业务流程自动化 | Java 流程引擎 | 工作流定义表 | Agent 可触发工作流，但不能绕过 |
| 审批流 | 人工审批节点 | Java 审批引擎 | 审批定义表 | Agent 可发起审批，等待结果 |
| 自动流 | 条件触发自动执行 | Java 事件引擎 | 自动流定义表 | Agent 操作可触发自动流 |
| 规则引擎 | 业务规则执行 | Java | 规则定义表 | Agent 操作受规则约束 |
| 可视化业务流 | 复杂业务流程编排 | Java | 流程定义表 | Agent 可作为流程中的一个节点 |
| 脚本引擎 | 自定义逻辑执行 | Java (Groovy/JS) | 脚本定义表 | Agent 不直接调用脚本 |
| 自定义 API | 对外暴露业务接口 | Java Spring MVC | API 定义表 | Agent 的 Tool 可调用自定义 API |

#### 核心边界原则图示

```
+-------------------------------------------------------------------+
|                                                                     |
|  Agent 引擎负责：                    aPaaS 引擎负责：                |
|  +-------------------------+        +-------------------------+     |
|  | "理解用户要什么"         |        | "确保数据正确"           |     |
|  | "规划怎么做"             | --调用--> "执行业务规则"           |     |
|  | "记住用户偏好"           |        | "控制数据权限"           |     |
|  | "协调多步执行"           | <-返回-- "驱动业务流程"           |     |
|  +-------------------------+        +-------------------------+     |
|                                                                     |
|  Agent 是"大脑"                      aPaaS 是"手脚+骨骼"            |
|  决定做什么、怎么做                   保证做得对、做得安全             |
|                                                                     |
+-------------------------------------------------------------------+
```

---

### 3.5 AI 专属能力层边界

#### AI 模型 + 原子能力（16 项）— Agent 平台专属

| 能力 | 说明 | aPaaS 是否可调用 |
|:---|:---|:---|
| LLM / 文本生成 | 大语言模型推理 | 不可，仅 Agent 内部使用 |
| 嵌入模型 | 文本向量化 | 不可，Agent 内部 |
| 长上下文模型 | 超长文本处理 | 不可，Agent 内部 |
| 中文小模型 | 轻量中文任务 | 不可，Agent 内部 |
| 多模态 | 图片/文档理解 | 不可，Agent 内部 |
| 向量数据库 | 语义检索 | 不可，Agent 内部 |
| 智能网络检索 | 互联网搜索 | 不可，Agent 内部 |
| 文档解析 | PDF/Word/Excel 解析 | 可考虑暴露为统一服务 |
| 实时语音识别 | 语音转文字 | 可考虑暴露为统一服务 |
| 录音文件识别 | 录音转写 | 可考虑暴露为统一服务 |
| 热词库 | 中文专业术语 | 不可，Agent 内部 |
| 记忆管理器 | 长期记忆 CRUD | 不可，Agent 内部 |
| 腾讯天御 | 内容安全 | 可考虑暴露为统一服务 |
| 效果评估 | AI 质量评估 | 不可，Agent 内部 |
| LLM 链路追踪 | AI 调用追踪 | 不可，Agent 内部 |
| AI 生图 | 图片生成 | 可考虑暴露为统一服务 |

#### 企业级集成能力（6 项）— aPaaS 平台专属

| 能力 | 说明 | Agent 如何使用 |
|:---|:---|:---|
| Open API | RESTful 接口暴露 | Agent Tool 通过 Open API 调用 aPaaS 服务 |
| Bulk API | 批量数据操作 | Agent 的 `batch_data` Skill 调用 Bulk API |
| 数据转换 | ETL 转换 | Agent 不直接使用 |
| 协议转换 | 多协议适配 | Agent 不直接使用 |
| 集成编排 | 外部系统集成 | Agent 可通过 MCP 接入集成编排的结果 |
| 监控告警 | 集成健康监控 | Agent 不直接使用 |

---

### 3.6 AI Trust Layer 边界（v3 新增）

| 能力 | 归属 | 实现位置 | 与统一服务的关系 |
|:---|:---|:---|:---|
| PII 数据掩码 | AI 专属 | Agent InputTransformMiddleware | 掩码规则可从统一数据管理获取 |
| Prompt 注入防护 | AI 专属 | Agent ContentReviewMiddleware | 独立于 aPaaS |
| 输出验证 | AI 专属 | Agent OutputValidationMiddleware | 独立于 aPaaS |
| 零数据保留 | AI 专属 | Agent 运行时策略 | 需与统一数据管理策略对齐 |
| 毒性检测 | AI 专属 | Agent ContentReviewMiddleware | 独立于 aPaaS |
| HITL 检查点 | **交叉** | Agent HITLMiddleware 发起 + 统一审批流执行 | 审批流复用 aPaaS 审批引擎 |
| Plan Mode | AI 专属 | Agent PlanningNode 展示 | 前端展示可复用 aPaaS UI 组件 |
| 审计日志 | **交叉** | Agent TracingMiddleware 产生 + 统一审计存储 | 日志写入统一审计系统 |
| LLM 链路追踪 | AI 专属 | Agent ai_trace_span 表 | 可汇入统一观测中心 |

---

### 3.7 统一平台服务边界（AI + aPaaS 共享）

| 服务域 | Agent 侧如何使用 | aPaaS 侧如何使用 | 统一要求 |
|:---|:---|:---|:---|
| **身份与认证** | Agent 继承用户登录态，以用户身份执行操作 | 用户直接登录操作 | 单点登录，Agent 无需独立认证 |
| **权限与访问控制** | Agent 的数据访问受 Permission Sets 约束（透传 user_id） | 用户操作受同一权限体系约束 | Agent 不能获得超越用户本身的权限 |
| **数据管理** | Agent 操作的数据遵循统一加密/归档/脱敏策略 | 同一策略 | 数据生命周期统一管理 |
| **审计与合规** | Agent 每次 Tool 调用产生审计日志 | 用户每次操作产生审计日志 | 统一审计链路，Agent 操作可追溯到发起用户 |
| **应用治理** | Agent 应用纳入统一发布/安装/监控 | 同一治理体系 | Agent 应用也有版本、沙盒、灰度 |
| **多端适配** | Agent 对话 UI 适配多端 | 业务 UI 适配多端 | 共享品牌/风格/布局框架 |
| **零信任与 API 治理** | Agent 的 MCP 调用受 API 网关治理 | 同一网关策略 | 默认拒绝，显式授权 |

---

## 四、关键交互接口细化

### 4.1 Agent 调用 aPaaS 的调用链路

```
Agent Tool (Python)
    |
    | HTTP/gRPC 调用
    v
aPaaS API 网关 (paas-gateway)
    |
    | 鉴权 + 限流 + 路由
    v
aPaaS 微服务 (Java Spring Boot)
    |-- paas-entity-service     <-- query_data / modify_data
    |-- paas-metadata-service   <-- query_schema / modify_schema
    |-- paas-privilege-service  <-- query_permission
    |-- paas-rule-service       <-- 校验规则执行
    +-- paas-layout-service     <-- UI 布局信息
    |
    | 业务规则执行 + 数据权限过滤
    v
数据库 (paas_entity_data / paas_metarepo)
```

### 4.2 aPaaS 调用 Agent 的场景

| 场景 | 触发方式 | 说明 |
|:---|:---|:---|
| 页面内嵌 Agent 对话 | 前端 JS SDK 调用 Agent SSE 接口 | aPaaS 页面嵌入 Agent 浮窗 |
| 工作流中调用 Agent | 工作流节点配置 Agent Action | Agent 作为流程中的一个执行节点 |
| 自动流触发 Agent | 事件触发 Agent 执行 | 如"新客户创建时自动生成欢迎方案" |
| 智能字段填充 | 字段配置 AI 自动填充 | aPaaS 调用 Agent 的 LLM 能力 |
| 智能推荐 | 列表/详情页推荐区域 | aPaaS 调用 Agent 的推理能力 |

### 4.3 元数据同步机制

```
aPaaS 元数据变更
    |
    | 变更事件（MQ / Webhook）
    v
Agent 元数据描述管理
    |
    | 重新生成语义描述
    v
Agent Tool Schema 更新
    |
    | 下一轮对话生效
    v
LLM 感知最新业务对象结构
```

**关键约束**：
- Agent 侧的元数据描述是 aPaaS 元数据的"只读投影"
- Agent 不能直接修改 aPaaS 的元模型定义（必须通过 `modify_schema` Tool 经 aPaaS API）
- 元数据变更的权威源始终在 aPaaS 侧

### 4.4 权限传递机制

```
用户登录 (统一认证)
    |
    | JWT Token (含 user_id, tenant_id, roles)
    v
Agent 会话创建
    |
    | 提取 user_id + tenant_id 写入 GraphState
    v
Agent Tool 调用 aPaaS API
    |
    | 请求头携带: X-User-Id + X-Tenant-Id + Authorization
    v
aPaaS 微服务
    |
    | 基于 user_id 执行行级数据权限过滤
    | 基于 roles 执行功能权限校验
    v
返回用户有权看到的数据
```

**核心约束**：Agent 永远不能以"超级管理员"身份访问数据，必须继承发起用户的权限边界。

---

## 五、数据归属边界

### 5.1 Agent 平台独占数据

| 数据类型 | 存储 | 说明 |
|:---|:---|:---|
| 会话历史 (messages) | Agent PG | 对话消息、多模态内容 |
| 长期记忆 (memories) | Agent PG + 向量库 | profile/preferences/agent_rules/entities |
| Agent 配置 | Agent PG | Agent 定义、Skill 定义、Tool 配置 |
| 执行追踪 (traces) | Agent PG (ai_trace_span) | LLM 调用链路、Tool 执行记录 |
| 检查点 (checkpoints) | Redis | 会话状态快照 |
| 知识库索引 | 向量数据库 | RAG 文档向量 |
| 评估数据 | Agent PG | 测试用例、评估结果 |
| Skill 执行统计 | Agent PG | 技能调用次数、成功率、耗时 |

### 5.2 aPaaS 平台独占数据

| 数据类型 | 存储 | 说明 |
|:---|:---|:---|
| 元模型定义 | paas_metarepo_common (p_meta_model/item/link/option) | 业务对象 Schema |
| 元数据实例 | p_common_metadata / p_tenant_metadata | 字段配置、布局、规则等 |
| 业务数据 | paas_entity_data (p_tenant_data_0~1999) | 客户/商机/联系人等实际数据 |
| 权限配置 | paas_privilege_service | 角色/权限/共享规则 |
| 用户账号 | paas_auth (p_user/p_passport) | 用户身份信息 |
| 流程定义 | 工作流/审批流/自动流表 | 业务流程配置 |
| 布局配置 | paas-layout-service | 页面布局元数据 |
| 集成配置 | 集成编排表 | 外部系统连接配置 |

### 5.3 共享/交叉数据

| 数据类型 | 权威源 | 消费方 | 同步方式 |
|:---|:---|:---|:---|
| 用户身份 (user_id/tenant_id) | aPaaS (paas_auth) | Agent (GraphState) | 登录时 JWT 传递 |
| 元数据 Schema | aPaaS (p_meta_model/item) | Agent (元数据描述) | 事件驱动同步 |
| 审计日志 | 双方各自产生 | 统一审计系统 | 双写或异步汇聚 |
| 操作结果 | aPaaS (业务数据变更) | Agent (Tool 返回值) | 实时 API 响应 |
| 权限定义 | aPaaS (privilege) | Agent (权限过滤) | API 调用时实时校验 |

---

## 六、Tool 与 aPaaS 服务的映射关系

### 6.1 Agent Tool 到 aPaaS 微服务的精确映射

| Agent Tool | aPaaS 微服务 | aPaaS API 端点 | 数据流向 |
|:---|:---|:---|:---|
| `query_data` | paas-entity-service | GET /api/entity/{entityApiKey}/list | Agent 读 aPaaS 数据 |
| `modify_data` (create) | paas-entity-service | POST /api/entity/{entityApiKey} | Agent 写 aPaaS 数据 |
| `modify_data` (update) | paas-entity-service | PUT /api/entity/{entityApiKey}/{id} | Agent 写 aPaaS 数据 |
| `modify_data` (delete) | paas-entity-service | DELETE /api/entity/{entityApiKey}/{id} | Agent 写 aPaaS 数据 |
| `analyze_data` | paas-entity-service | POST /api/entity/{entityApiKey}/aggregate | Agent 读 aPaaS 聚合 |
| `query_schema` | paas-metadata-service | GET /api/metadata/entity/{apiKey} | Agent 读 aPaaS 元数据 |
| `modify_schema` | paas-metadata-service | POST /api/metadata/entity/{apiKey}/items | Agent 写 aPaaS 元数据 |
| `query_permission` | paas-privilege-service | GET /api/privilege/check | Agent 读 aPaaS 权限 |

### 6.2 不经过 aPaaS 的 Agent 独立 Tool

| Agent Tool | 依赖 Plugin | 完全在 Agent 侧执行 | 说明 |
|:---|:---|:---|:---|
| `web_search` | search-plugin | 是 | 调用外部搜索引擎 |
| `company_info` | company-data-plugin | 是 | 调用工商数据 API |
| `financial_report` | financial-data-plugin | 是 | 调用财报数据 API |
| `search_memories` | memory-plugin | 是 | 检索 Agent 侧记忆 |
| `save_memory` | memory-plugin | 是 | 写入 Agent 侧记忆 |
| `ask_user` | 无 | 是 | 向用户提问 |
| `generate_image` | image-gen-plugin | 是 | 调用 AI 生图 |
| `load_file_content` | document-parse-plugin | 是 | 解析上传文件 |
| `delegate_task` | 无 | 是 | 启动子 Agent |
| `start_async_task` | 无 | 是 | 启动异步任务 |
| `send_notification` | notification-plugin | 是 | 发送通知（可能调用 aPaaS 通知服务） |

---

## 七、Skill 与 aPaaS 业务流程的边界

### 7.1 Skill vs aPaaS 工作流的本质区别

| 维度 | Agent Skill | aPaaS 工作流 |
|:---|:---|:---|
| **触发方式** | LLM 推理判断何时调用 | 条件规则触发（字段变更/定时/事件） |
| **执行主体** | LLM + Tool 调用链 | Java 流程引擎 |
| **灵活性** | 高（LLM 可根据上下文调整步骤） | 低（预定义路径，分支有限） |
| **确定性** | 低（LLM 输出非确定性） | 高（规则确定性执行） |
| **适用场景** | 探索性任务、分析、诊断、建议 | 标准化流程、审批、数据流转 |
| **人工介入** | HITL 检查点（高风险时暂停） | 审批节点（流程中固定节点） |
| **可审计性** | Agent Trace（ai_trace_span） | 流程日志（流程实例表） |

### 7.2 协作模式：Agent Skill 编排 aPaaS 工作流

```
场景：销售经理说"帮我把这批线索分配给团队"

Agent Skill: batch_data
    |
    | 步骤 1: query_data 获取待分配线索
    | 步骤 2: analyze_data 分析团队负载
    | 步骤 3: ask_user 确认分配方案
    | 步骤 4: modify_data 批量更新负责人
    |              |
    |              v
    |         aPaaS 自动流触发
    |              |
    |              | "负责人变更" 事件
    |              v
    |         aPaaS 工作流执行
    |              |-- 发送通知给新负责人
    |              |-- 更新 SLA 计时
    |              +-- 记录操作日志
    |
    | 步骤 5: Agent 确认执行完成，生成摘要
```

**边界原则**：
- Agent Skill 负责"智能决策"（分析负载、推荐方案）
- aPaaS 工作流负责"标准执行"（通知、SLA、日志）
- Agent 的 modify_data 触发 aPaaS 的自动流，两者通过数据变更事件解耦

### 7.3 禁止越界的场景

| 禁止行为 | 原因 | 正确做法 |
|:---|:---|:---|
| Agent 直接写数据库绕过 aPaaS API | 绕过校验规则和权限 | 必须通过 paas-entity-service API |
| Agent 自行实现审批逻辑 | 审批流有法律效力，需要 aPaaS 保证 | 调用 aPaaS 审批流 API |
| Agent 修改权限配置 | 权限变更影响全局 | 通过 HITL + aPaaS privilege API |
| aPaaS 工作流直接调用 LLM | 工作流需要确定性 | 通过 Agent API 间接调用 |
| aPaaS 直接读写 Agent 记忆 | 记忆是 Agent 私有数据 | 通过 Agent 提供的记忆 API |

---

## 八、交叉协同区域详细分析

### 8.1 元数据协同（最核心的交叉点）

```
                    aPaaS 侧                          Agent 侧
              +-------------------+              +-------------------+
              | p_meta_model      |              | 元数据语义描述     |
              | p_meta_item       |  --同步-->   | (Agent 可理解的    |
              | p_meta_link       |              |  自然语言描述)     |
              | p_meta_option     |              |                   |
              +-------------------+              +-------------------+
                    |                                    |
                    | 定义业务对象结构                      | 告诉 LLM 业务含义
                    v                                    v
              +-------------------+              +-------------------+
              | 业务数据 CRUD      |              | Tool Schema 生成  |
              | 校验规则执行        |              | (input_schema 中  |
              | 权限过滤           |              |  包含字段列表)    |
              +-------------------+              +-------------------+
```

**协同机制**：
1. aPaaS 元数据变更时，发布事件通知 Agent 侧
2. Agent 的"元数据描述工具"重新生成语义描述
3. 语义描述包含：实体中文名、字段含义、关联关系、业务规则提示
4. LLM 通过语义描述理解"客户"有哪些字段、什么含义

### 8.2 UI 协同（A2UI 协议）

| 层面 | Agent 侧职责 | aPaaS 侧职责 |
|:---|:---|:---|
| 组件触发 | Tool.render_hint 指定渲染组件 | 提供组件库（React 组件） |
| 数据准备 | Tool 返回结构化数据 | 组件消费数据并渲染 |
| 交互反馈 | 接收用户在组件中的操作 | 组件发出交互事件 |
| 样式一致 | 遵循 aPaaS 设计规范 | 提供 Design Token |

### 8.3 Human-in-the-Loop 协同

| 环节 | Agent 侧 | aPaaS 侧 | 统一服务 |
|:---|:---|:---|:---|
| 风险识别 | HITLMiddleware 判断 is_destructive | 无 | 无 |
| 审批发起 | Agent 暂停，发送审批请求 | 无 | 审批流引擎接收 |
| 审批执行 | 等待 | 审批人在 aPaaS UI 中审批 | 审批流驱动 |
| 结果回传 | 收到 approve/reject，恢复执行 | 无 | 回调 Agent resume API |

### 8.4 可观测性协同

| 数据类型 | 产生方 | 存储 | 消费方 |
|:---|:---|:---|:---|
| Agent Trace (LLM 调用) | Agent TracingMiddleware | Agent PG (ai_trace_span) | Agent 可观测系统 |
| Tool 调用日志 | Agent AgentLoggingMiddleware | Agent PG | 统一审计 + Agent 监控 |
| aPaaS API 调用日志 | aPaaS 网关 | aPaaS 日志系统 | 统一观测中心 |
| 业务操作日志 | aPaaS 服务层 | paas_entity_data (操作日志表) | 统一审计 |
| 端到端链路 | 双方通过 trace_id 关联 | 各自存储 | 统一观测中心聚合展示 |

---

## 九、边界冲突场景与裁决规则

### 9.1 典型冲突场景

| 冲突场景 | 描述 | 裁决 |
|:---|:---|:---|
| Agent 想创建新字段 | Agent 的 modify_schema 要在实体上加字段 | 必须经过 aPaaS 元数据校验 + HITL 审批 |
| Agent 想批量删除数据 | 用户说"删掉所有测试客户" | HITL 必须审批 + aPaaS 侧执行软删除 |
| Agent 记忆与业务数据冲突 | 记忆中记录"客户A是大客户"但数据已变 | 以 aPaaS 业务数据为准，记忆标记过期 |
| 工作流与 Agent 并发操作 | Agent 在修改数据时工作流也在修改 | aPaaS 侧乐观锁保证，Agent 收到冲突错误后重试 |
| Agent 推荐的操作违反业务规则 | Agent 建议设置折扣 > 100% | aPaaS 校验规则拦截，Agent 收到错误后调整 |

### 9.2 裁决原则

```
1. 数据正确性 > Agent 便利性
   - aPaaS 的校验规则、权限规则是硬约束
   - Agent 不能绕过，只能适应

2. 业务数据以 aPaaS 为准
   - Agent 记忆是"认知"，aPaaS 数据是"事实"
   - 冲突时以事实为准

3. 安全性由统一服务兜底
   - Agent 的 Trust Layer 是第一道防线
   - 统一权限/审计是最终保障

4. 用户体验由 Agent 主导
   - 交互方式、对话体验、智能推荐由 Agent 决定
   - aPaaS 提供数据和规则支撑
```

---

## 十、总结：一句话边界定义

| 平台 | 一句话定义 | 核心职责 |
|:---|:---|:---|
| **Agent 平台** | "理解意图、规划执行、记住偏好、协调资源" | 智能决策层 — 决定做什么、怎么做 |
| **aPaaS 平台** | "定义模型、执行规则、保障数据、驱动流程" | 业务执行层 — 保证做得对、做得安全 |
| **统一服务** | "认证身份、控制权限、审计合规、治理 API" | 安全治理层 — 确保谁能做、做了有记录 |
| **共同底座** | "多租户隔离、元数据驱动、微服务运行" | 基础设施层 — 让一切能跑起来 |

### 关键隐喻

```
Agent = 大脑（思考、决策、记忆、学习）
aPaaS = 身体（骨骼结构、肌肉执行、神经反射）
统一服务 = 免疫系统（识别入侵、保护边界、记录异常）
共同底座 = 循环系统（供血、供氧、维持生命）
```

### 判断任何能力归属的三问法

```
Q1: 这个能力需要 LLM 推理吗？
    是 → Agent 平台

Q2: 这个能力操作业务数据/执行业务规则吗？
    是 → aPaaS 平台

Q3: 这个能力是跨 AI 和 aPaaS 的横向治理吗？
    是 → 统一平台服务
```
