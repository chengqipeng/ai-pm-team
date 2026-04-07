"""
Hooks 系统 — 借鉴 utils/hooks.ts / utils/settings/types.ts
支持 pre/post tool use, session start/stop, pre/post compact 等生命周期钩子。

Hook 是 Agent 系统的"切面编程"机制：
- PreToolUse: 工具执行前拦截，可修改输入或拒绝执行
- PostToolUse: 工具执行后处理，可审计、记录、触发后续动作
- SessionStart: 会话开始或压缩后触发
- PreCompact: 压缩前触发，可注入自定义压缩指令
- StopHook: Agent 循环结束前触发，可决定是否继续

借鉴源码:
  - src/utils/settings/types.ts: HooksSchema 定义
  - src/utils/hooks.ts: executePreCompactHooks, executeStopFailureHooks
  - src/utils/hooks/postSamplingHooks.ts: executePostSamplingHooks
  - src/hooks/useCanUseTool.tsx: 权限检查中的 hook 集成
  - src/query/stopHooks.ts: handleStopHooks
"""
from __future__ import annotations

import re
import time
import logging
import asyncio
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


# ─── Hook 事件类型 ───

class HookEvent(str, Enum):
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    SESSION_START = "session_start"
    SESSION_STOP = "session_stop"
    PRE_COMPACT = "pre_compact"
    POST_COMPACT = "post_compact"
    PRE_QUERY = "pre_query"       # 每轮 API 调用前
    POST_QUERY = "post_query"     # 每轮 API 调用后


# ─── Hook 匹配条件 ───

@dataclass
class HookMatcher:
    """
    Hook 触发条件 (借鉴 HooksSchema 的 matcher 字段)
    支持工具名精确匹配、正则匹配、分类匹配
    """
    tool_name: str | None = None       # 精确匹配工具名
    tool_pattern: str | None = None    # 正则匹配工具名
    tool_category: str | None = None   # 分类匹配: "read" / "write" / "shell" / "*"
    input_pattern: str | None = None   # 匹配输入内容的正则

    # 工具分类映射 (借鉴 preToolUse/postToolUse 的 toolTypes)
    CATEGORY_MAP: dict[str, set[str]] = field(default_factory=lambda: {
        "read": {"file_read", "grep", "glob", "web_fetch", "web_search"},
        "write": {"file_write", "file_edit", "notebook_edit"},
        "shell": {"bash", "powershell"},
        "agent": {"agent", "send_message", "task_stop"},
    }, repr=False)

    def matches(self, tool_name: str, input_data: dict | None = None) -> bool:
        """判断是否匹配"""
        # 通配符
        if self.tool_name == "*" or self.tool_category == "*":
            return True

        # 精确匹配
        if self.tool_name and self.tool_name == tool_name:
            return True

        # 正则匹配
        if self.tool_pattern:
            try:
                if re.search(self.tool_pattern, tool_name):
                    return True
            except re.error:
                pass

        # 分类匹配
        if self.tool_category and self.tool_category in self.CATEGORY_MAP:
            if tool_name in self.CATEGORY_MAP[self.tool_category]:
                return True

        # 输入内容匹配
        if self.input_pattern and input_data:
            input_str = str(input_data)
            try:
                if re.search(self.input_pattern, input_str):
                    return True
            except re.error:
                pass

        return False


# ─── Hook 动作类型 ───

class HookActionType(str, Enum):
    ASK_AGENT = "ask_agent"      # 发送 prompt 给 agent
    RUN_COMMAND = "run_command"   # 执行 shell 命令


@dataclass
class HookAction:
    """Hook 触发后的动作"""
    type: HookActionType
    prompt: str | None = None    # ask_agent 时的 prompt
    command: str | None = None   # run_command 时的命令
    timeout: int = 60            # 命令超时秒数


# ─── Hook 定义 ───

@dataclass
class HookDefinition:
    """
    完整的 Hook 定义 (借鉴 HooksSchema)
    对应 .kiro/hooks/*.json 或 skill frontmatter 中的 hooks 字段
    """
    name: str
    event: HookEvent
    matcher: HookMatcher = field(default_factory=HookMatcher)
    action: HookAction = field(default_factory=lambda: HookAction(type=HookActionType.ASK_AGENT))
    enabled: bool = True
    source: str = "user"  # user / project / skill / plugin


# ─── Hook 执行结果 ───

@dataclass
class HookResult:
    """Hook 执行结果"""
    hook_name: str
    success: bool
    output: str = ""
    duration_ms: float = 0
    prevented_continuation: bool = False  # 是否阻止了后续操作
    modified_input: dict | None = None    # PreToolUse 可修改输入


# ─── Hook 注册表与执行器 ───

class HookRegistry:
    """
    Hook 注册表 (借鉴 utils/hooks.ts)
    管理所有已注册的 hooks，按事件类型分组
    """

    def __init__(self):
        self._hooks: dict[HookEvent, list[HookDefinition]] = {
            event: [] for event in HookEvent
        }

    def register(self, hook: HookDefinition) -> None:
        """注册一个 hook"""
        self._hooks[hook.event].append(hook)
        logger.debug(f"Hook registered: {hook.name} on {hook.event.value}")

    def unregister(self, hook_name: str) -> bool:
        """注销一个 hook"""
        for event, hooks in self._hooks.items():
            for i, h in enumerate(hooks):
                if h.name == hook_name:
                    hooks.pop(i)
                    return True
        return False

    def get_hooks(self, event: HookEvent) -> list[HookDefinition]:
        """获取某事件的所有已启用 hooks"""
        return [h for h in self._hooks[event] if h.enabled]

    def get_matching_hooks(
        self, event: HookEvent, tool_name: str, input_data: dict | None = None
    ) -> list[HookDefinition]:
        """获取匹配特定工具的 hooks"""
        return [
            h for h in self.get_hooks(event)
            if h.matcher.matches(tool_name, input_data)
        ]

    @property
    def all_hooks(self) -> list[HookDefinition]:
        result = []
        for hooks in self._hooks.values():
            result.extend(hooks)
        return result


class HookExecutor:
    """
    Hook 执行器 (借鉴 utils/hooks.ts 的各 execute* 函数)
    负责实际执行 hook 动作并收集结果
    """

    def __init__(self, registry: HookRegistry):
        self._registry = registry

    async def execute_pre_tool_use(
        self, tool_name: str, input_data: dict
    ) -> list[HookResult]:
        """
        执行 PreToolUse hooks (借鉴 useCanUseTool.tsx 中的 hook 集成)
        返回结果列表，调用方检查是否有 prevented_continuation
        """
        hooks = self._registry.get_matching_hooks(
            HookEvent.PRE_TOOL_USE, tool_name, input_data
        )
        results = []
        for hook in hooks:
            result = await self._execute_single(hook, {
                "tool_name": tool_name,
                "input": input_data,
            })
            results.append(result)
            # 如果某个 hook 阻止了执行，后续 hooks 不再运行
            if result.prevented_continuation:
                break
        return results

    async def execute_post_tool_use(
        self, tool_name: str, input_data: dict, output: str, is_error: bool
    ) -> list[HookResult]:
        """执行 PostToolUse hooks"""
        hooks = self._registry.get_matching_hooks(
            HookEvent.POST_TOOL_USE, tool_name, input_data
        )
        results = []
        for hook in hooks:
            result = await self._execute_single(hook, {
                "tool_name": tool_name,
                "input": input_data,
                "output": output,
                "is_error": is_error,
            })
            results.append(result)
        return results

    async def execute_session_hooks(
        self, event: HookEvent, context: dict | None = None
    ) -> list[HookResult]:
        """执行 Session 级别 hooks (start/stop/compact)"""
        hooks = self._registry.get_hooks(event)
        results = []
        for hook in hooks:
            result = await self._execute_single(hook, context or {})
            results.append(result)
        return results

    async def _execute_single(
        self, hook: HookDefinition, context: dict
    ) -> HookResult:
        """执行单个 hook"""
        start = time.monotonic()
        try:
            if hook.action.type == HookActionType.RUN_COMMAND:
                output = await self._run_command(hook.action, context)
            elif hook.action.type == HookActionType.ASK_AGENT:
                output = self._format_agent_prompt(hook.action, context)
            else:
                output = ""

            duration = (time.monotonic() - start) * 1000

            # 检查输出是否包含拒绝信号
            prevented = self._check_denial(output)

            return HookResult(
                hook_name=hook.name,
                success=True,
                output=output,
                duration_ms=duration,
                prevented_continuation=prevented,
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            logger.error(f"Hook '{hook.name}' failed: {e}")
            return HookResult(
                hook_name=hook.name,
                success=False,
                output=str(e),
                duration_ms=duration,
            )

    async def _run_command(self, action: HookAction, context: dict) -> str:
        """执行 shell 命令"""
        if not action.command:
            return ""
        try:
            proc = await asyncio.create_subprocess_shell(
                action.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=action.timeout
            )
            output = stdout.decode("utf-8", errors="replace")
            if stderr:
                output += "\n" + stderr.decode("utf-8", errors="replace")
            return output.strip()
        except asyncio.TimeoutError:
            return f"[Hook command timed out after {action.timeout}s]"
        except Exception as e:
            return f"[Hook command error: {e}]"

    def _format_agent_prompt(self, action: HookAction, context: dict) -> str:
        """格式化 agent prompt，替换上下文变量"""
        prompt = action.prompt or ""
        # 替换 {{tool_name}}, {{input}} 等占位符
        for key, value in context.items():
            placeholder = "{{" + key + "}}"
            prompt = prompt.replace(placeholder, str(value))
        return prompt

    def _check_denial(self, output: str) -> bool:
        """
        检查 hook 输出是否包含拒绝信号
        (借鉴 preToolUse hook 的 access denial 检测)
        """
        denial_patterns = [
            "access denied", "permission denied", "not allowed",
            "forbidden", "rejected", "blocked",
        ]
        lower = output.lower()
        return any(p in lower for p in denial_patterns)
