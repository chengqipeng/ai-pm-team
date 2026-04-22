"""
DeepAgent — 面向 2B CRM SaaS 的 Agent 系统
基于 LangChain create_agent 构建

模块结构:
  dtypes.py           — 核心类型 (Message, ToolResult, LLMClient)
  state.py            — 状态模型 (GraphState, AgentStatus, AgentCallbacks)
  tools.py            — Tool 统一接口 + ToolRegistry
  skills.py           — Skill 体系 (SkillDefinition/Registry/Executor/SkillsTool/Loader)
  subagent_config.py  — 子 Agent 配置 (SubagentConfig, SubagentRegistry)
  langchain_agent.py  — LangChain 集成 (create_deep_agent, ToolAdapter, MiddlewareAdapter)
  llm_client.py       — LLM 客户端 (DeepSeek API, Mock)
  plugin.py           — Plugin 生命周期 (PluginRegistry, MemoryPlugin, NotificationPlugin)
  crm_backend.py      — CRM 模拟后端 (内存数据库 + CRUD + 聚合)
  crm_tools.py        — CRM 业务工具 (query_schema/query_data/modify_data/analyze_data/ask_user)
  crm_skills.py       — CRM 业务技能 (verify_config/diagnose/customer_360/pipeline_analysis/...)
  service_backend.py  — 服务调用抽象层
  async_agent.py      — 异步子 Agent 管理

  middleware/          — 中间件栈 (适配 LangChain AgentMiddleware)
    base.py            — Middleware Protocol + PluginContext
    tenant.py          — TenantMiddleware (租户隔离)
    audit.py           — AuditMiddleware (审计日志)
    context.py         — ContextMiddleware (Layer 1/2 上下文压缩)
    memory.py          — MemoryMiddleware (画像注入 + 自动召回)
    skill.py           — SkillMiddleware (技能经验注入)
    hitl.py            — HITLMiddleware (人工审批)
    loop_detection.py  — LoopDetectionMiddleware (循环检测)
    summarization.py   — SummarizationMiddleware (消息压缩)
    output_validation.py — OutputValidationMiddleware (输出验证)
    guardrail.py       — GuardrailMiddleware (工具白名单)
"""
