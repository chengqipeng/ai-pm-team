"""
QueryEngine — 顶层编排入口
借鉴 QueryEngine.ts:submitMessage()
将 Agent Loop + Skills + Tools + Context + Hooks + Session + MCP + Plugins 组装为完整系统
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from .types import Message, MessageRole, ToolPermissionContext
from .state import AppState, AppStateStore
from .tools import ToolRegistry, ToolUseContext
from .skills import SkillRegistry, register_builtin_skills
from .builtin_tools import register_builtin_tools
from .context import get_system_context, get_user_context, AttachmentManager
from .hooks import HookRegistry, HookExecutor, HookEvent
from .session import SessionStorage
from .plugins import PluginRegistry, LoadedPlugin
from .mcp import McpClientManager, McpServerConfig, McpToolProxy, load_mcp_configs
from .coordinator import CoordinatorContext, filter_coordinator_tools
from .agent import (
    AgentDefinition, AgentLoopConfig, AgentLoopEngine,
    LLMClient, SubAgentRunner, SkillTool, AgentTool,
    get_builtin_agents,
)

logger = logging.getLogger(__name__)


@dataclass
class QueryEngineConfig:
    """引擎配置"""
    llm_client: LLMClient
    model: str = "claude-sonnet-4-20250514"
    max_turns: int = 50
    project_root: str = "."
    custom_system_prompt: str | None = None
    append_system_prompt: str | None = None
    permission_mode: str = "default"
    # 会话
    session_id: str | None = None          # 指定 session_id 用于 resume
    enable_session: bool = True
    # Coordinator 模式
    coordinator_mode: bool = False
    # MCP
    mcp_config_path: str | None = None
    # 插件目录
    plugin_dirs: list[str] = field(default_factory=list)


class QueryEngine:
    """
    查询引擎 — 系统顶层入口 (借鉴 QueryEngine.ts)
    组装所有子系统，提供 submit_message() 接口

    完整初始化流程:
    1. 注册内置工具
    2. 注册内置技能 + 加载文件技能
    3. 加载插件 (skills + hooks + agents)
    4. 连接 MCP 服务器 + 注册 MCP 工具
    5. 构建子 Agent 运行器
    6. 注册 SkillTool + AgentTool
    7. 加载上下文 (system + user)
    8. 初始化 Session 存储
    9. 初始化 Coordinator (如果启用)
    """

    def __init__(self, config: QueryEngineConfig):
        self.config = config
        self.store = AppStateStore(AppState(main_loop_model=config.model))
        self.tool_registry = ToolRegistry()
        self.skill_registry = SkillRegistry()
        self.hook_registry = HookRegistry()
        self.hook_executor = HookExecutor(self.hook_registry)
        self.plugin_registry = PluginRegistry()
        self.mcp_manager = McpClientManager()
        self.attachment_mgr = AttachmentManager()
        self._session: SessionStorage | None = None
        self._coordinator: CoordinatorContext | None = None
        self._messages: list[Message] = []
        self._initialized = False
        self._sub_agent_runner: SubAgentRunner | None = None

    async def initialize(self) -> None:
        """初始化所有子系统"""
        if self._initialized:
            return

        # 1. 注册内置工具
        register_builtin_tools(self.tool_registry)

        # 2. 注册内置技能 + 加载文件技能
        register_builtin_skills(self.skill_registry)
        self.skill_registry.load_all_sources(self.config.project_root)

        # 3. 加载插件
        for plugin_dir in self.config.plugin_dirs:
            plugins = PluginRegistry.load_from_directory(plugin_dir)
            for p in plugins:
                self.plugin_registry.register(p)
        self.plugin_registry.load_skills_into(self.skill_registry)
        self.plugin_registry.load_hooks_into(self.hook_registry)

        # 4. 连接 MCP 服务器
        if self.config.mcp_config_path:
            mcp_configs = load_mcp_configs(self.config.mcp_config_path)
            for mc in mcp_configs:
                conn = await self.mcp_manager.connect(mc)
                # 将 MCP 工具注册为本地工具
                for tool_def in conn.tools:
                    proxy = McpToolProxy(tool_def, self.mcp_manager)
                    self.tool_registry.register(proxy)

        # 5. 构建子 Agent 运行器
        self._sub_agent_runner = SubAgentRunner(
            llm_client=self.config.llm_client,
            tool_registry=self.tool_registry,
            skill_registry=self.skill_registry,
            store=self.store,
        )

        # 6. 注册 SkillTool 和 AgentTool
        skill_tool = SkillTool(self.skill_registry, self._sub_agent_runner)
        self.tool_registry.register(skill_tool)

        builtin_agents = get_builtin_agents()
        agent_tool = AgentTool(builtin_agents, self._sub_agent_runner)
        self.tool_registry.register(agent_tool)

        # 7. 加载上下文
        self._system_context = await get_system_context()
        self._user_context = await get_user_context(self.config.project_root)

        # 8. 初始化 Session
        if self.config.enable_session:
            self._session = SessionStorage(
                project_root=self.config.project_root,
                session_id=self.config.session_id,
            )
            # 如果指定了 session_id，尝试 resume
            if self.config.session_id:
                resumed = await self._session.load_transcript()
                if resumed:
                    self._messages = resumed
                    logger.info(f"Resumed session {self.config.session_id}: {len(resumed)} messages")

        # 9. 初始化 Coordinator
        if self.config.coordinator_mode:
            worker_tools = [
                t.name for t in self.tool_registry.all_tools
                if t.name not in {"agent", "send_message", "task_stop"}
            ]
            self._coordinator = CoordinatorContext(
                worker_tools=worker_tools,
                mcp_servers=self.mcp_manager.connected_servers,
            )

        # 保存元数据
        if self._session:
            await self._session.save_metadata({
                "model": self.config.model,
                "permission_mode": self.config.permission_mode,
                "coordinator_mode": self.config.coordinator_mode,
                "tool_count": len(self.tool_registry.all_tools),
                "skill_count": len(self.skill_registry.all_skills),
                "plugin_count": len(self.plugin_registry.get_enabled_plugins()),
            })

        self._initialized = True

    async def submit_message(self, prompt: str) -> AsyncIterator[Message]:
        """
        提交用户消息 (借鉴 QueryEngine.ts:submitMessage)
        完整流程: 初始化 → 上下文组装 → Agent Loop → 流式返回 → 持久化
        """
        await self.initialize()

        # 构建用户消息
        user_msg = Message(role=MessageRole.USER, content=prompt)
        self._messages.append(user_msg)

        # 持久化用户消息 (借鉴 QueryEngine.ts 在 API 调用前持久化)
        if self._session:
            await self._session.record_transcript(self._messages)

        # 构建 System Prompt
        system_prompt = self._build_full_system_prompt()

        # 构建 Agent Loop 配置
        user_context = dict(self._user_context)
        system_context = dict(self._system_context)

        # Coordinator 模式注入附加上下文
        if self._coordinator:
            user_context.update(self._coordinator.get_user_context())

        loop_config = AgentLoopConfig(
            system_prompt=system_prompt,
            user_context=user_context,
            system_context=system_context,
            max_turns=self.config.max_turns,
        )

        # 构建权限上下文
        perm_ctx = ToolPermissionContext(mode=self.config.permission_mode)

        # 启动 Agent Loop
        engine = AgentLoopEngine(
            llm_client=self.config.llm_client,
            tool_registry=self.tool_registry,
            skill_registry=self.skill_registry,
            store=self.store,
            config=loop_config,
            hook_registry=self.hook_registry,
            session_storage=self._session,
        )

        async for msg in engine.run(
            messages=list(self._messages),
            permission_context=perm_ctx,
        ):
            self._messages.append(msg)
            yield msg

        # 最终持久化
        if self._session:
            await self._session.record_transcript(self._messages)

    async def resume_session(self, session_id: str) -> list[Message]:
        """
        恢复会话 (借鉴 --resume 功能)
        加载 transcript 并返回历史消息
        """
        storage = SessionStorage(
            project_root=self.config.project_root,
            session_id=session_id,
        )
        messages = await storage.load_transcript()
        if messages:
            self._messages = messages
            self._session = storage
        return messages

    async def compact(self, custom_instructions: str | None = None) -> Message | None:
        """
        手动触发压缩 (借鉴 /compact 命令)
        """
        if not self._messages:
            return None

        compressor = ContextCompressor(llm_call=self._compact_llm_call)
        result = await compressor.autocompact(self._messages, self._build_full_system_prompt())
        if not result:
            return None

        # 构建压缩后消息
        boundary = Message(role=MessageRole.SYSTEM, content="[Compact boundary]", is_compact_boundary=True)
        summary = Message(role=MessageRole.USER, content=result.summary)
        self._messages = [boundary, summary]

        # 重置附件管理器
        self.attachment_mgr.reset_after_compact()

        if self._session:
            await self._session.record_transcript(self._messages)

        return summary

    async def _compact_llm_call(self, prompt: str, messages: list[Message]) -> str:
        """用于 autocompact 的 LLM 调用"""
        from .context import ContextCompressor
        api_messages = [{"role": "user", "content": prompt}]
        response = await self.config.llm_client.call(
            system_prompt="Summarize the conversation concisely.",
            messages=api_messages,
            model=self.config.model,
        )
        content = response.get("content", [])
        return "".join(b.get("text", "") for b in content if b.get("type") == "text")

    async def shutdown(self) -> None:
        """关闭引擎，清理资源"""
        await self.mcp_manager.disconnect_all()
        if self._session:
            await self._session.save_metadata({"status": "closed"})

    def _build_full_system_prompt(self) -> str:
        """构建完整 System Prompt"""
        parts = []

        # 自定义 prompt 或默认 prompt
        if self.config.custom_system_prompt:
            parts.append(self.config.custom_system_prompt)
        else:
            parts.append(self._default_system_prompt())

        # Coordinator 模式 prompt
        if self.config.coordinator_mode and self._coordinator:
            parts.append(CoordinatorContext.get_coordinator_system_prompt())

        # 追加 prompt
        if self.config.append_system_prompt:
            parts.append(self.config.append_system_prompt)

        return "\n\n".join(parts)

    def _default_system_prompt(self) -> str:
        tools = self.tool_registry.all_tools
        tool_names = ", ".join(t.name for t in tools)
        return (
            "You are a helpful coding assistant with access to tools.\n"
            f"Available tools: {tool_names}\n\n"
            "Use tools to help the user accomplish their tasks. "
            "When you're done, respond with a clear summary."
        )

    @property
    def messages(self) -> list[Message]:
        return list(self._messages)

    @property
    def session_id(self) -> str | None:
        return self._session.session_id if self._session else None
