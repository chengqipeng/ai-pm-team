"""安全护栏中间件 — 工具级权限管控

## 设计背景

CRM SaaS 是多租户系统，不同角色的用户对 Agent 的操作权限不同。
GuardrailMiddleware 在 wrap_tool_call 阶段拦截不允许的工具调用，
确保 Agent 不会越权执行操作。

## 管控维度

### 1. 工具白名单（allowed_tools）
限制 Agent 可以调用哪些工具。未在白名单中的工具调用直接返回错误。

### 2. 实体写入黑名单（readonly_entities）
限制 modify_data 工具不能操作哪些实体。用于保护核心业务对象。

### 3. 危险操作拦截（block_destructive）
禁止 modify_data 的 delete 操作，防止数据误删。

## 使用场景

### 场景 1：按角色配置工具权限
```python
# 普通销售 — 只能查询和分析，不能修改数据
GuardrailMiddleware(
    allowed_tools=["query_schema", "query_data", "analyze_data",
                    "ask_user", "ask_clarification"],
)

# 销售经理 — 可以修改数据，但不能删除
GuardrailMiddleware(
    allowed_tools=["query_schema", "query_data", "analyze_data",
                    "modify_data", "ask_user", "ask_clarification"],
    block_destructive=True,
)

# 管理员 — 全部权限
GuardrailMiddleware()  # 不传 allowed_tools = 全部放行
```

### 场景 2：保护核心实体不被 Agent 修改
```python
# 禁止 Agent 修改 account（客户）和 opportunity（商机）的数据
# 但允许修改 activity（活动）和 contact（联系人）
GuardrailMiddleware(
    readonly_entities=["account", "opportunity"],
)
```

### 场景 3：禁止子 Agent 委派（控制成本和复杂度）
```python
# 轻量模式 — 禁用 skills_tool 和 agent_tool
GuardrailMiddleware(
    allowed_tools=["query_schema", "query_data", "modify_data",
                    "analyze_data", "ask_user", "ask_clarification"],
)
```

### 场景 4：只读演示模式
```python
# Demo 环境 — 只允许查询，禁止一切写入
GuardrailMiddleware(
    allowed_tools=["query_schema", "query_data", "analyze_data",
                    "ask_user", "ask_clarification"],
)
```

### 场景 5：动态权限（从 configurable 读取）
```python
# 在 server.py 中根据用户角色动态设置
config = {
    "configurable": {
        "thread_id": thread_id,
        "user_id": user_id,
        "user_role": "sales",  # sales / manager / admin
    }
}
# GuardrailMiddleware 从 configurable["user_role"] 动态决定权限
```

## 在中间件管道中的位置

```
wrap_tool_call 洋葱模型（外→内）：
  TracingMiddleware          → 记录 tool span（最外层，记录完整耗时）
  AgentLoggingMiddleware     → 打印工具调用日志
  GuardrailMiddleware        → ★ 权限拦截（本中间件，拦截后不进入内层）
  ToolErrorHandlingMiddleware → 异常捕获
  ClarificationMiddleware    → 拦截 ask_clarification
                ↓
          实际工具执行
```

GuardrailMiddleware 排在 ToolErrorHandlingMiddleware 之前，
被拦截的工具调用不会触发异常处理逻辑，直接返回权限错误。
"""

import logging
from typing import Any

from langchain_core.messages import ToolMessage
from langchain.agents.middleware.types import AgentMiddleware
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

logger = logging.getLogger(__name__)


class GuardrailMiddleware(AgentMiddleware):
    """安全护栏 — 工具白名单 + 实体写入黑名单 + 危险操作拦截

    Args:
        allowed_tools: 允许调用的工具名列表。None 表示全部放行。
        readonly_entities: 禁止 modify_data 操作的实体列表。
        block_destructive: 是否禁止 modify_data 的 delete 操作。
    """

    def __init__(
        self,
        allowed_tools: list[str] | None = None,
        readonly_entities: list[str] | None = None,
        block_destructive: bool = False,
    ) -> None:
        super().__init__()
        self._allowed = set(allowed_tools) if allowed_tools else None
        self._readonly_entities = set(readonly_entities) if readonly_entities else set()
        self._block_destructive = block_destructive

    def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        blocked = self._check(request)
        if blocked:
            return blocked
        return handler(request)

    async def awrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command:
        blocked = self._check(request)
        if blocked:
            return blocked
        return await handler(request)

    def _check(self, request: ToolCallRequest) -> ToolMessage | None:
        """统一权限检查 — 返回 ToolMessage 表示拦截，None 表示放行"""
        tool_name = request.tool_call.get("name", "")
        tool_call_id = request.tool_call.get("id", "")
        args = request.tool_call.get("args", {})

        # 检查 1：工具白名单
        if self._allowed and tool_name not in self._allowed:
            logger.warning("Guardrail blocked tool: %s (not in allowed list)", tool_name)
            return self._blocked(tool_call_id, tool_name,
                                 f"Tool '{tool_name}' is not allowed by security policy.")

        # 检查 2 & 3 仅针对 modify_data
        if tool_name == "modify_data":
            action = args.get("action", "")
            entity = args.get("entity_api_key", "")

            # 检查 2：实体写入黑名单
            if entity and entity in self._readonly_entities:
                logger.warning("Guardrail blocked modify on readonly entity: %s.%s", entity, action)
                return self._blocked(tool_call_id, tool_name,
                                     f"Entity '{entity}' is read-only, modification is not allowed.")

            # 检查 3：危险操作拦截
            if self._block_destructive and action == "delete":
                logger.warning("Guardrail blocked destructive action: %s.delete", entity)
                return self._blocked(tool_call_id, tool_name,
                                     "Delete operations are blocked by security policy. "
                                     "Please contact an administrator.")

        return None

    @staticmethod
    def _blocked(tool_call_id: str, tool_name: str, reason: str) -> ToolMessage:
        return ToolMessage(
            content=f"Error: {reason}",
            tool_call_id=tool_call_id,
            name=tool_name,
            status="error",
        )
