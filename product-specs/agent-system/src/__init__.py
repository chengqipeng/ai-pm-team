"""
DeepAgent — 面向 2B CRM SaaS 的 Agent 系统

模块结构:
  core/       — 基础类型、异常、状态、LLM、流式、检查点、提示词、模型路由
  agents/     — Agent 工厂、配置、加载、适配器、子 Agent
  tools/      — Tool 基类、ToolRegistry、ToolLoader、AgentTool、CRM 工具
  skills/     — Skill 定义、注册、执行、加载、生成、CRM 技能
  middleware/ — 14 个中间件（继承 LangChain AgentMiddleware）
  memory/     — FTS5 存储、FTSEngine、防抖队列、记忆更新、提示词
  plugins/    — Plugin 生命周期管理
"""
