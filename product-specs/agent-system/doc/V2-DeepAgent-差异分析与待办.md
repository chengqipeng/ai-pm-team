# neo_agent_v2 vs DeepAgent — 代码级差异分析（最新）

> 基于 neo_agent_v2 最新代码与 DeepAgent 当前代码的逐模块对比

---

## 一、模块对照表

| neo_agent_v2 模块 | DeepAgent 对应 | 状态 | 差异说明 |
|---|---|---|---|
| `agents/lead_agent/agent.py` — `create_lead_agent()` | `langchain_agent.py` — `create_deep_agent()` | ✅ 已对齐 | 都调 `create_agent(model, tools, system_prompt, middleware, checkpointer)` |
| `agents/lead_agent/prompt.py` — `build_system_prompt()` | `prompt_builder.py` — `build_system_prompt()` | ✅ 已对齐 | DeepAgent 版本结构一致，支持技能段落 + 记忆上下文 |
| `agents/factory.py` — `make_lead_agent_with_model()` | `langchain_agent.py` — `create_deep_agent()` | ✅ 已对齐 | v2 的 factory.py 是旧入口，agent_factory.py 是新入口 |
| `agents/agent_factory.py` — `AgentFactory` | `agent_factory.py` — `AgentFactory` | ✅ 已对齐 | 都有 LRU 缓存 + max_depth 限制 |
| `agents/agent_config.py` — `AgentConfig` | 无独立文件 | ⚠️ 差异 | DeepAgent 用 `LangChainAgentConfig` dataclass，缺 YAML 定义支持 |
| `agents/agent_loader.py` — `AgentLoader` | 无 | ❌ 缺失 | 从 definitions/ 目录自动发现 agent.yaml |
| `agents/agent_registry.py` — `AgentRegistry` | 无 | ❌ 缺失 | 全局 Agent 配置注册表 |
| `agents/features.py` — `Features` | 无 | ❌ 缺失 | 特性开关（sandbox/memory/subagent/guardrail/mcp） |
| `agents/thread_state.py` — `ThreadState` | `state.py` — `GraphState` | ⚠️ 差异 | v2 用 LangGraph `MessagesState` + Artifact/ImageData；DeepAgent 用自定义 dataclass |
| `agents/streaming.py` — `SSEEvent` | `streaming.py` — `SSEEvent` | ✅ 已对齐 | 代码几乎一致 |
| `agents/checkpointer/provider.py` | `checkpointer.py` | ✅ 已对齐 | 都支持 SQLite，v2 额外有 Redis async |
| **中间件（14 vs 13）** | | | |
| `middlewares/agent_logging.py` | `middleware/agent_logging.py` | ✅ 已对齐 | v2 更详细（emoji 清理、GBK 兼容），DeepAgent 精简版 |
| `middlewares/clarification.py` | `middleware/clarification.py` | ✅ 已对齐 | 逻辑一致 |
| `middlewares/dangling_tool_call.py` | `middleware/dangling_tool_call.py` | ✅ 已对齐 | 代码一致 |
| `middlewares/guardrail.py` | `middleware/guardrail.py` | ✅ 已对齐 | 代码一致 |
| `middlewares/input_transform.py` | `middleware/input_transform.py` | ✅ 已对齐 | 骨架一致 |
| `middlewares/loop_detection.py` | `middleware/loop_detection.py` | ✅ 已对齐 | 逻辑一致 |
| `middlewares/memory.py` | `middleware/memory.py` | ✅ 已对齐 | 都有 MemoryEngine 协议 + NoopEngine |
| `middlewares/output_render.py` | 无 | ❌ 缺失 | UI 组件渲染钩子（Table/Report/Dashboard） |
| `middlewares/output_validation.py` | `middleware/output_validation.py` | ✅ 已对齐 | v2 更复杂（实体提取 + Skill 引用检查），DeepAgent 精简版 |
| `middlewares/reflection.py` | 无 | ⏭️ 空文件 | v2 也是空文件，暂不需要 |
| `middlewares/subagent_limit.py` | `middleware/subagent_limit.py` | ✅ 已对齐 | 逻辑一致 |
| `middlewares/summarization.py` | `middleware/summarization.py` | ✅ 已对齐 | 逻辑一致 |
| `middlewares/title.py` | `middleware/title.py` | ✅ 已对齐 | 逻辑一致 |
| `middlewares/todo.py` | `middleware/todo.py` | ✅ 已对齐 | 逻辑一致 |
| `middlewares/tool_error_handling.py` | `middleware/tool_error_handling.py` | ✅ 已对齐 | 代码一致 |
| **工具系统** | | | |
| `tools/skills_tool.py` — Pydantic `BaseTool` | `skills_tool.py` — Pydantic `BaseTool` | ✅ 已对齐 | 都用 `args_schema = SkillsToolInput` |
| `tools/agent_tool.py` — Pydantic `BaseTool` | `agent_tool.py` — Pydantic `BaseTool` | ✅ 已对齐 | 都用 `args_schema = AgentToolInput` |
| `tools/loader.py` — `ToolLoader` | 无独立文件 | ❌ 缺失 | 按名注册 + load_tools_by_names + 自动发现 |
| **技能系统** | | | |
| `skills/types.py` — `Skill` dataclass | `skills.py` — `SkillDefinition` dataclass | ✅ 已对齐 | 字段一致 |
| `skills/parser.py` — `SkillParser` | `skills.py` — `SkillLoader.parse()` | ✅ 已对齐 | v2 拆分更细，功能等价 |
| `skills/loader.py` — `SkillLoader` | `skills.py` — `SkillLoader` | ✅ 已对齐 | 功能等价 |
| `skills/registry.py` — `SkillRegistry` | `skills.py` — `SkillRegistry` | ✅ 已对齐 | v2 多了 `__len__`/`__contains__` |
| `skills/executor.py` — `SkillExecutor` | `skills.py` — `SkillExecutor` | ⚠️ 差异 | v2 的 fork 用 `AgentFactory.build()`；DeepAgent 仍用 `create_deep_agent()` |
| `skills/validation.py` | `skills.py` — `SkillLoader.validate()` | ✅ 已对齐 | v2 拆分独立文件 |
| `skills/installer.py` | 无 | ⏭️ 占位 | v2 也是 `raise NotImplementedError` |
| **子 Agent 系统** | | | |
| `subagents/config.py` — `SubagentConfig` | `subagent_config.py` — `SubagentConfig` | ⚠️ 差异 | v2 多了 `inherit_middleware`/`middleware_config` 字段 |
| `subagents/factory.py` — `SubagentFactory` | 无 | ❌ 缺失 | 独立的子 Agent 工厂（与 AgentFactory 分离） |
| `subagents/registry.py` — `SubagentRegistry` | `subagent_config.py` — `SubagentRegistry` | ⚠️ 差异 | v2 多了 `register_config()`/`get_config()` |
| `subagents/executor.py` — `SubagentExecutor` | 无 | ❌ 缺失 | 双线程池（IO/CPU）异步执行 |
| `subagents/builtins/` | 无 | ❌ 缺失 | bash_agent + general_purpose（桩实现） |
| **记忆系统** | | | |
| `memory/storage.py` — `MemoryStorage` | 无 | ❌ 缺失 | 原子文件 I/O（写临时文件 → os.rename） |
| `memory/embedding.py` — `EmbeddingClient` | 无 | ❌ 缺失 | text-embedding-3-small 向量化 |
| `memory/vector_store.py` — `ChromaVectorStore` | 无 | ❌ 缺失 | ChromaDB 向量检索 |
| `memory/prompt.py` — `MemoryChunk` + `build_memory_prompt()` | 无 | ❌ 缺失 | 短期 + 长期记忆提示词构建 |
| `memory/queue.py` — `DebounceQueue` | 无 | ❌ 缺失 | 防抖合并记忆更新请求 |
| `memory/updater.py` — `MemoryUpdater` | 无 | ❌ 缺失 | LLM 提取关键信息更新记忆 |
| **配置系统** | | | |
| `config/loader.py` — `ConfigLoader` | 无 | ❌ 缺失 | YAML/JSON + 环境变量覆盖 |
| `config/models.py` — `AppConfig` Pydantic | 无 | ❌ 缺失 | 类型化配置模型 |
| **上传管理** | | | |
| `uploads/manager.py` — `UploadManager` | 无 | ❌ 缺失 | 文件存储 + 文档转 Markdown |
| **异常体系** | | | |
| `exceptions.py` — 8 个异常类 | `exceptions.py` — 6 个异常类 | ⚠️ 差异 | DeepAgent 缺 `SandboxError`/`MCPConnectionError`/`VectorStoreError` |
| **适配器** | | | |
| `adapter.py` — `NeoAgentV2Adapter` | `adapter.py` — `NeoAgentV2Adapter` | ⚠️ 差异 | v2 多了 `execute_agui()` AG-UI 管道 |

---

## 二、剩余差距汇总

### 已完成对齐（上一轮实现）
- ✅ 13 个中间件（vs v2 的 14 个，仅缺 OutputRender 骨架）
- ✅ SkillsTool / AgentTool — Pydantic BaseTool
- ✅ AgentFactory — LRU 缓存 + 深度限制
- ✅ 统一异常体系
- ✅ PromptBuilder 结构化提示词

### 仍需实现

| 优先级 | 模块 | 说明 | 工作量 |
|--------|------|------|--------|
| P1 | `SkillExecutor.fork` 改用 `AgentFactory` | 当前仍每次 `create_deep_agent`，无缓存 | 1h |
| P1 | `ToolLoader` | 按名注册 + `load_tools_by_names` + 目录自动发现 | 1h |
| P1 | `SubagentConfig` 补齐字段 | 加 `inherit_middleware`/`middleware_config`/`middleware_names` | 0.5h |
| P1 | `Features` 特性开关 | 控制中间件加载 | 0.5h |
| P2 | `AgentLoader` + `AgentRegistry` | YAML 定义自动发现 | 2h |
| P2 | `OutputRenderMiddleware` | UI 组件渲染骨架 | 0.5h |
| P2 | `memory/` 完整体系 | Storage + Embedding + VectorStore + Queue + Updater + Prompt | 4h |
| P2 | `config/` 配置体系 | ConfigLoader + AppConfig Pydantic | 2h |
| P2 | `uploads/` 上传管理 | UploadManager + 文档转 Markdown | 1h |
| P2 | `ThreadState` 替换 `GraphState` | MessagesState + Artifact + ImageData | 2h |
| P2 | `SubagentFactory` + `SubagentExecutor` | 独立子 Agent 工厂 + 双线程池 | 2h |
| P2 | `adapter.py` 补 AG-UI | `execute_agui()` 方法 | 1h |
| P3 | 异常补齐 | SandboxError/MCPConnectionError/VectorStoreError | 0.5h |

### DeepAgent 独有（需保留）
- `plugin.py` — Plugin 生命周期（v2 无此体系）
- `crm_backend.py` + `crm_tools.py` + `crm_skills.py` — CRM 业务模拟
- `tools.py` — Tool 高级特性（aliases/search_hint/should_defer/max_result_size_chars）
- `llm_client.py` — MockLLMClient 可编程测试
- `service_backend.py` — 微服务调用抽象
- `async_agent.py` — fire-and-forget 异步任务
