"""
Agent 核心 — 借鉴 query.ts / QueryEngine.ts / AgentTool.tsx / runAgent.ts
Agent Loop Engine + 多 Agent 编排 + 容错反思
"""
from __future__ import annotations

import time
import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Awaitable

from .types import (
    Message, MessageRole, ToolUseBlock, ToolResultBlock,
    PermissionDecision, PermissionBehavior, ToolPermissionContext,
    RetryCategory, TaskStatus, create_agent_id,
)
from .state import AppState, AppStateStore
from .tools import Tool, ToolUseContext, ToolRegistry, execute_tools_parallel
from .skills import SkillDefinition, SkillRegistry
from .context import (
    get_system_context, get_user_context,
    ContextCompressor, AttachmentManager, CompactionResult,
)
from .hooks import HookRegistry, HookExecutor, HookEvent
from .session import SessionStorage

logger = logging.getLogger(__name__)


# ─── Agent 定义 (借鉴 loadAgentsDir.ts:BaseAgentDefinition) ───

@dataclass
class AgentDefinition:
    agent_type: str
    when_to_use: str
    tools: list[str] | None = None          # None = 全部
    disallowed_tools: list[str] | None = None
    skills: list[str] | None = None
    model: str | None = None                 # None / "inherit"
    max_turns: int | None = None
    permission_mode: str | None = None
    omit_claude_md: bool = False
    source: str = "built-in"

    get_system_prompt: Callable[[], str] = field(default=lambda: "You are a helpful assistant.")


# ─── LLM 调用抽象 ───

class LLMClient:
    """LLM API 客户端抽象 (可替换为任意 LLM 后端)"""

    async def call(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 8192,
    ) -> dict:
        """
        调用 LLM API，返回响应
        子类需实现具体的 API 调用逻辑
        """
        raise NotImplementedError("Subclass must implement call()")


# ─── API 错误分类与重试 (借鉴 services/api/errors.ts) ───

def categorize_retryable_error(error: Exception) -> RetryCategory:
    """错误分类 (借鉴 categorizeRetryableAPIError)"""
    msg = str(error).lower()
    if "429" in msg or "rate_limit" in msg:
        return RetryCategory.RATE_LIMIT
    if "500" in msg or "internal" in msg:
        return RetryCategory.SERVER_ERROR
    if "529" in msg or "overloaded" in msg:
        return RetryCategory.OVERLOADED
    if "connection" in msg or "timeout" in msg:
        return RetryCategory.NETWORK
    return RetryCategory.NON_RETRYABLE


async def retry_with_backoff(
    fn: Callable[[], Awaitable[Any]],
    max_retries: int = 3,
) -> Any:
    """指数退避重试 (借鉴 withRetry.ts)"""
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as e:
            category = categorize_retryable_error(e)
            if category == RetryCategory.NON_RETRYABLE or attempt == max_retries:
                raise
            base = 10.0 if category == RetryCategory.OVERLOADED else 1.0
            delay = base * (2 ** attempt) + random.random()
            logger.warning(f"Retry {attempt+1}/{max_retries}: {category.value}, waiting {delay:.1f}s")
            await asyncio.sleep(delay)


# ─── 反思与陷入循环检测 (借鉴 stuck skill + query.ts) ───

@dataclass
class ReflectionState:
    """反思状态追踪"""
    consecutive_same_tool: int = 0
    last_tool_name: str | None = None
    consecutive_errors: int = 0
    no_progress_turns: int = 0
    denial_count: int = 0

    SAME_TOOL_THRESHOLD = 3
    ERROR_THRESHOLD = 3
    NO_PROGRESS_THRESHOLD = 5
    DENIAL_THRESHOLD = 5


def detect_stuck_pattern(state: ReflectionState, tool_name: str | None, is_error: bool) -> str | None:
    """
    检测是否陷入循环 (借鉴 stuck skill 的触发逻辑)
    返回反思提示或 None
    """
    if tool_name:
        if tool_name == state.last_tool_name:
            state.consecutive_same_tool += 1
        else:
            state.consecutive_same_tool = 0
        state.last_tool_name = tool_name

    if is_error:
        state.consecutive_errors += 1
    else:
        state.consecutive_errors = 0

    if state.consecutive_same_tool >= state.SAME_TOOL_THRESHOLD:
        state.consecutive_same_tool = 0
        return (
            "[System] You've called the same tool 3+ times consecutively. "
            "Step back and reconsider your approach. Try a different tool or strategy."
        )

    if state.consecutive_errors >= state.ERROR_THRESHOLD:
        state.consecutive_errors = 0
        return (
            "[System] Multiple consecutive errors detected. "
            "Review what's going wrong and try a fundamentally different approach. "
            "Consider using ask_user if you need clarification."
        )

    return None


# ─── Agent Loop Engine (借鉴 query.ts:queryLoop) ───

@dataclass
class AgentLoopConfig:
    system_prompt: str = ""
    user_context: dict[str, str] = field(default_factory=dict)
    system_context: dict[str, str] = field(default_factory=dict)
    max_turns: int = 50
    max_output_tokens_recovery: int = 3


class AgentLoopEngine:
    """
    Agent 循环引擎 — 系统的心脏
    借鉴 query.ts:queryLoop() 的 while(true) + yield 模式
    集成: Hooks + Session + Context Compression + Reflection
    """

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        skill_registry: SkillRegistry,
        store: AppStateStore,
        config: AgentLoopConfig | None = None,
        hook_registry: HookRegistry | None = None,
        session_storage: SessionStorage | None = None,
    ):
        self.llm = llm_client
        self.tools = tool_registry
        self.skills = skill_registry
        self.store = store
        self.config = config or AgentLoopConfig()
        self.compressor = ContextCompressor()
        self.attachment_mgr = AttachmentManager()
        self._reflection = ReflectionState()
        self._hook_registry = hook_registry or HookRegistry()
        self._hook_executor = HookExecutor(self._hook_registry)
        self._session = session_storage
        self._total_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

    async def run(
        self,
        messages: list[Message],
        agent_id: str | None = None,
        permission_context: ToolPermissionContext | None = None,
    ) -> AsyncIterator[Message]:
        """
        Agent 主循环 (借鉴 query.ts:queryLoop)
        完整链路: SessionStart hooks → while(true) { 压缩 → 附件 → API → 工具 → 反思 } → StopHooks
        """
        perm_ctx = permission_context or self.store.get_state().tool_permission_context
        tool_pool = self.tools.assemble_tool_pool(perm_ctx)
        tool_schemas = [self._tool_to_schema(t) for t in tool_pool]

        context = ToolUseContext(
            get_app_state=self.store.get_state,
            set_app_state=self.store.set_state,
            agent_id=agent_id,
            tools=tool_pool,
            main_loop_model=self.store.get_state().main_loop_model,
            messages=messages,
        )

        # ─── SessionStart Hooks (借鉴 utils/hooks.ts) ───
        session_hook_results = await self._hook_executor.execute_session_hooks(
            HookEvent.SESSION_START, {"model": context.main_loop_model},
        )
        for hr in session_hook_results:
            if hr.output:
                hook_msg = Message(role=MessageRole.SYSTEM, content=f"[Hook:{hr.hook_name}] {hr.output}")
                messages.append(hook_msg)

        turn_count = 0
        last_stop_reason: str | None = None

        while True:
            # ─── Step 1: 上下文压缩管线 (借鉴 query.ts 的六策略) ───
            working_messages = list(messages)
            working_messages = self.compressor.apply_tool_result_budget(working_messages)

            estimated_tokens = sum(len(str(m.content)) // 4 for m in working_messages)
            if estimated_tokens > ContextCompressor.AUTOCOMPACT_TRIGGER_TOKENS:
                working_messages, freed = self.compressor.snip_history(working_messages)
                working_messages = self.compressor.microcompact(working_messages)
                logger.info(f"Context compression: snipped {freed} tokens, now {len(working_messages)} messages")

            # ─── Step 2: 动态附件注入 (借鉴 attachments.ts) ───
            attachments = await self.attachment_mgr.get_attachments(
                user_input=None, messages=working_messages,
                tools=tool_pool, agents=[],
            )
            for att in attachments:
                att_msg = Message(role=MessageRole.SYSTEM, content=f"<{att.tag}>\n{att.content}\n</{att.tag}>")
                working_messages.append(att_msg)

            # ─── Step 3: PreQuery Hooks ───
            pre_query_results = await self._hook_executor.execute_session_hooks(
                HookEvent.PRE_QUERY, {"turn_count": turn_count},
            )
            for hr in pre_query_results:
                if hr.output:
                    working_messages.append(Message(role=MessageRole.SYSTEM, content=hr.output))

            # ─── Step 4: 组装 System Prompt ───
            full_prompt = self._build_system_prompt()

            # ─── Step 5: 调用 LLM API (带重试) ───
            api_messages = self._messages_to_api_format(working_messages)

            try:
                response = await retry_with_backoff(
                    lambda: self.llm.call(
                        system_prompt=full_prompt,
                        messages=api_messages,
                        tools=tool_schemas if tool_pool else None,
                        model=context.main_loop_model,
                    )
                )
            except Exception as e:
                error_msg = Message(
                    role=MessageRole.ASSISTANT,
                    content=f"API Error: {e}",
                    api_error=str(e),
                )
                yield error_msg
                return

            # ─── Step 6: 解析响应 ───
            assistant_msg = self._parse_response(response)
            messages.append(assistant_msg)
            last_stop_reason = response.get("stop_reason")

            # 追踪用量
            if assistant_msg.usage:
                self._total_usage["input_tokens"] += assistant_msg.usage.get("input_tokens", 0)
                self._total_usage["output_tokens"] += assistant_msg.usage.get("output_tokens", 0)

            # 持久化 transcript
            if self._session:
                await self._session.record_transcript(messages)

            yield assistant_msg

            # ─── Step 7: 提取 tool_use blocks ───
            tool_uses = assistant_msg.tool_use_blocks
            if not tool_uses:
                # 纯文本响应 → 执行 StopHooks 后结束
                stop_results = await self._hook_executor.execute_session_hooks(
                    HookEvent.SESSION_STOP, {"stop_reason": last_stop_reason, "turn_count": turn_count},
                )
                # StopHook 可以要求继续 (借鉴 query/stopHooks.ts)
                should_continue = any(
                    "continue" in hr.output.lower() for hr in stop_results if hr.output
                )
                if should_continue:
                    # 注入 hook 的 prompt 作为用户消息，继续循环
                    for hr in stop_results:
                        if hr.output and "continue" in hr.output.lower():
                            messages.append(Message(role=MessageRole.USER, content=hr.output))
                            yield Message(role=MessageRole.SYSTEM, content=f"[StopHook:{hr.hook_name}] continuing...")
                    continue
                return

            turn_count += 1
            if turn_count >= self.config.max_turns:
                yield Message(
                    role=MessageRole.SYSTEM,
                    content=f"[Max turns ({self.config.max_turns}) reached]",
                )
                return

            # ─── Step 8: 并行执行工具 (集成 Hooks + Session) ───
            results = await execute_tools_parallel(
                tool_uses, context, perm_ctx, self.tools,
                hook_executor=self._hook_executor,
                session_storage=self._session,
            )

            # ─── Step 9: 反思检测 (借鉴 stuck skill) ───
            for tu, result in zip(tool_uses, results):
                reflection = detect_stuck_pattern(
                    self._reflection, tu.name, result.is_error,
                )
                if reflection:
                    reflection_msg = Message(role=MessageRole.USER, content=reflection)
                    messages.append(reflection_msg)
                    yield reflection_msg

            # ─── Step 10: 权限拒绝追踪 (借鉴 denialTracking.ts) ───
            denial_count = sum(1 for r in results if r.is_error and "Permission denied" in r.content)
            self._reflection.denial_count += denial_count
            if self._reflection.denial_count >= ReflectionState.DENIAL_THRESHOLD:
                self._reflection.denial_count = 0
                yield Message(
                    role=MessageRole.SYSTEM,
                    content="[System] Multiple permission denials. Consider switching approach or asking user.",
                )

            # ─── Step 11: 构建 tool_result 消息 ───
            result_msg = Message(
                role=MessageRole.USER,
                tool_result_blocks=results,
            )
            messages.append(result_msg)

            # 持久化 transcript
            if self._session:
                await self._session.record_transcript(messages)

            yield result_msg

            # 更新上下文
            context.messages = messages

    def _build_system_prompt(self) -> str:
        parts = [self.config.system_prompt]
        for key, value in self.config.system_context.items():
            parts.append(f"<{key}>\n{value}\n</{key}>")
        for key, value in self.config.user_context.items():
            parts.append(f"<{key}>\n{value}\n</{key}>")
        return "\n\n".join(p for p in parts if p)

    def _tool_to_schema(self, tool: Tool) -> dict:
        return {
            "name": tool.name,
            "description": tool.prompt() or f"Tool: {tool.name}",
            "input_schema": tool.input_schema(),
        }

    def _messages_to_api_format(self, messages: list[Message]) -> list[dict]:
        api_msgs = []
        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                continue
            entry: dict[str, Any] = {"role": msg.role.value}
            if msg.tool_use_blocks:
                entry["content"] = [
                    {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
                    for b in msg.tool_use_blocks
                ]
            elif msg.tool_result_blocks:
                entry["content"] = [
                    {"type": "tool_result", "tool_use_id": b.tool_use_id,
                     "content": b.content, "is_error": b.is_error}
                    for b in msg.tool_result_blocks
                ]
            else:
                entry["content"] = str(msg.content)
            api_msgs.append(entry)
        return api_msgs

    def _parse_response(self, response: dict) -> Message:
        content_blocks = response.get("content", [])
        text_parts = []
        tool_uses = []
        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                tool_uses.append(ToolUseBlock(
                    id=block["id"],
                    name=block["name"],
                    input=block.get("input", {}),
                ))
        return Message(
            role=MessageRole.ASSISTANT,
            content="\n".join(text_parts),
            tool_use_blocks=tool_uses,
            usage=response.get("usage"),
        )


# ─── 子 Agent 执行 (借鉴 AgentTool.tsx + runAgent.ts) ───

class SubAgentRunner:
    """
    子 Agent 运行器 (借鉴 runAgent.ts)
    独立工具池 + 权限隔离 + 上下文裁剪
    """

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        skill_registry: SkillRegistry,
        store: AppStateStore,
    ):
        self.llm = llm_client
        self.tools = tool_registry
        self.skills = skill_registry
        self.store = store

    async def run_agent(
        self,
        agent_def: AgentDefinition,
        prompt: str,
        parent_context: ToolUseContext | None = None,
        parent_messages: list[Message] | None = None,
        is_fork: bool = False,
    ) -> str:
        """
        启动子 Agent (借鉴 runAgent.ts:248)
        命名 Agent: 独立上下文 + 独立工具池
        Fork Agent: 继承父上下文 + 共享工具池
        """
        agent_id = create_agent_id()

        # 1. 构建权限上下文 (借鉴 runAgent.ts:agentGetAppState)
        parent_state = self.store.get_state()
        perm_mode = agent_def.permission_mode or "acceptEdits"
        perm_ctx = ToolPermissionContext(
            mode=perm_mode,
            always_allow_rules=parent_state.tool_permission_context.always_allow_rules,
            always_deny_rules=parent_state.tool_permission_context.always_deny_rules,
        )

        # 2. 独立组装工具池 (借鉴 AgentTool.tsx:573)
        all_tools = self.tools.assemble_tool_pool(perm_ctx)
        resolved_tools = self._resolve_agent_tools(agent_def, all_tools)

        # 3. 构建子 Agent 的工具注册表
        sub_registry = ToolRegistry()
        for tool in resolved_tools:
            sub_registry.register(tool)

        # 4. 构建上下文 (借鉴 runAgent.ts 的上下文裁剪)
        system_context = await get_system_context()
        user_context = await get_user_context()

        # 只读 Agent 省略 CLAUDE.md (借鉴 runAgent.ts:shouldOmitClaudeMd)
        if agent_def.omit_claude_md:
            user_context = {k: v for k, v in user_context.items() if k != "claude_md"}

        # Explore/Plan 省略 Git 状态
        if agent_def.agent_type in ("Explore", "Plan"):
            system_context = {k: v for k, v in system_context.items() if k != "git_status"}

        # 5. 构建初始消息
        if is_fork and parent_messages:
            # Fork: 继承父上下文 (借鉴 forkSubagent.ts)
            initial_messages = list(parent_messages)
            initial_messages.append(Message(role=MessageRole.USER, content=prompt))
        else:
            # 命名 Agent: 全新上下文
            initial_messages = [Message(role=MessageRole.USER, content=prompt)]

        # 6. 运行 Agent Loop
        config = AgentLoopConfig(
            system_prompt=agent_def.get_system_prompt(),
            user_context=user_context,
            system_context=system_context,
            max_turns=agent_def.max_turns or 30,
        )

        engine = AgentLoopEngine(
            llm_client=self.llm,
            tool_registry=sub_registry,
            skill_registry=self.skills,
            store=self.store,
            config=config,
        )

        # 收集结果
        result_parts: list[str] = []
        async for msg in engine.run(initial_messages, agent_id=agent_id, permission_context=perm_ctx):
            if msg.role == MessageRole.ASSISTANT and msg.content:
                result_parts.append(str(msg.content))

        return "\n".join(result_parts) if result_parts else "[Agent completed with no output]"

    def _resolve_agent_tools(
        self, agent_def: AgentDefinition, available: list[Tool]
    ) -> list[Tool]:
        """工具过滤 (借鉴 runAgent.ts:resolveAgentTools)"""
        if agent_def.tools and "*" in agent_def.tools:
            result = available
        elif agent_def.tools:
            allow_set = set(agent_def.tools)
            result = [t for t in available if t.name in allow_set]
        else:
            result = available

        if agent_def.disallowed_tools:
            deny_set = set(agent_def.disallowed_tools)
            result = [t for t in result if t.name not in deny_set]

        return result


# ─── SkillTool — 技能调用工具 (借鉴 SkillTool.ts) ───

class SkillTool(Tool):
    """
    技能调用工具 (借鉴 SkillTool.ts)
    统一入口: 查找技能 → 判断执行模式 → inline/fork 执行
    """

    def __init__(
        self,
        skill_registry: SkillRegistry,
        sub_agent_runner: SubAgentRunner | None = None,
    ):
        self._skills = skill_registry
        self._runner = sub_agent_runner

    @property
    def name(self) -> str:
        return "skill"

    async def description(self, input_data: dict) -> str:
        skill_name = input_data.get("skill_name", "")
        return f"Execute skill: {skill_name}"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "skill_name": {"type": "string"},
                "args": {"type": "string", "default": ""},
            },
            "required": ["skill_name"],
        }

    async def call(self, input_data: dict, context: ToolUseContext, on_progress=None) -> ToolResult:
        skill_name = input_data["skill_name"]
        args = input_data.get("args", "")

        skill = self._skills.find(skill_name)
        if not skill:
            return ToolResult(content=f"Unknown skill: {skill_name}", is_error=True)

        if not skill.get_prompt:
            return ToolResult(content=f"Skill '{skill_name}' has no prompt", is_error=True)

        prompt = await skill.get_prompt(args)

        # 执行模式判断 (借鉴 SkillTool.ts)
        if skill.context == "inline":
            return ToolResult(content=prompt)

        # fork 模式: 启动独立子 Agent
        if self._runner:
            agent_def = AgentDefinition(
                agent_type=f"skill-{skill_name}",
                when_to_use=skill.description,
                tools=skill.allowed_tools,
                model=skill.model,
                source="skill",
                get_system_prompt=lambda: prompt,
            )
            result = await self._runner.run_agent(agent_def, prompt)
            return ToolResult(content=result)

        return ToolResult(content=prompt)

    @property
    def max_result_size_chars(self) -> int:
        return 100_000

    def prompt(self) -> str:
        skills = self._skills.all_skills
        if not skills:
            return "Execute a skill by name."
        listing = "\n".join(f"- {s.name}: {s.description}" for s in skills)
        return f"Execute a skill. Available skills:\n{listing}"


# ─── AgentTool — 子 Agent 启动工具 (借鉴 AgentTool.tsx) ───

class AgentTool(Tool):
    """
    子 Agent 启动工具 (借鉴 AgentTool.tsx)
    支持命名 Agent 和 Fork 两种模式
    """

    def __init__(
        self,
        agent_definitions: list[AgentDefinition],
        sub_agent_runner: SubAgentRunner,
    ):
        self._agents = {a.agent_type: a for a in agent_definitions}
        self._runner = sub_agent_runner

    @property
    def name(self) -> str:
        return "agent"

    async def description(self, input_data: dict) -> str:
        return f"Launch agent: {input_data.get('subagent_type', 'general')}"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "subagent_type": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["prompt"],
        }

    async def call(self, input_data: dict, context: ToolUseContext, on_progress=None) -> ToolResult:
        prompt = input_data["prompt"]
        agent_type = input_data.get("subagent_type")

        if agent_type and agent_type in self._agents:
            agent_def = self._agents[agent_type]
        else:
            # 默认通用 Agent
            agent_def = AgentDefinition(
                agent_type="general",
                when_to_use="General purpose task execution",
                get_system_prompt=lambda: "You are a helpful coding assistant.",
            )

        result = await self._runner.run_agent(agent_def, prompt)
        return ToolResult(content=result)

    def prompt(self) -> str:
        lines = ["Launch a sub-agent for complex tasks. Available types:"]
        for a in self._agents.values():
            tools_desc = ", ".join(a.disallowed_tools or []) if a.disallowed_tools else "All"
            lines.append(f"- {a.agent_type}: {a.when_to_use} (Disallowed: {tools_desc})")
        return "\n".join(lines)


# ─── 内置 Agent 定义 (借鉴 builtInAgents.ts) ───

def get_builtin_agents() -> list[AgentDefinition]:
    return [
        AgentDefinition(
            agent_type="Explore",
            when_to_use="Fast read-only codebase exploration and search",
            disallowed_tools=["agent", "file_edit", "file_write"],
            model="inherit",
            omit_claude_md=True,
            max_turns=20,
            get_system_prompt=lambda: (
                "You are a file search specialist. READ-ONLY mode.\n"
                "Use grep, glob, file_read, and bash (read-only commands only).\n"
                "NEVER create, modify, or delete files."
            ),
        ),
        AgentDefinition(
            agent_type="Plan",
            when_to_use="Create implementation plans without making changes",
            disallowed_tools=["file_edit", "file_write"],
            model="inherit",
            omit_claude_md=True,
            max_turns=15,
            get_system_prompt=lambda: (
                "You are a planning specialist. Analyze the codebase and create "
                "a detailed implementation plan. Do NOT make any file changes."
            ),
        ),
        AgentDefinition(
            agent_type="Verification",
            when_to_use="Verify code changes by running tests and checks",
            disallowed_tools=["file_edit", "file_write"],
            model="inherit",
            max_turns=10,
            get_system_prompt=lambda: (
                "You are a verification specialist. Run tests, check for errors, "
                "and validate that recent changes are correct."
            ),
        ),
    ]
