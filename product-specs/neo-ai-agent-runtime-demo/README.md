# neo-ai-agent-runtime-demo

Agent 运行时调用端 Demo — 演示如何通过 FeignClient 远程加载 Tool / Middleware 并组装 Agent。

## 职责

- 通过 `ToolFeignClient` 远程获取各业务域服务注册的 Tool 定义
- 通过 `MiddlewareFeignClient` 远程获取 Middleware 定义
- 根据 `agent.yaml` 元数据配置组装 Agent 能力
- 执行远程 Tool 时通过 FeignClient 回调业务域服务

## 运行

```bash
pip install -e ../neo-ai-registry-sdk
uvicorn app.main:app --reload --port 8001
```
