# neo_agent_v2 (design.md) vs DeepAgent 差异分析与待办

## 一、差异对比：谁的方案更优

### 1.1 DeepAgent 多出的能力（建议保留）

| 能力 | DeepAgent 实现 | design.md 是否有 | 评估 |
|------|---------------|-----------------|------|
| **TenantMiddleware** | 自动注入 tenant_id 到工具参数，记忆路径隔离 | 无 | **保留**。2B SaaS 必须有租户隔离，design.md 面向通用场景没考虑 |
| **ContextMiddleware Layer 1** | 工具结果 >500 字符时代码提取摘要 + 虚拟文件保留原文 | 无（只有 Summarization） | **保留**。比 design.md 的 Summarization 更细粒度，在工具返回时就压缩，而不是等到 before_model |
| **ContextMiddleware Layer 2** | MD5 去重（重复 ToolMessage 替换） | 无 | **保留**。design.md 的 LoopDetection 只检测重复 tool_calls，不检测重复 tool_results |
| **HITLMiddleware** | is_destructive 检查 + 自定义规则 + resume 恢复 | ClarificationMiddleware（只处理 ask_clarification） | **保留并增强**。我们的 HITL 覆盖面更广（破坏性操作 + 自定义规则），design.md 的 Clarification 只处理一种工具 |
| **SkillMiddleware** | 从 memory 召回 Skill 历史使用经验注入上下文 | 无独立中间件 | **保留**。design.md 的 Skill 经验在 SkillExecutor 内部，我们抽成独立中间件更灵活 |
| **ReflectionNode** | 4 种反思策略（stuck/retry/replan/escalate） | 无 | **保留**。design.md 没有反思机制，LoopDetection 只是简单的循环检测 |
| **PlanningNode** | 复杂任务自动分解为多步计划 | TodoMiddleware（注入 TODO 列表） | **保留**。我们的 PlanningNode 是主动规划，design.md 的 Todo 是被动注入 |
| **before_tool_call / after_tool_call** | 独立的工具调用前后钩子 | 无（只有 wrap_tool_call） | **保留**。比 design.md 更细粒度，before_tool_call 可以修改参数，after_tool_call 可以修改结果 |
| **Plugin 生命周期** | PluginRegistry + initialize/shutdown/health_check | 无 | **保留**。design.md 没有 Plugin 体系 |
| **CRM 业务工具** | 5 个真实 CRUD 工具 + CrmSimulatedBackend | 无（通用框架） | **保留**。这是我们的业务层 |

### 1.2 design.md 多出的能力（需要补齐）

| 能力 | design.md 设计 | DeepAgent 现状 | 优先级 | 补齐方案 |
|------|---------------|---------------|--------|---------|
| **DanglingToolCallMiddleware** | 修复上一轮悬挂的 tool_calls（补充 error ToolMessage） | 无 | P1 | 新增中间件，在 before_step 中扫描 messages 补充缺失的 ToolMessage |
| **ClarificationMiddleware** | 拦截 ask_clarification 工具，格式化后中断执行 | 无（我们的 ask_user 工具直接返回模拟回答） | P2 | 增强 ask_user 工具，支持 interrupt 模式 |
| **OutputRenderMiddleware** | 将输出映射到 UI 组件（TableRenderer/ReportRenderer） | 无 | P2 | 新增中间件，在 after_step 中检测输出格式 |
| **TitleMiddleware** | 首轮对话自动生成标题 | 无 | P3 | 简单实现：取第一条 HumanMessage 前 50 字符 |
| **InputTransformMiddleware** | 输入预处理（多模态转换） | 无 | P3 | 预留骨架 |
| **SubagentLimitMiddleware** | 限制单轮子 Agent 并发数 | 无（通过 max_llm_calls 间接限制） | P2 | 新增中间件，在 after_model 中检查 skills_tool 调用数量 |
| **SubagentCache** | 子 Agent 实例缓存（LRU + TTL） | 无（每次创建新实例） | P2 | 在 SkillExecutor 中加缓存 |
| **SubagentExecutor 双线程池** | IO Pool + CPU Pool 分离 | 无（直接 async） | P3 | 当前 async 方案在 Python 中已经足够 |
| **YAML 配置文件** | AppConfig Pydantic + YAML/JSON + 环境变量覆盖 | AgentConfig dataclass + 代码传参 | P2 | 新增 YAML 加载器 |
| **SSE 流式输出** | astream_events → SSE 事件流（token/tool_call/done） | yield state | P1 | 新增 stream_agent_response() 适配器 |
| **NeoAgentV2Adapter** | 单例适配器层，懒加载 Agent | 无 | P1 | 新增适配器 |
| **异常层次结构** | HarnessError + 9 个子类 | SkillExecutionError + SkillValidationError | P2 | 扩展异常体系 |
| **OutputValidation 增强** | 检查实体缺失 + 工具使用不足 | 只检查长度 | P2 | 增强检查规则 |

### 1.3 实现方案不同的（需要决策）

| 能力 | design.md | DeepAgent | 决策建议 |
|------|-----------|-----------|---------|
| **编排引擎** | LangChain `create_agent` | 自研 `GraphEngine` | **迁移到 LangChain**。理由：跟随 LangChain 升级、社区生态、减少维护成本 |
| **状态类型** | `ThreadState(MessagesState)` | `GraphState` dataclass | **迁移后自然对齐**。LangGraph 的 MessagesState 提供 messages reducer |
| **工具错误处理** | 独立 `ToolErrorHandlingMiddleware` | ExecutionNode 内嵌 try/except | **抽成独立中间件**。更符合中间件架构 |
| **fork 执行** | `SubagentExecutor` 线程池 | 直接 async 创建子 engine | **保持 async**。Python async 已经足够，线程池增加复杂度 |
| **TODO 管理** | `TodoMiddleware` 注入 TODO 列表 | `PlanningNode` 主动规划 | **保留 PlanningNode**。主动规划比被动注入更强 |

---

## 二、双方都没实现的功能

以下功能在 design.md 中有描述但标注为"预留骨架"或"空实现"，我们也没有实现：

| 功能 | design.md 状态 | 说明 | 优先级 |
|------|---------------|------|--------|
| **多模态输入** | InputTransformMiddleware 中 MultimodalTransformer 为空骨架 | 图片/音频/视频输入处理 | P3 |
| **UI 组件渲染** | OutputRenderMiddleware 中所有 Renderer 的 can_render() 返回 False | TableRenderer/ReportRenderer/DashboardRenderer | P2 |
| **沙箱代码执行** | Features.sandbox_enabled 开关存在，但无实现 | 安全的代码执行环境 | P3 |
| **MCP 工具集成** | Features.mcp_enabled 开关存在，配置结构定义了 | Model Context Protocol 外部工具 | P2 |
| **向量存储记忆** | MemorySettings.vector_store 配置存在，MemoryEngine 为 NoopMemoryEngine | 基于向量检索的长期记忆 | P1 |
| **记忆查询重写** | MemoryMiddleware 中 rewrite_query() 提到但未实现 | 多轮对话时重写查询以提高召回率 | P2 |
| **Artifact 管理** | ThreadState.artifacts 字段 + artifacts_reducer 定义了 | Agent 生成的代码/文档制品管理 | P3 |
| **计划模式** | TodoMiddleware 中 is_plan_mode 检查 | 用户显式进入计划模式，Agent 生成 TODO 列表 | P3 |
| **模型提供商切换** | AppConfig.model.providers 配置 | 运行时切换 LLM 提供商（OpenAI/Anthropic/DeepSeek） | P2 |
| **社区工具** | ToolSettings.community_tools 配置 | 加载社区贡献的工具包 | P3 |

---

## 三、GraphEngine → LangChain 迁移方案

### 3.1 迁移范围

需要替换的文件：
- `src/graph/engine.py` — GraphEngine → 用 `create_agent` 或 LangGraph StateGraph
- `src/graph/router.py` — Router → LangGraph 条件边
- `src/graph/state.py` — GraphState → 继承 MessagesState
- `src/graph/factory.py` — AgentFactory → 调用 create_agent
- `src/nodes/execution.py` — ExecutionNode → LangGraph 内置 ToolNode + 中间件
- `src/nodes/planning.py` — PlanningNode → LangGraph 节点
- `src/nodes/reflection.py` — ReflectionNode → LangGraph 节点

不需要改的文件：
- `src/skills.py` — Skill 体系独立于编排引擎
- `src/tools.py` — Tool 基类需要适配为 BaseTool
- `src/middleware/*.py` — 中间件需要适配为 AgentMiddleware
- `src/crm_*.py` — 业务层不变
- `src/plugin.py` — Plugin 体系独立

### 3.2 迁移风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| LangChain API 不稳定 | create_agent 是新 API，可能变更 | 锁定版本，封装适配层 |
| 中间件接口不兼容 | AgentMiddleware 的钩子签名与我们不同 | 写适配器包装现有中间件 |
| 状态模型差异 | MessagesState 的 messages 是 LangChain Message 类型 | 需要转换层 |
| 测试全部重写 | 26 个测试依赖 GraphEngine | 分阶段迁移，保持旧测试可运行 |

### 3.3 建议方案

**不建议一次性迁移**。建议分两步：

**Phase 1（短期）：** 保持自研 GraphEngine，但让 Tool 和 Middleware 的接口与 LangChain 对齐
- Tool 基类增加 `_arun()` / `_run()` 方法（兼容 BaseTool）
- Middleware 增加 `awrap_tool_call` 方法（兼容 AgentMiddleware）
- 状态模型增加 messages reducer（兼容 MessagesState）

**Phase 2（中期）：** 引入 LangGraph 作为编排引擎
- 用 LangGraph StateGraph 替换 GraphEngine
- PlanningNode / ExecutionNode / ReflectionNode 转为 LangGraph 节点
- Router 转为 LangGraph 条件边
- 中间件通过 AgentMiddleware 适配器接入

---

## 四、优先级排序

### P0（必须做，阻塞上线）
- [ ] SSE 流式输出 + NeoAgentV2Adapter 适配器
- [ ] DanglingToolCallMiddleware（修复悬挂 tool_calls）

### P1（应该做，影响体验）
- [ ] 向量存储记忆（替换内存 MemoryPlugin）
- [ ] Tool 接口对齐 LangChain BaseTool
- [ ] Middleware 接口对齐 LangChain AgentMiddleware
- [ ] ToolErrorHandlingMiddleware（从 ExecutionNode 抽出）

### P2（可以做，提升质量）
- [ ] SubagentCache（LRU + TTL）
- [ ] SubagentLimitMiddleware
- [ ] ClarificationMiddleware（增强 ask_user）
- [ ] OutputRenderMiddleware（UI 组件映射）
- [ ] OutputValidation 增强（实体+工具使用检查）
- [ ] YAML 配置文件加载
- [ ] 异常层次结构扩展
- [ ] MCP 工具集成
- [ ] 记忆查询重写
- [ ] 模型提供商切换

### P3（锦上添花）
- [ ] TitleMiddleware
- [ ] InputTransformMiddleware
- [ ] 多模态输入
- [ ] 沙箱代码执行
- [ ] Artifact 管理
- [ ] 计划模式
- [ ] 社区工具
- [ ] GraphEngine → LangGraph 迁移（Phase 2）
