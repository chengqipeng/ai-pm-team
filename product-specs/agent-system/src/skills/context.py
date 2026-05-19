"""Skill 执行上下文 — 通过 contextvars 传递当前正在执行的 Skill 信息

用于 SkillToolScopeMiddleware 在 wrap_tool_call 阶段读取当前 Skill 的 allowed_tools，
实现运行时工具作用域隔离。

## 使用方式

### inline 模式
SkillsTool._arun() 在返回 prompt 前设置上下文：
    set_skill_context(skill_name, skill.allowed_tools, "inline")
    return prompt
    # 上下文持续到下一次 skill 调用或 agent 执行结束

### fork 模式
SkillExecutor._execute_fork() 在子 Agent 执行前后设置/清除上下文：
    token = set_skill_context(skill_name, skill.allowed_tools, "fork")
    try:
        result = await agent.ainvoke(...)
    finally:
        clear_skill_context(token)

### 中间件读取
SkillToolScopeMiddleware 在 wrap_tool_call 中读取：
    ctx = get_skill_context()
    if ctx and ctx.allowed_tools and tool_name not in ctx.allowed_tools:
        return blocked(...)
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SkillContext:
    """当前正在执行的 Skill 上下文信息"""
    skill_name: str
    allowed_tools: frozenset[str]  # 允许调用的工具集合（空集 = 不限制）
    context_mode: str = "inline"   # inline | fork


# ContextVar：存储当前线程/协程的 Skill 执行上下文
_current_skill_context: contextvars.ContextVar[SkillContext | None] = contextvars.ContextVar(
    "current_skill_context", default=None
)


def set_skill_context(
    skill_name: str,
    allowed_tools: list[str] | frozenset[str],
    context_mode: str = "inline",
) -> contextvars.Token:
    """设置当前 Skill 执行上下文，返回 Token 用于后续清除

    对于 inline 模式：调用后上下文持续存在，直到下一次 set 或 clear。
    对于 fork 模式：应在 try/finally 中配合 clear_skill_context 使用。
    """
    tools = frozenset(allowed_tools) if not isinstance(allowed_tools, frozenset) else allowed_tools
    ctx = SkillContext(
        skill_name=skill_name,
        allowed_tools=tools,
        context_mode=context_mode,
    )
    return _current_skill_context.set(ctx)


def get_skill_context() -> SkillContext | None:
    """获取当前 Skill 执行上下文，无上下文时返回 None"""
    return _current_skill_context.get()


def clear_skill_context(token: contextvars.Token) -> None:
    """清除 Skill 执行上下文（恢复到设置前的状态）"""
    _current_skill_context.reset(token)


def reset_skill_context() -> contextvars.Token:
    """无条件清除 Skill 执行上下文（不需要 token）

    用于 Skill 执行完成后清除上下文，例如 inline 模式下
    LLM 完成 Skill 指令后的清理。
    """
    return _current_skill_context.set(None)
