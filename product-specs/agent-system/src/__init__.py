"""
DeepAgent — 面向 2B CRM SaaS 的 Agent 系统

模块结构:
  dtypes.py         — 核心类型定义 (Message, ToolResult, LLMClient)
  tools.py          — Tool 统一接口 + ToolRegistry
  llm_client.py     — LLM 客户端 (DeepSeek API, Mock 客户端)
  service_backend.py — 服务调用抽象层 (Mock/Direct/Gateway)
  async_agent.py    — 异步子 Agent 管理

  graph/            — 图状态机编排引擎
    state.py        — GraphState, AgentStatus, TaskPlan, AgentLimits
    router.py       — Router 路由决策 (7 级优先级)
    engine.py       — GraphEngine 主循环 + CheckpointStore
    factory.py      — AgentFactory 初始化 + AgentConfig

  nodes/            — 三个核心 Node
    planning.py     — PlanningNode (任务规划)
    execution.py    — ExecutionNode (步骤执行, mini agent loop)
    reflection.py   — ReflectionNode (反思决策, 4 种策略)

  middleware/        — 中间件栈 (洋葱模型)
    base.py         — Middleware Protocol + PluginContext
    tenant.py       — TenantMiddleware (租户隔离)
    audit.py        — AuditMiddleware (审计日志)
    context.py      — ContextMiddleware (上下文压缩)
    skill.py        — SkillMiddleware (技能经验注入)
    hitl.py         — HITLMiddleware (人工审批)
"""
