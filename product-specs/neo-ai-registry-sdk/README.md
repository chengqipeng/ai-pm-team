# neo-ai-registry-sdk

Agent 切面注册器 SDK — Tool / Middleware 定义与加载的统一 Python 包。

## 设计模式

```
┌──────────────────────────────────────────────────────────────────────┐
│  业务域微服务（neo-ai-provider-demo）                                 │
│                                                                      │
│  registry = Registry(domain="sales")                                 │
│  registry.register_tool(ToolDefinition(...))    ← 手动内置数据        │
│  registry.register_middleware(MiddlewareDefinition(...))              │
│                                                                      │
│  # 暴露 HTTP API（实现 Provider 接口）                                │
│  GET  /v1/registry/tools          → registry.list_tools()            │
│  POST /v1/tools/{key}/execute     → handler(input_data)              │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ HTTP（FeignClient 模式）
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Agent 运行时（neo-ai-agent-runtime-demo）                            │
│                                                                      │
│  tool_client = ToolFeignClient(base_url="http://provider:8002")      │
│  tools = tool_client.list_tools()           ← 远程获取 Tool 定义      │
│  result = tool_client.execute_tool(...)     ← 远程执行 Tool           │
└──────────────────────────────────────────────────────────────────────┘
```

## 模块结构

```
neo_ai_registry/
├── __init__.py            # 包入口
├── models.py              # 数据模型：ToolDefinition + MiddlewareDefinition + McpServerDefinition
├── registry.py            # 内存注册表（业务域服务使用）
├── validator.py           # Schema 校验
├── providers/
│   └── base.py            # 抽象接口：ToolProvider + MiddlewareProvider
└── feign/
    └── client.py           # FeignClient：ToolFeignClient + MiddlewareFeignClient
```

## 三个项目关系

```
product-specs/
├── agent-system/              # Agent 核心框架源码
├── neo-ai-registry-sdk/       # SDK 包（本项目）
├── neo-ai-agent-runtime-demo/ # Agent 运行时调用端 Demo
└── neo-ai-provider-demo/      # 业务域服务提供方 Demo
```

## 快速验证

```bash
# 1. 安装 SDK
cd neo-ai-registry-sdk && pip install -e .

# 2. 启动业务域服务（Provider）
cd ../neo-ai-provider-demo && pip install -e . && uvicorn app.main:app --port 8002

# 3. 启动 Agent 运行时
cd ../neo-ai-agent-runtime-demo && pip install -e . && uvicorn app.main:app --port 8001

# 4. 验证
curl http://localhost:8001/v1/agent/tools      # Agent 端查看已加载的 Tool
curl http://localhost:8002/v1/registry/tools   # Provider 端查看注册的 Tool
curl -X POST http://localhost:8001/v1/agent/execute \
  -H "Content-Type: application/json" \
  -d '{"tool_name": "query_customer", "input": {"customer_name": "仁科"}}'
```
