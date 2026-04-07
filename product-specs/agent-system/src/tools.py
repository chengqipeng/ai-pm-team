"""
Tools 体系 — 借鉴 Tool.ts / tools.ts
统一 Tool 接口 + 工厂模式 + 权限控制 + 结果预算
"""
from __future__ import annotations

import json
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from .types import (
    ToolResult, ToolUseBlock, ToolResultBlock, ValidationResult,
    PermissionDecision, PermissionBehavior, ToolPermissionContext,
    Message, MessageRole,
)


# ─── Tool 统一接口 (借鉴 Tool.ts:362) ───

class Tool(ABC):
    """
    工具基类 — 35+ 字段结构化类型的 Python 等价物
    所有工具必须实现 name / description / input_schema / call
    """

    # ===== 核心四要素 =====
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def description(self, input_data: dict) -> str: ...

    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema 格式的输入定义"""
        ...

    @abstractmethod
    async def call(
        self,
        input_data: dict,
        context: ToolUseContext,
        on_progress: Callable[[Any], None] | None = None,
    ) -> ToolResult: ...

    # ===== 注册与发现 =====
    @property
    def aliases(self) -> list[str]:
        return []

    @property
    def search_hint(self) -> str | None:
        return None

    @property
    def should_defer(self) -> bool:
        return False

    def is_enabled(self) -> bool:
        return True

    # ===== 安全与权限 =====
    def validate_input(self, input_data: dict) -> ValidationResult:
        return ValidationResult(valid=True)

    async def check_permissions(
        self, input_data: dict, context: ToolUseContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior=PermissionBehavior.ALLOW)

    def is_read_only(self, input_data: dict) -> bool:
        return False

    def is_destructive(self, input_data: dict) -> bool:
        return False

    # ===== 输出控制 =====
    @property
    def max_result_size_chars(self) -> int:
        return 50_000

    def map_result(self, result: ToolResult) -> ToolResultBlock:
        return ToolResultBlock(
            tool_use_id="",
            content=result.content,
            is_error=result.is_error,
        )

    # ===== Prompt 注入 =====
    def prompt(self) -> str:
        return ""


# ─── ToolUseContext (借鉴 Tool.ts:ToolUseContext) ───

@dataclass
class ToolUseContext:
    """贯穿整个调用链的工具执行上下文"""
    get_app_state: Callable
    set_app_state: Callable
    agent_id: str | None = None
    query_tracking: dict | None = None
    tools: list[Tool] = field(default_factory=list)
    main_loop_model: str = "claude-sonnet-4-20250514"
    read_file_state: dict[str, str] = field(default_factory=dict)
    messages: list[Message] = field(default_factory=list)


# ─── 工具注册表 (借鉴 tools.ts:getTools / getAllBaseTools) ───

class ToolRegistry:
    """
    工具注册与组装 (借鉴 tools.ts)
    支持固定工具 + 条件工具 + MCP 工具 + 权限过滤
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._alias_map: dict[str, str] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        for alias in tool.aliases:
            self._alias_map[alias] = tool.name

    def find_by_name(self, name: str) -> Tool | None:
        """查找工具 (借鉴 Tool.ts:findToolByName)"""
        if name in self._tools:
            return self._tools[name]
        canonical = self._alias_map.get(name)
        if canonical:
            return self._tools.get(canonical)
        return None

    def assemble_tool_pool(
        self, permission_context: ToolPermissionContext
    ) -> list[Tool]:
        """
        组装工具池 (借鉴 tools.ts:assembleToolPool)
        1. 收集所有已启用工具
        2. 应用权限过滤
        """
        enabled = [t for t in self._tools.values() if t.is_enabled()]
        return self._filter_by_deny_rules(enabled, permission_context)

    def _filter_by_deny_rules(
        self, tools: list[Tool], ctx: ToolPermissionContext
    ) -> list[Tool]:
        deny_set = set(ctx.always_deny_rules)
        return [t for t in tools if t.name not in deny_set]

    @property
    def all_tools(self) -> list[Tool]:
        return list(self._tools.values())


# ─── 权限检查 (借鉴 useCanUseTool.tsx) ───

async def can_use_tool(
    tool: Tool,
    input_data: dict,
    context: ToolUseContext,
    permission_context: ToolPermissionContext,
) -> PermissionDecision:
    """
    权限检查链 (借鉴 useCanUseTool.tsx)
    1. 规则匹配 (always_allow / always_deny)
    2. 工具自身权限检查
    3. 后台 Agent 自动拒绝
    """
    # 始终允许规则
    if tool.name in permission_context.always_allow_rules:
        return PermissionDecision(behavior=PermissionBehavior.ALLOW)

    # 始终拒绝规则
    if tool.name in permission_context.always_deny_rules:
        return PermissionDecision(
            behavior=PermissionBehavior.DENY,
            reason=f"Tool '{tool.name}' is in deny list",
        )

    # 工具自身权限检查
    tool_decision = await tool.check_permissions(input_data, context)
    if tool_decision.behavior != PermissionBehavior.ASK:
        return tool_decision

    # 后台 Agent 不能弹出确认
    if permission_context.should_avoid_prompts:
        return PermissionDecision(
            behavior=PermissionBehavior.DENY,
            reason="Background agent cannot prompt user",
        )

    # bypassPermissions 模式
    if permission_context.mode == "bypassPermissions":
        return PermissionDecision(behavior=PermissionBehavior.ALLOW)

    # acceptEdits 模式: 非破坏性操作自动允许
    if permission_context.mode == "acceptEdits" and not tool.is_destructive(input_data):
        return PermissionDecision(behavior=PermissionBehavior.ALLOW)

    return tool_decision


# ─── 工具执行编排 (借鉴 toolOrchestration.ts:runTools) ───

async def execute_tool_use(
    tool_use: ToolUseBlock,
    context: ToolUseContext,
    permission_context: ToolPermissionContext,
    registry: ToolRegistry,
    hook_executor: Any | None = None,
    session_storage: Any | None = None,
) -> ToolResultBlock:
    """
    单个工具调用的完整链路 (借鉴 what-are-tools.mdx)
    findTool → preHook → validate → permission → call → postHook → budget → persist
    """
    import time as _time
    start_time = _time.monotonic()

    # Step 1: 查找工具
    tool = registry.find_by_name(tool_use.name)
    if not tool:
        return ToolResultBlock(
            tool_use_id=tool_use.id,
            content=f"Error: Unknown tool '{tool_use.name}'",
            is_error=True,
        )

    # Step 2: PreToolUse Hooks (借鉴 useCanUseTool.tsx 中的 hook 集成)
    if hook_executor:
        hook_results = await hook_executor.execute_pre_tool_use(
            tool_use.name, tool_use.input,
        )
        for hr in hook_results:
            if hr.prevented_continuation:
                return ToolResultBlock(
                    tool_use_id=tool_use.id,
                    content=f"Blocked by hook '{hr.hook_name}': {hr.output}",
                    is_error=True,
                )
            # Hook 可修改输入
            if hr.modified_input:
                tool_use = ToolUseBlock(
                    id=tool_use.id, name=tool_use.name, input=hr.modified_input,
                )

    # Step 3: 输入校验
    validation = tool.validate_input(tool_use.input)
    if not validation.valid:
        return ToolResultBlock(
            tool_use_id=tool_use.id,
            content=f"Validation error: {validation.message}",
            is_error=True,
        )

    # Step 4: 权限检查
    decision = await can_use_tool(tool, tool_use.input, context, permission_context)
    if decision.behavior == PermissionBehavior.DENY:
        return ToolResultBlock(
            tool_use_id=tool_use.id,
            content=f"Permission denied: {decision.reason or 'rejected'}",
            is_error=True,
        )

    # Step 5: 执行
    try:
        result = await tool.call(
            decision.updated_input or tool_use.input,
            context,
        )
    except Exception as e:
        error_content = f"Tool execution error: {e}"
        # PostToolUse Hooks (即使失败也执行)
        if hook_executor:
            await hook_executor.execute_post_tool_use(
                tool_use.name, tool_use.input, error_content, is_error=True,
            )
        return ToolResultBlock(
            tool_use_id=tool_use.id,
            content=error_content,
            is_error=True,
        )

    # Step 6: PostToolUse Hooks
    if hook_executor:
        await hook_executor.execute_post_tool_use(
            tool_use.name, tool_use.input, result.content, result.is_error,
        )

    # Step 7: 结果预算控制 + 持久化 (借鉴 toolResultStorage.ts)
    content = result.content
    budget = tool.max_result_size_chars
    if len(content) > budget:
        # 大结果持久化到磁盘
        if session_storage:
            file_path = await session_storage.persist_tool_result(
                tool_use.id, content,
            )
            if file_path:
                preview = content[:500]
                content = (
                    f"{preview}\n\n"
                    f"[Full output ({len(content):,} chars) saved to: {file_path}]"
                )
            else:
                content = content[:budget] + f"\n[Truncated: exceeded {budget:,} char limit]"
        else:
            content = content[:budget] + f"\n[Truncated: exceeded {budget:,} char limit]"

    duration_ms = (_time.monotonic() - start_time) * 1000
    return ToolResultBlock(
        tool_use_id=tool_use.id,
        content=content,
        is_error=result.is_error,
    )


async def execute_tools_parallel(
    tool_uses: list[ToolUseBlock],
    context: ToolUseContext,
    permission_context: ToolPermissionContext,
    registry: ToolRegistry,
    hook_executor: Any | None = None,
    session_storage: Any | None = None,
) -> list[ToolResultBlock]:
    """并行执行多个工具调用"""
    tasks = [
        execute_tool_use(tu, context, permission_context, registry, hook_executor, session_storage)
        for tu in tool_uses
    ]
    return list(await asyncio.gather(*tasks))
