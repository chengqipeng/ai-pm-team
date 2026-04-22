# DeepAgent vs Hermes Agent vs Claude Code — 逐维度代码级对比

> 基于 DeepAgent 当前代码、Hermes Agent v0.10.0 源码结构、Claude Code 泄露源码分析

---

## 一、架构定位对比

| 维度 | DeepAgent | Hermes Agent | Claude Code |
|------|-----------|-------------|-------------|
| 定位 | 2B CRM SaaS Agent 框架 | 自改进个人 AI Agent | 代码工程 Agentic CLI |
| 语言 | Python (LangChain) | Python (原生) | TypeScript (Bun + React Ink) |
| Agent 引擎 | `langchain.agents.create_agent` | 自建 `AIAgent` 循环 (`run_agent.py`) | 自建 `QueryEngine` (46K 行) |
| 工具数量 | 5 CRM 工具 + SkillsTool + AgentTool | 40+ 内置工具 | 17+ 核心工具 |
| 技能系统 | SKILL.md + inline/fork | SKILL.md + 自动生成 + agentskills.io 标准 | Prompt-native Skill + Plugin |
| 子 Agent | AgentTool + AgentFactory | delegate_tool + 隔离子 Agent | AgentTool + Coordinator/Worker + Mailbox |
| 记忆 | MemoryMiddleware + NoopEngine | 三层记忆（Session + FTS5 + User Model） | 三层压缩（Micro + Auto + Full Compact） |
| 开源 | 内部项目 | MIT 开源 (95.6K stars) | 商业产品（源码泄露分析） |

---

## 二、工具系统逐项对比

| 能力 | DeepAgent | Hermes Agent | Claude Code |
|------|-----------|-------------|-------------|
| 工具基类 | 自定义 `Tool` ABC + Pydantic `BaseTool` | 自建 registry + schema | 自建 Tool 基类 (~29K 行 TS) |
| 工具注册 | `ToolRegistry` + `ToolLoader`(缺) | `tools/registry.py` 中央注册 | 中央 Tool Registry |
| 动态描述 `description(input)` | ✅ `Tool.description(input_data)` | ❌ 静态描述 | ✅ 动态描述 |
| 延迟加载 `shouldDefer` | ✅ `Tool.should_defer` | ❌ | ✅ `shouldDefer + searchHint` |
| 搜索提示 `searchHint` | ✅ `Tool.search_hint` | ❌ | ✅ |
| 每工具结果预算 | ✅ `max_result_size_chars` (50K) | ❌ | ✅ `maxResultSizeChars` |
| 工具别名 | ✅ `Tool.aliases` | ❌ | ❌ |
| 只读/破坏性标记 | ✅ `is_read_only` / `is_destructive` | ❌ | ✅ 每工具权限级别 |
| 输入验证 | ✅ `validate_input()` | ❌ | ✅ Zod schema 验证 |
| 压缩协作 | ✅ `summary_threshold` / `summary_max_words` | ✅ `_summarize_tool_result` 按工具类型 | ✅ MicroCompact 本地裁剪 |
| 工具权限隔离 | ✅ `GuardrailMiddleware` 白名单 | ✅ `approval.py` 危险命令检测 | ✅ 每工具独立权限级别 |
| MCP 集成 | ❌ | ✅ `mcp_tool.py` (~1050 行) | ✅ MCP 服务器 + 指令注入 |
| 工具自动发现 | ❌ (缺 ToolLoader 目录扫描) | ✅ `discover_builtin_tools()` | ✅ 编译时注册 |

**DeepAgent 优势：** Tool 高级特性（aliases/search_hint/should_defer/max_result_size_chars/summary_threshold）是三者中最完整的元数据模型，Claude Code 有类似设计但 Hermes 缺失。

**DeepAgent 差距：** 缺 MCP 集成、缺工具自动发现（ToolLoader 目录扫描）、实际工具数量少（5 个 CRM 工具 vs Hermes 40+ vs Claude Code 17+）。

---

## 三、技能系统逐项对比

| 能力 | DeepAgent | Hermes Agent | Claude Code |
|------|-----------|-------------|-------------|
| 技能定义格式 | SKILL.md (YAML frontmatter + Markdown body) | SKILL.md (agentskills.io 标准) | Prompt-native + Plugin metadata |
| 技能加载 | `SkillLoader.discover()` 扫描目录 | `skill_commands.py` + Skills Hub | `loadPluginCommands.ts` |
| 技能注册 | `SkillRegistry` | 内存索引 + FTS5 搜索 | Plugin Registry |
| 技能执行 | `SkillExecutor` (inline/fork) | 直接注入 prompt | `SkillTool/prompt.ts` |
| inline 模式 | ✅ prompt 注入当前对话 | ✅ 等价 | ✅ 等价 |
| fork 模式 | ✅ 创建子 Agent 执行 | ✅ delegate_tool 子 Agent | ✅ AgentTool 子 Agent |
| 自动技能生成 | ❌ | ✅ 任务完成后自动创建 SKILL.md | ❌ |
| 技能自改进 | ❌ | ✅ 使用中自动优化 | ❌ |
| 技能市场 | ❌ | ✅ Skills Hub (浏览/安装) | ❌ |
| 技能安装器 | 占位 `NotImplementedError` | ✅ `installer.py` | ❌ |
| 技能验证 | ✅ `SkillLoader.validate()` | ✅ `validation.py` | ❌ (Plugin metadata 验证) |
| allowed_tools 约束 | ✅ 技能声明允许的工具列表 | ❌ | ❌ |
| 技能参数化 | ✅ `{arg}` 占位符替换 | ✅ | ❌ |

**DeepAgent 优势：** `allowed_tools` 约束（技能级工具白名单）是独有设计，适合 SaaS 多租户场景。inline/fork 双模式 + AgentFactory 缓存。

**DeepAgent 差距：** 缺自动技能生成（Hermes 的核心卖点）、缺技能自改进、缺技能市场。

---

## 四、子 Agent 系统逐项对比

| 能力 | DeepAgent | Hermes Agent | Claude Code |
|------|-----------|-------------|-------------|
| 子 Agent 工具 | `AgentTool` (Pydantic BaseTool) | `delegate_tool.py` | `AgentTool.tsx` |
| 子 Agent 工厂 | `AgentFactory` (LRU 缓存 + max_depth=3) | 直接 spawn 隔离进程 | 同一 Tool Registry 内 spawn |
| 嵌套深度限制 | ✅ max_depth=3 | ❌ (进程隔离天然限制) | ❌ (扁平架构) |
| 实例缓存 | ✅ LRU OrderedDict | ❌ (每次新建) | ❌ |
| 并发限制 | ✅ `SubagentLimitMiddleware` (max=3) | ❌ | ❌ |
| Coordinator/Worker | ❌ | ❌ | ✅ Mailbox 模式 + 原子 claim |
| 异步 fire-and-forget | ✅ `AsyncSubAgentManager` | ✅ 并行 workstream | ❌ |
| 子 Agent 配置 | `SubagentConfig` dataclass | 无独立配置 | 无独立配置 |
| 子 Agent 注册表 | `SubagentRegistry` | ❌ | ❌ |

**DeepAgent 优势：** AgentFactory LRU 缓存 + SubagentConfig 独立配置 + SubagentLimitMiddleware 并发限制，是三者中最完整的子 Agent 管理体系。

**DeepAgent 差距：** 缺 Coordinator/Worker Mailbox 模式（Claude Code 的危险操作审批机制）。

---

## 五、记忆与上下文压缩逐项对比

| 能力 | DeepAgent | Hermes Agent | Claude Code |
|------|-----------|-------------|-------------|
| **Session 记忆** | `SummarizationMiddleware` (token 估算 → 摘要) | Session memory (标准上下文管理) | MicroCompact (本地裁剪，0 API 调用) |
| **持久化记忆** | `MemoryMiddleware` + `NoopMemoryEngine` (协议已定义) | FTS5 全文搜索 (~10ms/10K 文档) | 无独立持久化（依赖 context files） |
| **用户画像** | `MemoryDimension.USER_PROFILE` (协议已定义) | 自动 User Model (跨 session 偏好) | 无 |
| **维度化检索** | ✅ 4 维度 (user_profile/customer_context/task_history/domain_knowledge) | ❌ 扁平检索 | ❌ |
| **向量检索** | ❌ (NoopEngine 占位) | ❌ (FTS5 关键词) | ❌ |
| **记忆提取** | `MemoryMiddleware.aafter_agent` 异步提取 | 自动 skill 生成 + 记忆持久化 | 无自动提取 |
| **压缩层级** | 1 层 (SummarizationMiddleware) | 1 层 (context compression) | 3 层 (Micro + Auto + Full Compact) |
| **压缩触发** | token 估算 > 75% 阈值 | 接近上下文窗口 | 接近上下文窗口 + 13K buffer |
| **压缩熔断** | ❌ | ❌ | ✅ 3 次失败后停止 |
| **压缩后文件重注入** | ❌ | ❌ | ✅ 最近访问文件 (≤5K tokens/file) |
| **压缩后预算重置** | ❌ | ❌ | ✅ 重置到 50K tokens |

**DeepAgent 优势：** 维度化记忆检索（4 维度）是独有设计，适合 CRM 场景（用户画像 + 客户上下文 + 任务历史 + 领域知识）。MemoryEngine 协议设计良好，可插拔。

**DeepAgent 差距：** 压缩只有 1 层（vs Claude Code 3 层），缺压缩熔断、缺压缩后文件重注入、缺 FTS5 全文搜索、MemoryEngine 仍是 Noop 占位。

---

## 六、中间件系统逐项对比

| 中间件 | DeepAgent | Hermes Agent | Claude Code |
|--------|-----------|-------------|-------------|
| 工具错误处理 | ✅ `ToolErrorHandlingMiddleware` | ✅ 内置 | ✅ 内置 |
| 悬空工具调用修复 | ✅ `DanglingToolCallMiddleware` | ❌ | ❌ |
| 安全护栏 | ✅ `GuardrailMiddleware` | ✅ `approval.py` | ✅ 每工具权限 |
| 循环检测 | ✅ `LoopDetectionMiddleware` (hash + 滑动窗口) | ❌ | ❌ (QueryEngine 内置) |
| 上下文压缩 | ✅ `SummarizationMiddleware` | ✅ `context_compressor.py` | ✅ 三层压缩 |
| 日志追踪 | ✅ `AgentLoggingMiddleware` | ❌ (内置日志) | ✅ 遥测系统 |
| 澄清中断 | ✅ `ClarificationMiddleware` | ❌ | ❌ (Hooks 系统) |
| 记忆注入 | ✅ `MemoryMiddleware` | ✅ 内置 | ❌ (context files) |
| 输出验证 | ✅ `OutputValidationMiddleware` | ❌ | ❌ |
| 子 Agent 限制 | ✅ `SubagentLimitMiddleware` | ❌ | ❌ |
| 输入转换 | ✅ `InputTransformMiddleware` | ❌ | ❌ |
| 标题生成 | ✅ `TitleMiddleware` | ❌ | ❌ |
| 计划模式 | ✅ `TodoMiddleware` | ❌ | ✅ Task tracking |
| Prompt 缓存 | ❌ | ❌ | ✅ `prompt_caching.py` (Anthropic) |
| 遥测指标 | ❌ | ❌ | ✅ 挫败感指标 + continue 计数 |
| Hooks 系统 | ❌ | ❌ | ✅ 17 个生命周期事件 |

**DeepAgent 优势：** 13 个独立中间件，全部继承 `AgentMiddleware`，是三者中最模块化的中间件栈。DanglingToolCall、LoopDetection、Clarification、OutputValidation、SubagentLimit 是独有的。

**DeepAgent 差距：** 缺 Prompt 缓存、缺遥测指标、缺 Hooks 系统（Claude Code 的 17 个生命周期事件）。

---

## 七、配置与部署对比

| 能力 | DeepAgent | Hermes Agent | Claude Code |
|------|-----------|-------------|-------------|
| 配置格式 | Python dataclass 硬编码 | TOML (`~/.hermes/config.toml`) | JSON + 环境变量 |
| 环境变量覆盖 | ❌ | ✅ | ✅ |
| 模型切换 | 代码修改 | `hermes model` 命令 | `/model` 命令 |
| 多模型路由 | ❌ | ✅ (辅助 LLM 按任务选模型) | ❌ (单模型) |
| 部署方式 | Python 包 | CLI + Docker + VPS + Serverless | npm 包 |
| 消息平台 | 无 | 6 个 (Telegram/Discord/Slack/WhatsApp/Signal/CLI) | CLI only |
| 定时任务 | ❌ | ✅ 内置 cron 调度 | ❌ |
| Feature Flags | ❌ | ❌ | ✅ 108 个编译时特性门控 |

---

## 八、独有能力汇总

### DeepAgent 独有
1. **Plugin 生命周期体系** — platform/industry/tenant 三层分级，register → initialize → shutdown
2. **CRM 业务模拟** — 完整的内存数据库 + CRUD + 聚合 + 5 个业务工具 + 6 个业务技能
3. **Tool 元数据模型** — aliases/search_hint/should_defer/max_result_size_chars/summary_threshold/code_extractable
4. **维度化记忆** — 4 维度检索（user_profile/customer_context/task_history/domain_knowledge）
5. **allowed_tools 技能约束** — 技能级工具白名单
6. **SubagentConfig 独立配置** — 每个子 Agent 可配置独立的 middleware/tools/skills
7. **MockLLMClient** — 可编程测试（预设工具调用响应脚本）
8. **ServiceBackend 协议** — 微服务调用抽象层

### Hermes Agent 独有
1. **自动技能生成** — 任务完成后自动创建 SKILL.md（核心卖点）
2. **技能自改进** — 使用中自动优化技能
3. **Skills Hub** — 技能市场（浏览/安装/118 个内置技能）
4. **三层记忆** — Session + FTS5 持久化 + 自动 User Model
5. **多模型路由** — 辅助 LLM 按任务类型选模型
6. **6 平台消息网关** — Telegram/Discord/Slack/WhatsApp/Signal/CLI
7. **内置 cron 调度** — 自然语言定时任务
8. **40+ 内置工具** — 终端/文件/Web/浏览器/代码执行/MCP
9. **agentskills.io 开放标准** — 技能互操作
10. **RL 训练集成** — Atropos 环境 + 轨迹压缩

### Claude Code 独有
1. **三层上下文压缩** — MicroCompact(0 API) + AutoCompact(13K buffer) + FullCompact(重置 50K)
2. **压缩熔断** — 3 次失败后停止
3. **Coordinator/Worker Mailbox** — 危险操作审批 + 原子 claim
4. **17 个 Hooks 生命周期事件** — 工具调用前后、Agent 启停等
5. **Prompt 缓存** — Anthropic 原生缓存
6. **遥测指标** — 挫败感指标（swearing frequency）+ continue 计数
7. **108 个 Feature Flags** — 编译时死代码消除
8. **46K 行 QueryEngine** — 自愈查询循环 + 流式 + 重试
9. **每工具独立权限级别** — BashTool vs FileReadTool 不同权限
10. **压缩后文件重注入** — 最近访问文件 ≤5K tokens/file

---

## 九、DeepAgent 应吸收的精华（按优先级）

### P0 — 必须吸收

| # | 来源 | 能力 | 理由 |
|---|------|------|------|
| 1 | Claude Code | **三层压缩** — 增加 MicroCompact（本地裁剪旧工具输出，0 API 调用） | 当前只有 1 层，长 session 会崩 |
| 2 | Claude Code | **压缩熔断** — 连续 N 次压缩失败后停止 | 防止无限压缩循环 |
| 3 | Hermes | **MCP 集成** — 连接外部 MCP 服务器扩展工具 | 生态互操作必备 |
| 4 | Hermes | **ToolLoader 目录自动发现** — 扫描 tools/ 目录加载 BaseTool 子类 | 当前缺失，v2 已有 |

### P1 — 重要优化

| # | 来源 | 能力 | 理由 |
|---|------|------|------|
| 5 | Claude Code | **Prompt 缓存** — 缓存不变的 system prompt 部分 | 降低 token 成本 |
| 6 | Hermes | **多模型路由** — 辅助 LLM 按任务类型选模型 | 成本优化 40-60% |
| 7 | Hermes | **FTS5 全文搜索** — 替代 NoopEngine 的持久化记忆 | 记忆系统从占位到可用 |
| 8 | Claude Code | **压缩后文件重注入** — Full Compact 后重注入最近访问文件 | 保持上下文连贯性 |
| 9 | Hermes | **自动技能生成** — 任务完成后自动创建 SKILL.md | 自改进能力 |

### P2 — 锦上添花

| # | 来源 | 能力 | 理由 |
|---|------|------|------|
| 10 | Claude Code | **Coordinator/Worker Mailbox** — 危险操作审批 | 多 Agent 安全 |
| 11 | Claude Code | **遥测指标** — 挫败感 + continue 计数 | 产品质量监控 |
| 12 | Hermes | **技能自改进** — 使用中优化技能 | 长期价值 |
| 13 | Hermes | **cron 调度** — 自然语言定时任务 | 自动化场景 |
| 14 | Claude Code | **Hooks 系统** — 生命周期事件钩子 | 可扩展性 |
