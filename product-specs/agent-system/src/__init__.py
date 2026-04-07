"""
Agent + Skills + Tools 框架
基于 my-claude-code 源码分析的 Python 完整实现

模块清单:
  types.py        — 核心类型定义 (Message, Permission, ToolResult)
  state.py        — 状态管理 (AppStateStore, 不可变更新+订阅)
  context.py      — 上下文管理 (五层架构, 六策略压缩, CLAUDE.md)
  tools.py        — 工具体系 (统一接口, 注册表, 权限检查, 并行执行)
  builtin_tools.py — 内置工具 (FileRead/Write/Edit, Bash, Grep, Glob)
  skills.py       — 技能体系 (多源加载, Frontmatter解析, 内置技能)
  hooks.py        — Hooks系统 (pre/post tool use, session hooks)
  session.py      — 会话持久化 (transcript, resume, 文件快照)
  coordinator.py  — Coordinator模式 (星型编排, Worker管理, XML通信)
  llm_client.py   — LLM客户端 (Anthropic API, Mock客户端)
  plugins.py      — 插件系统 (注册, 加载, 组件分发)
  mcp.py          — MCP集成 (服务器连接, 工具代理, 资源管理)
  agent.py        — Agent核心 (Loop Engine, 子Agent, 反思, SkillTool, AgentTool)
  engine.py       — 顶层编排 (QueryEngine, 全系统组装)
"""
