# DeepAgent

面向 2B CRM SaaS 的 Agent 系统 — 图状态机编排引擎。

## 快速开始

```bash
# 安装依赖
poetry install

# 运行 demo（无需 API Key）
poetry run python demo.py

# 运行测试
poetry run pytest

# 使用真实 DeepSeek API
export DEEPSEEK_API_KEY=sk-...
poetry run python example.py
```

## 架构

```
GraphEngine (主循环)
  ├── Router (路由决策, 7 级优先级)
  ├── PlanningNode (任务规划)
  ├── ExecutionNode (步骤执行, mini agent loop)
  ├── ReflectionNode (反思决策, 4 种策略)
  └── Middleware Stack (洋葱模型)
       ├── TenantMiddleware (租户隔离)
       ├── AuditMiddleware (审计日志)
       ├── ContextMiddleware (上下文压缩)
       ├── SkillMiddleware (技能经验注入)
       └── HITLMiddleware (人工审批)
```
