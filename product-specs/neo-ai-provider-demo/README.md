# neo-ai-provider-demo

业务域服务（Provider）Demo — 演示如何使用 Registry 手动内置 Tool / Middleware 定义并暴露 HTTP API。

## 职责

- 使用 `Registry` 手动注册 Tool 和 Middleware 定义
- 暴露 Provider HTTP API 供 Agent 运行时通过 FeignClient 调用
- 实现 Tool 执行回调逻辑（业务域具体实现）

## 运行

```bash
pip install -e ../neo-ai-registry-sdk
uvicorn app.main:app --reload --port 8002
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/registry/tools` | 列出所有 Tool 定义 |
| GET | `/v1/registry/tools/{api_key}` | 获取单个 Tool 定义 |
| POST | `/v1/tools/{api_key}/execute` | 执行 Tool（回调） |
| GET | `/v1/registry/middlewares` | 列出所有 Middleware 定义 |
