# Plugin / Tool / Skill 边界深度分析

> 本文档从行业实践出发，重新定义三者的本质区别和边界规则，修正当前设计中的分类混乱。

---

## 一、行业实践中的三者定义

### 1.1 各框架的分类方式

| 框架 | 对应 Tool 的概念 | 对应 Skill 的概念 | 对应 Plugin 的概念 |
|------|-----------------|------------------|-------------------|
| Claude Code | Tool（35+ 字段） | Skill（prompt 模板） | Plugin（提供 skill + hook） |
| Salesforce Agentforce | Action（原子操作） | Topic/Subagent（业务域） | — |
| LangChain DeepAgents | Tool（function） | —（无独立概念） | Middleware（能力注入） |
| Hermes Agent | Tool（registry 注册） | Skill（.md 文件） | Plugin（memory provider 等） |
| OpenAI Assistants | Function（function calling） | —（无独立概念） | —（无独立概念） |

### 1.2 提炼出的本质区别

```
Tool（工具）= 一次原子操作
  本质: 输入参数 → 执行 → 返回结果
  特征: 无状态、单步、确定性、LLM 直接调用
  类比: 函数调用
  例子: 查询一条数据、搜索一个关键词、调用一个 API

Skill（技能）= 一段业务知识 + 执行策略
  本质: 一个精心设计的 prompt，指导 Agent 如何完成某类任务
  特征: 有步骤、有判断、有策略、需要多轮 Tool 调用才能完成
  类比: SOP（标准操作流程）
  例子: "如何诊断配置问题"、"如何做数据迁移"、"如何评估客户资质"

Plugin（插件）= 一个可插拔的能力模块
  本质: 向 Agent 系统注入新的能力（工具 + 中间件 + 配置），可独立启用/禁用/替换
  特征: 有生命周期、有配置、有状态、影响 Agent 的整体行为
  类比: 浏览器扩展
  例子: 记忆系统、通知渠道、LLM 提供商、审计日志
```

### 1.3 判断边界的三个问题

对于任何一个能力，问三个问题就能确定它属于哪一层：

```
Q1: LLM 能直接调用它吗？（一次调用，一次返回）
  → 是 → Tool

Q2: 它需要多步推理、多次工具调用才能完成吗？
  → 是 → Skill

Q3: 它是一个独立的基础设施能力，需要初始化/配置/可替换吗？
  → 是 → Plugin
```

---

## 二、当前设计的边界问题

### 2.1 分类正确的

| 能力 | 当前分类 | 判断 | 正确性 |
|------|---------|------|--------|
| query_schema | Tool | 一次查询，一次返回 | ✅ 正确 |
| query_data | Tool | 一次 CRUD，一次返回 | ✅ 正确 |
| web_search | Tool | 一次搜索，一次返回 | ✅ 正确 |
| company_info | Tool | 一次查询，一次返回 | ✅ 正确 |
| ask_user | Tool | 一次提问，一次返回 | ✅ 正确 |
| llm-plugin | Plugin | 基础设施，可替换提供商 | ✅ 正确 |
| memory-plugin | Plugin | 基础设施，可替换后端 | ✅ 正确 |
| notification-plugin | Plugin | 基础设施，可替换渠道 | ✅ 正确 |
| diagnose | Skill | 多步排查流程 | ✅ 正确 |
| config_entity | Skill | 多步配置向导 | ✅ 正确 |
| migration | Skill | 多步迁移流程 | ✅ 正确 |

### 2.2 分类有问题的

| 能力 | 当前分类 | 问题 | 应该是 |
|------|---------|------|--------|
| search_memories | Tool（由 memory-plugin 提供） | 一次搜索一次返回，是 Tool 没错。但它不应该由 Plugin "提供"工具——Plugin 应该提供基础设施，Tool 应该由 ToolRegistry 统一管理 | **Tool**（内置），内部调用 memory-plugin 的接口 |
| search_memories | 同上 | 同上 | **Tool**（内置） |
| save_memory | 同上 | 同上 | **Tool**（内置） |
| send_notification | Tool（由 notification-plugin 提供） | 同上 | **Tool**（内置） |
| verify_config | Skill | 它的 prompt 本质上是"调用 query_schema 检查一堆规则"——这更像是一个**预定义的任务模板**，不需要多步推理 | **Skill** ✅ 但需要简化——它不需要 fork 子 Agent，inline 注入检查清单即可 |
| stuck | Skill | 它不是"技能"，它是 Agent 引擎的内部机制（ReflectionNode 的一部分） | **不应该是 Skill**，应该是 ReflectionNode 的内置逻辑 |
| remember | Skill | "记住这个"本质上就是调用 save_memory 工具——不需要一个 Skill 来包装 | **不应该是 Skill**，LLM 直接调用 save_memory 工具即可 |
| reflect | Skill | 同 stuck，是 ReflectionNode 的内部机制 | **不应该是 Skill**，是引擎内置逻辑 |
| skillify | Skill | 将操作转为技能——这确实需要多步推理 | ✅ 正确 |
| batch_data | Skill | "批量操作"本质上是多次调用 query_data——需要策略（分批、确认、错误处理） | ✅ 正确 |
| iterate | Skill | "迭代执行"是一种执行策略，不是业务技能 | **不应该是 Skill**，应该是 PlanningNode 的规划策略 |
| data_analysis | Skill | 数据分析需要多步（查元数据→查数据→聚合→洞察） | ✅ 正确 |
| permission_audit | Skill | 权限审计需要多步排查 | ✅ 正确 |
| analyze_data | Tool | 一次聚合查询，一次返回 | ✅ 正确 |
| api_call | Tool | 一次 API 调用，一次返回 | ✅ 正确 |

### 2.3 Plugin 提供 Tool 的问题

当前设计中 memory-plugin "提供" search_memories/search_memories/save_memory 三个工具，notification-plugin "提供" send_notification 工具。这个设计有问题：

**问题**: Plugin 和 Tool 的职责混淆了。Plugin 应该提供**基础设施能力**（存储后端、检索引擎、通知渠道），Tool 应该是 LLM 调用的**统一接口**。让 Plugin 直接注册 Tool 会导致：
1. Tool 的生命周期依赖 Plugin（Plugin 禁用时 Tool 消失，LLM 不知道为什么工具没了）
2. 同一个 Tool 可能有多个 Plugin 实现（两个 memory plugin 都注册 search_memories？）
3. ToolRegistry 不再是工具的唯一真相源

**正确做法**: Tool 始终由 ToolRegistry 管理，Tool 内部通过 PluginContext 调用 Plugin 的接口：

```
错误:  memory-plugin → 注册 search_memories Tool → ToolRegistry
正确:  ToolRegistry 注册 search_memories Tool → Tool.call() 内部调用 context.memory.recall()
       如果 context.memory 为 None（Plugin 未启用）→ Tool.is_enabled() 返回 False → LLM 看不到此工具
```

---

## 三、修正后的边界定义

### 3.1 Tool（工具）— LLM 的手

```
定义: 一次原子操作。LLM 通过 function calling 直接调用，输入参数，返回结果。
生命周期: 由 ToolRegistry 统一管理，AgentFactory 初始化时注册。
状态: 无状态（每次调用独立）。
谁调用: LLM（通过 tool_use block）。
```

完整的 Tool 列表（全部由 ToolRegistry 管理）：

| Tool | 功能 | 依赖的 Plugin | is_enabled 条件 |
|------|------|-------------|----------------|
| query_schema | 查询元数据定义 | — | 始终启用 |
| query_data | 业务数据 CRUD | — | 始终启用 |
| analyze_data | 数据聚合统计 | — | 始终启用 |
| query_permission | 权限配置查询 | — | 始终启用 |
| web_search | 网络搜索 | search-plugin | context.search is not None |
| web_fetch | 网页内容提取 | search-plugin | context.search is not None |
| company_info | 企业工商查询 | company-data-plugin | context.company is not None |
| financial_report | 上市公司财报 | financial-data-plugin | context.financial is not None |
| api_call | 外部 API 调用 | — | 租户有配置的 API 连接 |
| mcp_tool | MCP 协议扩展 | — | 有已连接的 MCP Server |
| ask_user | 向用户提问 | — | 始终启用 |
| search_memories | 搜索长期记忆 | memory-plugin | context.memory is not None |
| search_memories | 浏览记忆目录 | memory-plugin | context.memory is not None |
| save_memory | 写入长期记忆 | memory-plugin | context.memory is not None |
| send_notification | 推送通知 | notification-plugin | context.notification is not None |
| delegate_task | 派生同步子 Agent | — | 仅主 Agent 可用 |
| start_async_task | 派生异步子 Agent | — | 仅主 Agent 可用 |

**关键变化**: search_memories / save_memory / send_notification 不再由 Plugin "提供"，而是始终注册在 ToolRegistry 中，通过 `is_enabled()` 检查 Plugin 是否可用。

### 3.2 Skill（技能）— Agent 的 SOP

```
定义: 一段业务知识 + 执行策略的 prompt 模板。指导 Agent 如何完成某类复杂任务。
生命周期: 由 SkillRegistry 管理，支持内置 + 文件加载 + 动态创建。
状态: 无状态（每次使用时注入 prompt）。
谁调用: Agent 自己决定使用哪个 Skill（PlanningNode 或 ExecutionNode 中）。
执行方式: inline（注入当前对话）或 fork（启动子 Agent）。
```

修正后的 Skill 列表（去掉不应该是 Skill 的）：

| Skill | 功能 | 执行方式 | 为什么是 Skill 而非 Tool |
|-------|------|---------|------------------------|
| verify_config | 元数据配置校验 | inline | 需要按检查清单逐项校验，不是一次调用 |
| diagnose | 业务问题诊断 | fork | 需要多步排查（元数据→数据→权限→历史经验） |
| config_entity | 业务对象配置向导 | fork | 需要多步引导（需求理解→方案设计→确认→执行→校验） |
| batch_data | 批量数据操作 | fork | 需要策略（评估影响→确认→分批执行→报告） |
| data_analysis | 业务数据分析 | fork | 需要多步（理解结构→采集→统计→洞察→报告） |
| migration | 数据迁移 | fork | 需要多步（分析源→映射→确认→迁移→校验） |
| permission_audit | 权限审计 | fork | 需要多步排查（角色→权限→共享规则→分析） |
| skillify | 操作转技能 | fork | 需要分析对话提炼可复用流程 |

**去掉的**：
- ~~stuck~~ → 移入 ReflectionNode 内置逻辑（不是业务技能，是引擎机制）
- ~~remember~~ → LLM 直接调用 save_memory 工具（不需要 Skill 包装）
- ~~reflect~~ → 移入 ReflectionNode 内置逻辑（不是业务技能，是引擎机制）
- ~~iterate~~ → 移入 PlanningNode 的规划策略（不是业务技能，是执行策略）

### 3.3 Plugin（插件）— 系统的器官

```
定义: 一个可插拔的基础设施能力模块。提供 Agent 运行所需的底层服务。
生命周期: AgentFactory 初始化时加载，运行期间不变。可独立启用/禁用/替换。
状态: 有状态（维护连接、缓存、配置）。
谁调用: Agent 引擎内部（Middleware / Node / Tool 通过 PluginContext 调用）。
```

Plugin 列表（不变）：

| Plugin | 提供什么 | 谁使用 | 可替换性 |
|--------|---------|--------|---------|
| llm-plugin | LLM 调用能力 | 所有 Node | DeepSeek / OpenAI / Anthropic |
| memory-plugin | 记忆存储 + 检索 + 遗忘 | MemoryMiddleware + 记忆类 Tool | filesystem / pgvector / elasticsearch |
| notification-plugin | 通知推送 | send_notification Tool | 站内信 / 钉钉 / 飞书 / 邮件 |
| audit-plugin | 审计日志 | AuditMiddleware | 文件 / 数据库 / ELK |
| search-plugin | 网络搜索 + 网页提取 | web_search / web_fetch Tool | Tavily / Bing / Google / SerpAPI |
| company-data-plugin | 企业工商数据 | company_info Tool | 天眼查 / 企查查 / 启信宝 |
| financial-data-plugin | 上市公司财务数据 | financial_report Tool | 巨潮资讯 / Wind / 东方财富 |

**设计原则**: 所有外部数据源都是 Plugin，因为供应商可替换。Tool 是 LLM 调用的稳定接口，Plugin 是底层供应商的适配层。换供应商时只改 Plugin 配置，不改 Tool 接口，LLM 完全无感知。

```
Tool（稳定接口，LLM 调用）          Plugin（可替换适配层，运维配置）
─────────────────────              ─────────────────────────────
web_search Tool                    search-plugin
  → call() 内部调用                  ├── TavilyAdapter（当前）
    context.search.query()           ├── BingAdapter（备选）
                                     └── GoogleAdapter（备选）

company_info Tool                  company-data-plugin
  → call() 内部调用                  ├── TianyanchaAdapter（当前）
    context.company.query()          ├── QichachaAdapter（备选）
                                     └── QixinbaoAdapter（备选）

financial_report Tool              financial-data-plugin
  → call() 内部调用                  ├── CninfoAdapter（当前）
    context.financial.query()        ├── WindAdapter（备选）
                                     └── EastmoneyAdapter（备选）
```

**关键变化**: Plugin 不再直接注册 Tool。Plugin 提供接口（PluginContext.memory / PluginContext.notification），Tool 通过接口调用 Plugin 的能力。

---

## 四、三者的协作关系

```
用户: "帮我分析上个月的销售数据"

PlanningNode:
  → 识别为"数据分析"任务
  → 加载 data_analysis Skill 的 prompt（SOP）
  → 生成计划: 1.查元数据 2.查数据 3.聚合统计 4.生成洞察

ExecutionNode (Step 1):
  → LLM 根据 Skill prompt 决定调用 query_schema Tool
  → Tool.call() → ServiceBackend → paas-metadata-service API
  → 返回实体字段定义

ExecutionNode (Step 2):
  → LLM 决定调用 query_data Tool (action=query)
  → Tool.call() → ServiceBackend → paas-entity-service API
  → 返回业务数据

ExecutionNode (Step 3):
  → LLM 决定调用 analyze_data Tool
  → Tool.call() → ServiceBackend → 聚合统计
  → 返回统计结果

ExecutionNode (Step 4):
  → LLM 根据 Skill prompt 中的"输出报告"指引，生成分析报告

ReflectionNode:
  → 提取记忆: save_memory Tool → memory-plugin → 持久化
  → 通知用户: send_notification Tool → notification-plugin → 推送
```

```
三者的关系:
  Plugin 提供基础设施 → Tool 封装原子操作 → Skill 编排多步流程

  Plugin 不知道 Tool 的存在（只提供接口）
  Tool 不知道 Skill 的存在（只执行单步）
  Skill 不知道 Plugin 的存在（只编排 Tool 调用）

  唯一的耦合点是 PluginContext:
    Tool 通过 context.memory 调用 memory-plugin
    Tool 通过 context.notification 调用 notification-plugin
    Node 通过 context.llm 调用 llm-plugin
```

---

## 五、边界判断速查表

遇到新能力时，用这个表判断它属于哪一层：

| 判断条件 | → 分类 | 示例 |
|----------|--------|------|
| LLM 一次调用，一次返回结果 | Tool | 查询数据、搜索网络、调用 API |
| 需要多步推理、多次 Tool 调用、有业务 SOP | Skill | 诊断问题、配置向导、数据迁移 |
| 是 Agent 引擎的内部机制（用户不感知） | 引擎内置 | stuck 自救、反思、迭代重试 |
| 是可替换的基础设施（存储/通知/模型） | Plugin | 记忆后端、通知渠道、LLM 提供商 |
| 是 Agent 的执行策略（规划/调度） | Node 逻辑 | 任务分解、步骤调度、并行/串行 |
