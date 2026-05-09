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

## 元模型 / 元数据 / 业务数据 浏览

前端页面：`http://localhost:8001/metamodel`
REST 接口前缀：`/api/meta/*`

三层浏览（对齐 paas-platform-service 的 MetamodelBrowseApiService + EntityDataApiService）：

| 左侧 Tab | REST 列表 | 后端来源 |
|:---|:---|:---|
| 元模型     | `/api/meta/metamodels`       | `p_meta_model` |
| 业务对象   | `/api/meta/metadata/entities`| `entity` 元数据实例 |
| 业务数据   | `/api/meta/data/entities`    | `p_tenant_data_*` 分片 |

### 切换数据源

**默认（零依赖）**：内存模拟数据（`MetarepoSimulatedBackend` + `CrmSimulatedBackend`）

**对接真实 paas-platform-service**：

```bash
# Feign 风格：指向 paas-platform-service（同时生效于 REST API、前端页面、Agent 工具）
export METAREPO_API_BASE=http://paas-platform-service:8080

# 租户 ID：不配置时默认使用 src.core.context.DEFAULT_TENANT_ID（= 1）
# agent-system 内部 RequestContext / TraceWriter / ai_* 表 / X-Tenant-Id header 全部共用同一个值
# export DEFAULT_TENANT_ID=1                      # 全局默认（不改也行）
# export METAREPO_TENANT_ID=1                     # 仅覆盖 X-Tenant-Id header

# export METAREPO_USER_ID=1001                    # 可选：X-User-Id
# export METAREPO_TOKEN=eyJhbGc...                # 可选：Authorization: Bearer

# 业务数据可单独指向另一个服务（不配置则沿用 METAREPO_API_BASE）
# export ENTITY_DATA_API_BASE=http://paas-platform-service:8080

poetry run uvicorn server:app --port 8001
```

前端右上角徽章会显示当前数据源 + 租户 ID（`● paas-platform-service · 租户 1`）。

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
