"""SkillToolScopeMiddleware — Skill 级工具作用域隔离

## 设计背景

每个 Skill 通过 allowed_tools 字段声明它可以使用的工具集合。
本中间件在 wrap_tool_call 阶段检查当前工具调用是否在 Skill 的允许范围内，
实现运行时的严格作用域隔离，防止 Skill 越权调用未授权的工具。

## 管控逻辑

1. 读取 contextvars 中的 SkillContext（由 SkillExecutor 设置）
2. 如果没有 SkillContext（非 Skill 执行期间），放行
3. 如果 SkillContext.allowed_tools 为空集，放行（空 = 不限制，向后兼容）
4. 如果工具名在 allowed_tools 中，放行
5. 否则，拦截并返回权限错误

## 特殊工具豁免

以下工具始终放行，不受 Skill 作用域限制：
- skills_tool: Skill 可以调用其他 Skill（嵌套执行由深度限制控制）
- ask_user / ask_clarification: 用户交互工具始终可用

## 在中间件管道中的位置

```
wrap_tool_call 洋葱模型（外→内）：
  TracingMiddleware          → 记录 tool span
  AgentLoggingMiddleware     → 打印工具调用日志
  GuardrailMiddleware        → Agent 级权限拦截
  SkillToolScopeMiddleware   → ★ Skill 级作用域隔离（本中间件）
  ToolErrorHandlingMiddleware → 异常捕获
  ClarificationMiddleware    → 拦截 ask_clarification
                ↓
          实际工具执行
```

SkillToolScopeMiddleware 排在 GuardrailMiddleware 之后：
- GuardrailMiddleware 做 Agent 级别的全局权限管控
- SkillToolScopeMiddleware 做 Skill 级别的细粒度作用域隔离
- 两者互补，不冲突
"""

import logging
from typing import Any

from langchain_core.messages import ToolMessage
from langchain.agents.middleware.types import AgentMiddleware
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from src.skills.context import get_skill_context

logger = logging.getLogger(__name__)

# 始终放行的工具（不受 Skill 作用域限制）
_EXEMPT_TOOLS: frozenset[str] = frozenset({
    "skills_tool",       # Skill 嵌套调用
    "ask_user",          # 用户交互
    "ask_clarification", # 追问澄清
})


class SkillToolScopeMiddleware(AgentMiddleware):
    """Skill 级工具作用域隔离 — 运行时验证工具调用是否在 Skill 的 allowed_tools 范围内

    Args:
        exempt_tools: 额外豁免的工具名列表（始终放行，不受 Skill 限制）。
                      默认已包含 skills_tool、ask_user、ask_clarification。
        strict: 严格模式。True = 拦截越权调用并返回错误；False = 仅记录警告不拦截。
                默认 True。
    """

    def __init__(
        self,
        exempt_tools: list[str] | None = None,
        strict: bool = True,
    ) -> None:
        super().__init__()
        self._exempt = _EXEMPT_TOOLS | frozenset(exempt_tools or [])
        self._strict = strict

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
        """检查工具调用是否在当前 Skill 的 allowed_tools 范围内"""
        ctx = get_skill_context()

        # 非 Skill 执行期间 → 放行
        if ctx is None:
            return None

        # allowed_tools 为空 → 不限制（向后兼容：未配置 allowed_tools 的 Skill 不受限）
        if not ctx.allowed_tools:
            return None

        tool_name = request.tool_call.get("name", "")
        tool_call_id = request.tool_call.get("id", "")

        # 豁免工具 → 放行
        if tool_name in self._exempt:
            return None

        # 在允许范围内 → 放行
        if tool_name in ctx.allowed_tools:
            return None

        # 越权调用
        if self._strict:
            logger.warning(
                "SkillToolScope blocked: skill='%s' attempted to call tool='%s' "
                "(allowed: %s)",
                ctx.skill_name, tool_name, sorted(ctx.allowed_tools),
            )
            return ToolMessage(
                content=(
                    f"Error: Tool '{tool_name}' is not allowed for skill '{ctx.skill_name}'. "
                    f"Allowed tools: {sorted(ctx.allowed_tools)}. "
                    f"Please use only the tools within the skill's configured scope."
                ),
                tool_call_id=tool_call_id,
                name=tool_name,
                status="error",
            )
        else:
            # 非严格模式：仅警告，不拦截
            logger.warning(
                "SkillToolScope warning (non-strict): skill='%s' calling tool='%s' "
                "outside allowed scope %s",
                ctx.skill_name, tool_name, sorted(ctx.allowed_tools),
            )
            return None
